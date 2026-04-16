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

_OCR_RUNTIME_EXCEPTIONS = (
    requests.RequestException,
    RuntimeError,
    TimeoutError,
    OSError,
    ValueError,
)


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


def _get_remote_ocr_engine() -> Any:
    settings = get_settings()
    config = _build_ocr_config(settings.PADDLEOCR_MODEL)
    cache_key = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True)
    return get_cached_engine(cache_key, lambda: PaddleOCR(config))


def _get_remote_nutrition_ocr_engine() -> Any:
    settings = get_settings()
    config = _build_ocr_config(settings.PADDLEOCR_NUTRITION_MODEL)
    cache_key = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True)
    return get_cached_engine(cache_key, lambda: PaddleOCR(config))


def warmup() -> None:
    _get_remote_ocr_engine()
    _get_remote_nutrition_ocr_engine()


def _prepare_remote_ocr_input(image_bytes: bytes) -> bytes:
    return _prepare_image_for_remote_ocr(image_bytes)


def _extract_layout_results(raw_result: Any) -> list[Any]:
    if not isinstance(raw_result, dict):
        return []
    results = raw_result.get("results", [])
    if not results or not isinstance(results[0], dict):
        return []
    layout_results = results[0].get("layoutParsingResults", [])
    return layout_results if isinstance(layout_results, list) else []


def _build_full_text_result(raw_result: Any) -> OCRTextResult:
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


def _build_table_json_from_raw_result(
    raw_result: Any,
    *,
    fallback_text: str,
) -> tuple[dict[str, Any] | None, bool]:
    layout_results = _extract_layout_results(raw_result)
    table_json = None
    has_table = False

    if layout_results:
        table_data = _extract_table_from_layout(layout_results)
        if table_data and "html" in table_data:
            rows = _html_table_to_structured(table_data["html"])
            table_json = _convert_table_to_nutrition_json(rows)
            has_table = bool(table_json and table_json.get("rows"))
            logger.info("table_html_parsed", rows=len(rows), has_table=has_table)

    if not has_table and fallback_text and "<table" in fallback_text.lower():
        table_data = _extract_table_from_html_fallback(fallback_text)
        if table_data and "rows" in table_data:
            table_json = _convert_table_to_nutrition_json(table_data["rows"])
            has_table = bool(table_json and table_json.get("rows"))
            logger.info(
                "table_from_fallback_parsed",
                rows=len(table_data["rows"]),
                has_table=has_table,
            )

    return table_json, has_table


def _build_nutrition_table_result(raw_result: Any) -> TableRecognitionResult:
    lines = _extract_text_lines_with_nested_fallback(raw_result)
    raw_text = "\n".join(line["text"] for line in lines if line["text"])

    table_json, has_table = _build_table_json_from_raw_result(
        raw_result,
        fallback_text=raw_text,
    )
    logger.info(
        "table_recognition_debug",
        has_table=has_table,
        raw_text_len=len(raw_text) if raw_text else 0,
    )

    result = TableRecognitionResult(
        table_json=table_json,
        table_html_url=None,
        table_xlsx_url=None,
        ocr_fallback_text=raw_text,
        source="ocr_runtime",
    )
    logger.info("table_recognition_completed", has_table=has_table)
    return result


def _build_parallel_result(
    full_text_raw_result: Any,
    nutrition_raw_result: Any,
) -> OCRParallelResult:
    full_text_result = _build_full_text_result(full_text_raw_result)
    nutrition_result = _build_nutrition_table_result(nutrition_raw_result)
    if not nutrition_result.ocr_fallback_text:
        nutrition_result.ocr_fallback_text = full_text_result.raw_text
    return OCRParallelResult(
        full_text=full_text_result,
        nutrition_table=nutrition_result,
    )


def _run_single_ocr(image_bytes: bytes, engine: Any) -> dict[str, Any]:
    return engine.ocr(image_bytes)


