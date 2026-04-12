from __future__ import annotations

import concurrent.futures
import json
from dataclasses import asdict
from typing import Any

import structlog

from app.core.config import get_settings
from app.core.errors import OCRServiceError
from app.workers.ocr import client as ocr_client
from app.workers.ocr.cache import _ENGINE_CACHE, get_cached_engine
from app.workers.ocr.parsing import (
    _convert_table_to_nutrition_json,
    _extract_table_from_html_fallback,
    _extract_table_from_layout,
    _extract_text_lines_with_nested_fallback,
    _html_table_to_structured,
    _prepare_image_for_remote_ocr,
)
from app.workers.ocr.types import (
    OCRConfig,
    OCRParallelResult,
    OCRTextResult,
    TableRecognitionResult,
)

logger = structlog.get_logger(__name__)
requests = ocr_client.requests
time = ocr_client.time
PaddleOCRAPIClient = ocr_client.PaddleOCRAPIClient
PaddleOCR = PaddleOCRAPIClient


def _build_ocr_config(model: str) -> OCRConfig:
    settings = get_settings()
    return OCRConfig(
        job_url=settings.PADDLEOCR_JOB_URL,
        token=(
            settings.PADDLEOCR_TOKEN.get_secret_value()
            if hasattr(settings.PADDLEOCR_TOKEN, "get_secret_value")
            else settings.PADDLEOCR_TOKEN
        ),
        model=model,
        lang="ch",
        use_angle_cls=True,
        det=True,
        rec=True,
        det_db_box_thresh=settings.PADDLEOCR_DET_DB_BOX_THRESH,
        det_db_unclip_ratio=settings.PADDLEOCR_DET_DB_UNCLIP_RATIO,
        rec_char_type="ch",
        device="cpu",
        use_doc_orientation_classify=settings.PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY,
        use_doc_unwarping=settings.PADDLEOCR_USE_DOC_UNWARPING,
        use_textline_orientation=settings.PADDLEOCR_USE_TEXTLINE_ORIENTATION,
        use_table_recognition=settings.PADDLEOCR_USE_TABLE_RECOGNITION,
        use_e2e_wired_table_rec_model=settings.PADDLEOCR_USE_E2E_WIRED_TABLE_REC_MODEL,
        use_e2e_wireless_table_rec_model=settings.PADDLEOCR_USE_E2E_WIRELESS_TABLE_REC_MODEL,
        use_formula_recognition=False,
        use_chart_recognition=False,
        text_det_limit_side_len=settings.PADDLEOCR_TEXT_DET_LIMIT_SIDE_LEN,
        text_det_limit_type=settings.PADDLEOCR_TEXT_DET_LIMIT_TYPE,
        text_det_thresh=settings.PADDLEOCR_TEXT_DET_THESH,
        poll_interval_s=settings.PADDLEOCR_POLL_INTERVAL_S,
        poll_timeout_s=settings.PADDLEOCR_POLL_TIMEOUT_S,
        request_timeout_s=settings.PADDLEOCR_REQUEST_TIMEOUT_S,
    )


def _get_ocr_engine() -> PaddleOCR:
    settings = get_settings()
    config = _build_ocr_config(settings.PADDLEOCR_MODEL)
    cache_key = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True)
    return get_cached_engine(cache_key, lambda: PaddleOCR(config))


def _get_nutrition_ocr_engine() -> PaddleOCR:
    settings = get_settings()
    config = _build_ocr_config(settings.PADDLEOCR_NUTRITION_MODEL)
    cache_key = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True)
    return get_cached_engine(cache_key, lambda: PaddleOCR(config))


def warmup() -> None:
    _get_ocr_engine()
    _get_nutrition_ocr_engine()


def recognize_full_text(image_bytes: bytes) -> OCRTextResult:
    engine = _get_ocr_engine()
    try:
        prepared_bytes = _prepare_image_for_remote_ocr(image_bytes)
        raw_result = engine.ocr(prepared_bytes)
        lines = _extract_text_lines_with_nested_fallback(raw_result)
        raw_text = "\n".join(line["text"] for line in lines if line["text"])
        result = OCRTextResult(
            raw_text=raw_text,
            lines=lines,
            blocks=[],
            source="ocr_runtime",
        )
        logger.info("ocr_full_completed", lines=len(lines))
        return result
    except (requests.RequestException, RuntimeError, TimeoutError, OSError, ValueError) as exc:
        logger.exception("ocr_runtime_failed", error=str(exc))
        raise OCRServiceError("OCR runtime failed") from exc


