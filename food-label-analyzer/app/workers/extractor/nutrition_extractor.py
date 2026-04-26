"""营养成分解析器，优先读表格结构，失败时再从 OCR 文本兜底解析。"""


from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

import structlog
from openai import OpenAI

from app.core.config import get_settings
from app.schemas.analysis_data import NutritionData
from app.workers.extractor.prompts.nutrition_table_llm_parse import (
    build_nutrition_table_llm_parse_prompt,
)

logger = structlog.get_logger(__name__)

_VALUE_UNIT_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kJ|kj|KJ|kcal|Kcal|mg|g|ug|μg|克|毫克|千焦)",
    re.IGNORECASE,
)
_PERCENT_PATTERN = re.compile(r"(?:\d+(?:\.\d+)?\s*%|%\s*\d+(?:\.\d+)?)")
_PLAIN_NUTRIENT_TOKENS = (
    "反式脂肪",
    "饱和脂肪",
    "碳水化合物",
    "膳食纤维",
    "胆固醇",
    "蛋白质",
    "总脂肪",
    "维生素",
    "脂肪",
    "能量",
    "热量",
    "糖",
    "钠",
    "钙",
    "铁",
    "锌",
    "钾",
    "镁",
)
_PLAIN_TEXT_HEADER_TOKENS = {"营养成分表", "项目", "NRV", "NRV%"}


class _NutritionHTMLTableParser(HTMLParser):
    """把 OCR 返回的 HTML 表格解析成行列数据。"""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif (
            tag in {"td", "th"}
            and self._current_table is not None
            and self._current_row is not None
        ):
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None:
            cell_text = _normalize_cell_text("".join(self._current_cell))
            if self._current_row is not None:
                self._current_row.append(cell_text)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(self._current_row):
                row = [cell for cell in self._current_row if cell]
                if row and self._current_table is not None:
                    self._current_table.append(row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = None


def _get_llm_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        base_url=settings.DEEPSEEK_BASE_URL,
        api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
        timeout=settings.DEEPSEEK_TIMEOUT,
        max_retries=settings.DEEPSEEK_MAX_RETRIES,
    )


def _build_result(
    items: list[dict[str, Any]],
    serving_size: str | None,
    parse_method: str,
    advice_summary: str | None = None,
) -> dict[str, Any]:
    return NutritionData(
        items=items,
        serving_size=serving_size,
        advice_summary=advice_summary,
        parse_method=parse_method,
    ).model_dump()


def _normalize_cell_text(value: Any) -> str:
    """去掉单元格里的多余空白。"""
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value)).strip()


def _normalize_ocr_value_text(value: Any) -> str:
    """修正 OCR 常见误读，比如把 Og 当成 0g。"""
    normalized = str(value or "")
    return re.sub(
        r"(?i)(?<![a-z])[oO](?=\s*(?:g|mg|ug|μg|kj|kcal|克|毫克|千焦))",
        "0",
        normalized,
    )


def _normalize_unit(unit: str) -> str:
    normalized = unit.strip()
    lower = normalized.lower()
    if lower == "kj" or normalized == "千焦":
        return "kJ"
    if lower == "kcal":
        return "kcal"
    if normalized == "克":
        return "g"
    if normalized == "毫克":
        return "mg"
    if lower == "ug":
        return "μg"
    return normalized


def _extract_percent(text: str) -> str | None:
    """从文本里提取 NRV 百分比。"""
    match = _PERCENT_PATTERN.search(text)
    if not match:
        return None
    normalized = re.sub(r"\s+", "", match.group(0))
    if normalized.startswith("%"):
        return f"{normalized[1:]}%"
    return normalized


def _extract_value_unit(text: str) -> tuple[str, str] | None:
    """从文本里提取数值和单位。"""
    match = _VALUE_UNIT_PATTERN.search(_normalize_ocr_value_text(text))
    if not match:
        return None
    return match.group("value"), _normalize_unit(match.group("unit"))


def _find_header_row(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows[:4]):
        joined = "".join(row)
        if "项目" in joined and ("每" in joined or "NRV" in joined.upper()):
            return index
    return None


def _resolve_columns(header: list[str]) -> tuple[int, int, int | None, str | None]:
    name_index = next(
        (index for index, cell in enumerate(header) if "项目" in cell),
        0,
    )
    percent_index = next(
        (
            index
            for index, cell in enumerate(header)
            if "%" in cell or "NRV" in cell.upper() or "参考值" in cell
        ),
        None,
    )
    value_index = next(
        (
            index
            for index, cell in enumerate(header)
            if index != name_index
            and index != percent_index
            and ("每" in cell or re.search(r"\d+\s*(?:g|ml|毫升|克)", cell, re.I))
        ),
        1 if len(header) > 1 else name_index,
    )
    serving_size = header[value_index] if value_index < len(header) else None
    return name_index, value_index, percent_index, serving_size