def _run_parallel_jobs(
    full_text_image_bytes: bytes,
    nutrition_image_bytes: bytes,
    full_text_engine: Any,
    nutrition_engine: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(
            _run_single_ocr, full_text_image_bytes, full_text_engine
        )
        future2 = executor.submit(
            _run_single_ocr, nutrition_image_bytes, nutrition_engine
        )
        return future1.result(), future2.result()


def _recognize_full_text_remote(image_bytes: bytes) -> OCRTextResult:
    engine = _get_remote_ocr_engine()
    prepared_image_bytes = _prepare_remote_ocr_input(image_bytes)
    return _build_full_text_result(engine.ocr(prepared_image_bytes))


def _recognize_nutrition_table_remote(image_bytes: bytes) -> TableRecognitionResult:
    engine = _get_remote_nutrition_ocr_engine()
    prepared_image_bytes = _prepare_remote_ocr_input(image_bytes)
    return _build_nutrition_table_result(engine.ocr(prepared_image_bytes))


def _recognize_parallel_remote(
    full_text_image_bytes: bytes,
    nutrition_image_bytes: bytes,
) -> OCRParallelResult:
    full_text_engine = _get_remote_ocr_engine()
    nutrition_engine = _get_remote_nutrition_ocr_engine()
    prepared_full_text_image_bytes = _prepare_remote_ocr_input(full_text_image_bytes)
    prepared_nutrition_image_bytes = _prepare_remote_ocr_input(nutrition_image_bytes)
    full_text_raw_result, nutrition_raw_result = _run_parallel_jobs(
        prepared_full_text_image_bytes,
        prepared_nutrition_image_bytes,
        full_text_engine,
        nutrition_engine,
    )
    return _build_parallel_result(full_text_raw_result, nutrition_raw_result)


def _log_and_raise_ocr_runtime_failure(
    *,
    operation: str,
    mode: str,
    exc: Exception,
    context: dict[str, Any] | None = None,
) -> None:
    logger.exception(
        "ocr_runtime_failed",
        operation=operation,
        mode=mode,
        error_type=type(exc).__name__,
        error=str(exc),
        **(context or {}),
    )
    raise OCRServiceError("OCR runtime failed") from exc


def recognize_full_text(image_bytes: bytes) -> OCRTextResult:
    try:
        return _recognize_full_text_remote(image_bytes)
    except _OCR_RUNTIME_EXCEPTIONS as exc:
        _log_and_raise_ocr_runtime_failure(
            operation="full_text",
            mode="remote",
            exc=exc,
            context={"image_bytes": len(image_bytes)},
        )


def recognize_nutrition_table(image_bytes: bytes) -> TableRecognitionResult:
    try:
        return _recognize_nutrition_table_remote(image_bytes)
    except _OCR_RUNTIME_EXCEPTIONS as exc:
        _log_and_raise_ocr_runtime_failure(
            operation="nutrition_table",
            mode="remote",
            exc=exc,
            context={"image_bytes": len(image_bytes)},
        )


def recognize_parallel(
    full_text_image_bytes: bytes,
    nutrition_image_bytes: bytes | None = None,
) -> OCRParallelResult:
    if nutrition_image_bytes is None:
        nutrition_image_bytes = full_text_image_bytes

    try:
        return _recognize_parallel_remote(full_text_image_bytes, nutrition_image_bytes)
    except _OCR_RUNTIME_EXCEPTIONS as exc:
        _log_and_raise_ocr_runtime_failure(
            operation="parallel",
            mode="remote",
            exc=exc,
            context={
                "full_text_image_bytes": len(full_text_image_bytes),
                "nutrition_image_bytes": len(nutrition_image_bytes),
                "shared_input": full_text_image_bytes is nutrition_image_bytes,
            },
        )


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
    "_get_remote_ocr_engine",
    "_get_remote_nutrition_ocr_engine",
    "_run_single_ocr",
    "warmup",
    "recognize_full_text",
    "recognize_nutrition_table",
    "recognize_parallel",
]
