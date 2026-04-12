from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import structlog
from PIL import Image

logger = structlog.get_logger(__name__)


def _ensure_file(path: str | Path) -> Path:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {file_path}")
    if not file_path.is_file():
        raise FileNotFoundError(f"图片路径不是有效文件: {file_path}")
    return file_path

def _prepare_image_for_remote_ocr(
    image_bytes: bytes,
    *,
    max_side: int = 2200,
    jpeg_quality: int = 86,
) -> bytes:
    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
    except (OSError, ValueError):
        return image_bytes

    original_size = image.size
    processed = image.copy()
    processed.thumbnail((max_side, max_side))

    output = BytesIO()
    try:
        processed.save(output, format="JPEG", quality=jpeg_quality, optimize=True)
    except (OSError, ValueError):
        return image_bytes

    optimized = output.getvalue()
    if not optimized:
        return image_bytes

    logger.info(
        "ocr_image_prepared",
        original_bytes=len(image_bytes),
        prepared_bytes=len(optimized),
        original_size=original_size,
        prepared_size=processed.size,
    )
    return optimized if len(optimized) < len(image_bytes) else image_bytes

def _coerce_number(value: Any) -> int | float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number.is_integer():
        return int(number)
    return round(number, 4)

def _coerce_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def _repair_text(text: str) -> str:
    for source_encoding in ("gbk", "gb18030"):
        try:
            repaired = text.encode(source_encoding).decode("utf-8")
        except UnicodeError:
            continue
        if repaired:
            return repaired
    return text

def _normalize_point(point: Any) -> list[int | float] | None:
    if isinstance(point, dict):
        if "x" in point and "y" in point:
            return [_coerce_number(point["x"]), _coerce_number(point["y"])]
        return None
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return [_coerce_number(point[0]), _coerce_number(point[1])]
    return None

def _normalize_bbox(raw_bbox: Any) -> list[list[int | float]]:
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 8:
        raw_bbox = [raw_bbox[0:2], raw_bbox[2:4], raw_bbox[4:6], raw_bbox[6:8]]

    if isinstance(raw_bbox, (list, tuple)):
        points: list[list[int | float]] = []
        for point in raw_bbox:
            normalized = _normalize_point(point)
            if normalized is not None:
                points.append(normalized)
        if len(points) >= 4:
            return points[:4]
        return points
    return []

def _is_local_line(item: Any) -> bool:
    return (
        isinstance(item, (list, tuple))
        and len(item) == 2
        and isinstance(item[1], (list, tuple))
        and len(item[1]) >= 2
    )

def _build_line(text: Any, score: Any, bbox: Any) -> dict[str, Any]:
    normalized_text = "" if text is None else _repair_text(str(text))
    return {
        "text": normalized_text,
        "score": _coerce_score(score),
        "bbox": _normalize_bbox(bbox),
    }