def _nutrition_items_from_rows(
    rows: list[list[Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    normalized_rows = [
        [_normalize_cell_text(cell) for cell in row]
        for row in rows
        if isinstance(row, list)
    ]
    normalized_rows = [row for row in normalized_rows if any(row)]
    header_index = _find_header_row(normalized_rows)
    if header_index is None:
        return [], None
    if len(normalized_rows[header_index]) < 2:
        return [], None

    name_index, value_index, percent_index, serving_size = _resolve_columns(
        normalized_rows[header_index]
    )
    items: list[dict[str, Any]] = []
    for row in normalized_rows[header_index + 1 :]:
        if len(row) <= max(name_index, value_index):
            continue
        name = row[name_index]
        if not name or "项目" in name or "营养成分" in name:
            continue

        row_text = "".join(row)
        parsed_value = _extract_value_unit(row[value_index]) or _extract_value_unit(
            row_text
        )
        if parsed_value is None:
            continue

        percent_text = (
            row[percent_index]
            if percent_index is not None and percent_index < len(row)
            else row_text
        )
        items.append(
            {
                "name": name,
                "value": parsed_value[0],
                "unit": parsed_value[1],
                "daily_reference_percent": _extract_percent(percent_text),
                "level": None,
                "recommendation": None,
            }
        )

    return items, serving_size


def _parse_table_rows(table_result: dict[str, Any] | None) -> dict[str, Any] | None:
    sanitized_table_result = _sanitize_table_result(table_result)
    if not sanitized_table_result:
        return None
    rows = sanitized_table_result.get("rows")
    if not isinstance(rows, list):
        return None
    items, serving_size = _nutrition_items_from_rows(rows)
    if not items:
        return None
    return _build_result(items, serving_size, "table_recognition")


def _parse_html_tables(nutrition_raw_text: str | None) -> dict[str, Any] | None:
    if not nutrition_raw_text or "<table" not in nutrition_raw_text.lower():
        return None
    parser = _NutritionHTMLTableParser()
    parser.feed(nutrition_raw_text)
    for rows in parser.tables:
        items, serving_size = _nutrition_items_from_rows(rows)
        if items:
            return _build_result(items, serving_size, "ocr_text")
    return None


def _normalize_plain_nutrient_name(line: str) -> str | None:
    """从一行 OCR 文本里识别营养素名称，并修正常见错字。"""
    normalized = _normalize_cell_text(line)
    if not normalized:
        return None

    corrected = (
        normalized.replace("蛋百质", "蛋白质")
        .replace("蛋自质", "蛋白质")
        .replace("蛋曰质", "蛋白质")
    )
    if corrected in _PLAIN_TEXT_HEADER_TOKENS:
        return None

    compact = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "", corrected)
    for token in _PLAIN_NUTRIENT_TOKENS:
        if token in compact:
            return corrected
    return None


def _extract_serving_size_from_lines(lines: list[str]) -> str | None:
    """从 OCR 文本中找出每份或每 100g 的计量口径。"""
    for line in lines:
        if re.search(
            r"每\s*(?:份|100\s*(?:g|克|ml|毫升)|\d+\s*(?:g|克|ml|毫升))",
            line,
            re.I,
        ):
            return _normalize_cell_text(line)
    return None


def _parse_plain_nutrition_text(
    nutrition_raw_text: str | None,
) -> dict[str, Any] | None:
    """从逐行 OCR 文本里兜底解析营养成分。"""
    if not nutrition_raw_text:
        return None

    lines = [
        line.strip()
        for line in re.split(r"[\r\n]+", nutrition_raw_text)
        if line.strip()
    ]
    if len(lines) < 3:
        return None

    items: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        name = _normalize_plain_nutrient_name(lines[index])
        if not name:
            index += 1
            continue

        value_unit = _extract_value_unit(lines[index])
        value_index = index
        if value_unit is None:
            probe_index = index + 1
            while (
                probe_index < len(lines)
                and _normalize_cell_text(lines[probe_index]) in _PLAIN_TEXT_HEADER_TOKENS
            ):
                probe_index += 1
            if probe_index >= len(lines):
                break
            value_unit = _extract_value_unit(lines[probe_index])
            value_index = probe_index

        if value_unit is None:
            index += 1
            continue

        percent = _extract_percent(lines[index])
        next_index = value_index + 1
        if percent is None and next_index < len(lines):
            next_percent = _extract_percent(lines[next_index])
            if next_percent:
                percent = next_percent
                next_index += 1

        items.append(
            {
                "name": name,
                "value": value_unit[0],
                "unit": value_unit[1],
                "daily_reference_percent": percent,
                "level": None,
                "recommendation": None,
            }
        )
        index = max(index + 1, next_index)

    if not items:
        return None
    return _build_result(items, _extract_serving_size_from_lines(lines), "ocr_text")


def _parse_structured_nutrition(
    table_result: dict[str, Any] | None,
    nutrition_raw_text: str | None,
) -> dict[str, Any] | None:
    """按表格、HTML、逐行文本的顺序解析营养成分。"""
    return (
        _parse_table_rows(table_result)
        or _parse_html_tables(nutrition_raw_text)
        or _parse_plain_nutrition_text(nutrition_raw_text)
    )


def _extract_json_payload(content: str) -> dict[str, Any] | None:
    if not content:
        return None

    normalized = content.strip()
    if normalized.startswith("```"):
        fenced_match = re.search(
            r"```(?:json)?\s*(\{[\s\S]*\})\s*```",
            normalized,
            re.IGNORECASE,
        )
        if fenced_match:
            normalized = fenced_match.group(1).strip()

    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        object_match = re.search(r"\{[\s\S]*\}", normalized)
        if not object_match:
            return None
        try:
            payload = json.loads(object_match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(payload, dict):
        return None
    return payload


def _sanitize_table_result(table_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(table_result, dict):
        return None

    table_json = table_result.get("table_json")
    if isinstance(table_json, dict):
        return table_json
    return table_result


def _serialize_inputs(
    table_result: dict[str, Any] | None,
    nutrition_raw_text: str | None,
) -> dict[str, str]:
    sanitized_table_result = _sanitize_table_result(table_result)
    return {
        "table_result_json": json.dumps(
            sanitized_table_result or {}, ensure_ascii=False, indent=2
        ),
        "nutrition_raw_text": (
            nutrition_raw_text.strip()
            if nutrition_raw_text and nutrition_raw_text.strip()
            else "(无补充 OCR 文本)"
        ),
    }


def _resolve_parse_method(
    table_result: dict[str, Any] | None,
    nutrition_raw_text: str | None,
) -> str:
    if _sanitize_table_result(table_result):
        return "table_recognition"
    if nutrition_raw_text and nutrition_raw_text.strip():
        return "ocr_text"
    return "empty"


def _render_prompt(template: str, inputs: dict[str, str]) -> str:
    rendered = template
    for key, value in inputs.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _llm_parse(
    table_result: dict[str, Any] | None,
    nutrition_raw_text: str | None,
) -> dict[str, Any] | None:
    parse_method = _resolve_parse_method(table_result, nutrition_raw_text)
    if parse_method == "empty":
        return _build_result([], None, "empty")

    settings = get_settings()
    prompt = build_nutrition_table_llm_parse_prompt()
    inputs = _serialize_inputs(table_result, nutrition_raw_text)
    rendered_prompt = _render_prompt(prompt, inputs)

    try:
        response = _get_llm_client().chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            temperature=0,
            max_tokens=1200,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": rendered_prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        payload = _extract_json_payload(content)
        if payload is None:
            return None
        payload["parse_method"] = parse_method
        result = NutritionData.model_validate(payload)
        return result.model_dump()
    except Exception as exc:
        logger.warning("nutrition_llm_parse_failed", error=str(exc))
        return None


def parse(table_result, ocr_fallback_text: str | None = None) -> dict[str, Any]:
    """解析输入数据，返回统一的结构化结果。"""
    table_data = (
        table_result.model_dump()
        if hasattr(table_result, "model_dump")
        else table_result
    )
    if not isinstance(table_data, dict):
        table_data = None

    result = _llm_parse(table_data, ocr_fallback_text)
    if result:
        if not result.get("items"):
            if (
                table_data
                and ocr_fallback_text
                and result.get("parse_method") == "table_recognition"
            ):
                fallback_result = _llm_parse(None, ocr_fallback_text)
                if fallback_result and fallback_result.get("items"):
                    logger.info(
                        "nutrition_llm_parsed_from_text_after_empty_table",
                        parse_method=fallback_result["parse_method"],
                        items=len(fallback_result["items"]),
                    )
                    return fallback_result
            structured_result = _parse_structured_nutrition(
                table_data,
                ocr_fallback_text,
            )
            if structured_result and structured_result.get("items"):
                logger.info(
                    "nutrition_structured_table_parsed",
                    parse_method=structured_result["parse_method"],
                    items=len(structured_result["items"]),
                )
                return structured_result
        logger.info(
            "nutrition_llm_parsed",
            parse_method=result["parse_method"],
            items=len(result["items"]),
        )
        return result

    if table_data and ocr_fallback_text:
        result = _llm_parse(None, ocr_fallback_text)
        if result and result.get("items"):
            logger.info(
                "nutrition_llm_parsed_from_text",
                parse_method=result["parse_method"],
                items=len(result["items"]),
            )
            return result

    structured_result = _parse_structured_nutrition(table_data, ocr_fallback_text)
    if structured_result:
        logger.info(
            "nutrition_structured_table_parsed",
            parse_method=structured_result["parse_method"],
            items=len(structured_result["items"]),
        )
        return structured_result

    if not table_data and not ocr_fallback_text:
        logger.info("nutrition_parse_empty")
        return _build_result([], None, "empty")

    logger.warning("nutrition_parse_failed")
    return _build_result([], None, "failed")


__all__ = ["parse", "_llm_parse"]