def recognize_nutrition_table(image_bytes: bytes) -> TableRecognitionResult:
    engine = _get_nutrition_ocr_engine()
    try:
        prepared_bytes = _prepare_image_for_remote_ocr(image_bytes)
        raw_result = engine.ocr(prepared_bytes)
        lines = _extract_text_lines_with_nested_fallback(raw_result)
        raw_text = "\n".join(line["text"] for line in lines if line["text"])

        table_json = None
        table_html_url = None
        table_xlsx_url = None
        has_table = False

        layout_results = None
        if isinstance(raw_result, dict):
            results = raw_result.get("results", [])
            if results and isinstance(results[0], dict):
                layout_results = results[0].get("layoutParsingResults", [])

        if layout_results:
            table_data = _extract_table_from_layout(layout_results)
            if table_data and "html" in table_data:
                rows = _html_table_to_structured(table_data["html"])
                table_json = _convert_table_to_nutrition_json(rows)
                has_table = bool(table_json and table_json.get("rows"))
                logger.info("table_html_parsed", rows=len(rows), has_table=has_table)

        if not has_table and raw_text and "<table" in raw_text.lower():
            table_data = _extract_table_from_html_fallback(raw_text)
            if table_data and "rows" in table_data:
                table_json = _convert_table_to_nutrition_json(table_data["rows"])
                has_table = bool(table_json and table_json.get("rows"))
                logger.info(
                    "table_from_fallback_parsed",
                    rows=len(table_data["rows"]),
                    has_table=has_table,
                )

        logger.info(
            "table_recognition_debug",
            has_table=has_table,
            raw_text_len=len(raw_text) if raw_text else 0,
        )

        result = TableRecognitionResult(
            table_json=table_json,
            table_html_url=table_html_url,
            table_xlsx_url=table_xlsx_url,
            ocr_fallback_text=raw_text,
            source="ocr_runtime",
        )
        logger.info("table_recognition_completed", has_table=has_table)
        return result
    except (requests.RequestException, RuntimeError, TimeoutError, OSError, ValueError) as exc:
        logger.exception("ocr_runtime_failed", error=str(exc))
        raise OCRServiceError("OCR runtime failed") from exc


def _run_single_ocr(image_bytes: bytes, config: OCRConfig) -> dict[str, Any]:
    client = PaddleOCRAPIClient(config)
    job_id = client._submit_job(image_bytes)
    job_data = client._poll_job(job_id)
    result_url = job_data.get("resultUrl") or {}
    json_url = result_url.get("jsonUrl") or result_url.get("jsonlUrl")
    if not json_url:
        raise RuntimeError(f"OCR ???????????jsonUrl: {job_data}")
    return client._download_jsonl_results(str(json_url))


def _run_parallel_jobs(
    full_text_image_bytes: bytes,
    nutrition_image_bytes: bytes,
    full_text_config: OCRConfig,
    nutrition_config: OCRConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(_run_single_ocr, full_text_image_bytes, full_text_config)
        future2 = executor.submit(_run_single_ocr, nutrition_image_bytes, nutrition_config)
        return future1.result(), future2.result()


def recognize_parallel(
    full_text_image_bytes: bytes,
    nutrition_image_bytes: bytes | None = None,
) -> OCRParallelResult:
    full_text_config = _get_ocr_engine().config
    nutrition_config = _get_nutrition_ocr_engine().config
    if nutrition_image_bytes is None:
        nutrition_image_bytes = full_text_image_bytes
    prepared_full_text_image_bytes = _prepare_image_for_remote_ocr(full_text_image_bytes)
    prepared_nutrition_image_bytes = _prepare_image_for_remote_ocr(nutrition_image_bytes)

    try:
        job1_result, job2_result = _run_parallel_jobs(
            prepared_full_text_image_bytes,
            prepared_nutrition_image_bytes,
            full_text_config,
            nutrition_config,
        )

        full_text_lines = _extract_text_lines_with_nested_fallback(job1_result)
        full_text_raw = "\n".join(line["text"] for line in full_text_lines if line["text"])
        nutrition_lines = _extract_text_lines_with_nested_fallback(job2_result)
        nutrition_raw = "\n".join(line["text"] for line in nutrition_lines if line["text"])

        nutrition_result = TableRecognitionResult(
            table_json=None,
            table_html_url=None,
            table_xlsx_url=None,
            ocr_fallback_text=nutrition_raw or full_text_raw,
            source="ocr_runtime",
        )

        layout_results = None
        if isinstance(job2_result, dict):
            results = job2_result.get("results", [])
            if results and isinstance(results[0], dict):
                layout_results = results[0].get("layoutParsingResults", [])

        table_json = None
        has_table = False
        if layout_results:
            table_data = _extract_table_from_layout(layout_results)
            if table_data and "html" in table_data:
                rows = _html_table_to_structured(table_data["html"])
                table_json = _convert_table_to_nutrition_json(rows)
                has_table = bool(table_json and table_json.get("rows"))

        if not has_table and full_text_raw and "<table" in full_text_raw.lower():
            table_data = _extract_table_from_html_fallback(full_text_raw)
            if table_data and "rows" in table_data:
                table_json = _convert_table_to_nutrition_json(table_data["rows"])
                has_table = bool(table_json and table_json.get("rows"))

        nutrition_result.table_json = table_json
        logger.info("table_recognition_completed", has_table=has_table)

        full_text_result = OCRTextResult(
            raw_text=full_text_raw,
            lines=full_text_lines,
            blocks=[],
            source="ocr_runtime",
        )
        logger.info("ocr_full_completed", lines=len(full_text_lines))
        return OCRParallelResult(full_text=full_text_result, nutrition_table=nutrition_result)
    except (requests.RequestException, RuntimeError, TimeoutError, OSError, ValueError) as exc:
        logger.exception("ocr_runtime_failed", error=str(exc))
        raise OCRServiceError("OCR runtime failed") from exc


__all__ = [
    "OCRConfig",
    "OCRTextResult",
    "TableRecognitionResult",
    "OCRParallelResult",
    "PaddleOCR",
    "PaddleOCRAPIClient",
    "requests",
    "time",
    "_ENGINE_CACHE",
    "_get_ocr_engine",
    "_get_nutrition_ocr_engine",
    "_run_single_ocr",
    "warmup",
    "recognize_full_text",
    "recognize_nutrition_table",
    "recognize_parallel",
]