def _extract_from_layout_results(layout_results: list[Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for item in layout_results:
        if not isinstance(item, dict):
            continue
        markdown = item.get("markdown")
        text_block = ""
        if isinstance(markdown, dict):
            text_block = str(markdown.get("text") or "")
        elif isinstance(item.get("text"), str):
            text_block = item["text"]
        bbox = (
            item.get("bbox")
            or item.get("box")
            or item.get("region")
            or item.get("poly")
            or []
        )
        for text_line in text_block.splitlines():
            stripped = text_line.strip()
            if stripped:
                lines.append(_build_line(text=stripped, score=1.0, bbox=bbox))
    return lines

def extract_text_lines(ocr_result: Any) -> list[dict[str, Any]]:
    if ocr_result is None:
        return []

    if isinstance(ocr_result, dict):
        if "results" in ocr_result:
            return extract_text_lines(ocr_result["results"])

        if "result" in ocr_result:
            return extract_text_lines(ocr_result["result"])

        if "ocrResults" in ocr_result and isinstance(ocr_result["ocrResults"], list):
            lines: list[dict[str, Any]] = []
            for item in ocr_result["ocrResults"]:
                if isinstance(item, dict) and "prunedResult" in item:
                    lines.extend(extract_text_lines(item["prunedResult"]))
                else:
                    lines.extend(extract_text_lines(item))
            return lines

        if "prunedResult" in ocr_result:
            return extract_text_lines(ocr_result["prunedResult"])

        if "rec_texts" in ocr_result and isinstance(ocr_result["rec_texts"], list):
            texts = ocr_result.get("rec_texts") or []
            scores = ocr_result.get("rec_scores") or []
            boxes = (
                ocr_result.get("dt_polys")
                or ocr_result.get("rec_polys")
                or ocr_result.get("textline_polys")
                or []
            )
            total = max(len(texts), len(scores), len(boxes))
            lines = []
            for index in range(total):
                text = texts[index] if index < len(texts) else ""
                score = scores[index] if index < len(scores) else 0.0
                bbox = boxes[index] if index < len(boxes) else []
                line = _build_line(text=text, score=score, bbox=bbox)
                if line["text"] or line["bbox"]:
                    lines.append(line)
            return lines

        if "layoutParsingResults" in ocr_result and isinstance(
            ocr_result["layoutParsingResults"], list
        ):
            return _extract_from_layout_results(ocr_result["layoutParsingResults"])

        if "lines" in ocr_result and isinstance(ocr_result["lines"], list):
            return [
                _build_line(
                    text=line.get("text"),
                    score=line.get("score"),
                    bbox=line.get("bbox"),
                )
                for line in ocr_result["lines"]
                if isinstance(line, dict)
            ]

    if isinstance(ocr_result, list):
        if not ocr_result:
            return []

        if all(_is_local_line(item) for item in ocr_result):
            return [
                _build_line(text=item[1][0], score=item[1][1], bbox=item[0])
                for item in ocr_result
            ]

        lines: list[dict[str, Any]] = []
        for item in ocr_result:
            lines.extend(extract_text_lines(item))
        return lines

    return []

def _extract_text_lines_with_nested_fallback(
    ocr_result: Any,
) -> list[dict[str, Any]]:
    lines = extract_text_lines(ocr_result)
    nested_lines: list[dict[str, Any]] = []

    if isinstance(ocr_result, dict):
        results = ocr_result.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("lines"), list):
                    nested_lines.extend(extract_text_lines({"lines": item["lines"]}))

    if not nested_lines:
        return lines

    if not lines:
        return nested_lines

    seen_keys = {
        (line.get("text"), json.dumps(line.get("bbox"), ensure_ascii=False))
        for line in lines
    }
    for line in nested_lines:
        key = (line.get("text"), json.dumps(line.get("bbox"), ensure_ascii=False))
        if key in seen_keys:
            continue
        lines.append(line)
    return lines

def _extract_table_from_layout(layout_results: list[Any]) -> dict[str, Any] | None:
    for layout in layout_results:
        if not isinstance(layout, dict):
            continue

        pruned = layout.get("prunedResult", {})
        parsing_list = pruned.get("parsing_res_list", [])

        for block in parsing_list:
            if not isinstance(block, dict):
                continue
            label = block.get("block_label", "").lower()
            if label != "table":
                continue

            content = block.get("block_content", "")
            if isinstance(content, str) and "<table" in content.lower():
                return {"html": content, "source": "layout"}

            if isinstance(content, dict):
                table_html = content.get("html") or content.get("table")
                if table_html:
                    return {"html": table_html, "source": "layout"}
    return None

def _extract_table_from_html_fallback(html_text: str) -> dict[str, Any] | None:
    if "<table" not in html_text.lower() or "</table>" not in html_text.lower():
        return None

    rows = _html_table_to_structured(html_text)
    if rows:
        return {"html": html_text, "source": "html_fallback", "rows": rows}
    return None

def _html_table_to_structured(html_content: str) -> list[list[str]]:
    import re

    rows: list[list[str]] = []

    cell_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
    row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)

    for row_match in row_pattern.finditer(html_content):
        row_text = row_match.group(1)
        cells: list[str] = []
        for td_match in cell_pattern.finditer(row_text):
            cell_html = td_match.group(1)
            cell_text = re.sub(r"<[^>]+>", "", cell_html).strip()
            cell_text = cell_text.replace("\n", " ").replace("\r", " ")
            cell_text = " ".join(cell_text.split())
            if cell_text:
                cells.append(cell_text)
        if cells:
            rows.append(cells)

    if not rows:
        for td_match in cell_pattern.finditer(html_content):
            cell_html = td_match.group(1)
            cell_text = re.sub(r"<[^>]+>", "", cell_html).strip()
            cell_text = cell_text.replace("\n", " ").replace("\r", " ")
            cell_text = " ".join(cell_text.split())
            if cell_text:
                rows.append([cell_text])

    return rows

def _convert_table_to_nutrition_json(rows: list[list[str]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return {"rows": rows}
