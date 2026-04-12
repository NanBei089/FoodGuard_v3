from __future__ import annotations

import concurrent.futures
import json
from dataclasses import asdict
from typing import Any

import structlog

from app.core.config import get_settings
from app.core.errors import OCRServiceError
from app.workers.ocr import client as ocr_client
from app.workers.ocr import local_engine as ocr_local
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


def _is_local_ocr_mode() -> bool:
    return get_settings().PADDLEOCR_MODE == "local"


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


def _get_ocr_engine() -> Any:
    if _is_local_ocr_mode():
        settings = get_settings()
        device = ocr_local.resolve_device(settings.PADDLEOCR_DEVICE)
        cache_key = (
            f"local:text:{device}:{settings.PADDLEOCR_LOCAL_PRECISION}:"
            f"{settings.PADDLEOCR_LOCAL_MODEL_DIR or ''}"
        )
        return get_cached_engine(
            cache_key,
            lambda: ocr_local.LocalPaddleOCRClient(
                device=device,
                precision=settings.PADDLEOCR_LOCAL_PRECISION,
                cpu_threads=settings.PADDLEOCR_LOCAL_CPU_THREADS,
                enable_mkldnn=settings.PADDLEOCR_LOCAL_ENABLE_MKLDNN,
                use_doc_orientation_classify=settings.PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY,
                use_doc_unwarping=settings.PADDLEOCR_USE_DOC_UNWARPING,
                use_textline_orientation=settings.PADDLEOCR_USE_TEXTLINE_ORIENTATION,
                text_det_limit_side_len=settings.PADDLEOCR_TEXT_DET_LIMIT_SIDE_LEN,
                text_det_limit_type=settings.PADDLEOCR_TEXT_DET_LIMIT_TYPE,
                text_det_thresh=settings.PADDLEOCR_TEXT_DET_THESH,
                text_det_box_thresh=settings.PADDLEOCR_DET_DB_BOX_THRESH,
                text_det_unclip_ratio=settings.PADDLEOCR_DET_DB_UNCLIP_RATIO,
                local_model_dir=settings.PADDLEOCR_LOCAL_MODEL_DIR,
            ),
        )

    settings = get_settings()
    config = _build_ocr_config(settings.PADDLEOCR_MODEL)
    cache_key = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True)
    return get_cached_engine(cache_key, lambda: PaddleOCR(config))


def _get_nutrition_ocr_engine() -> Any:
    if _is_local_ocr_mode():
        settings = get_settings()
        device = ocr_local.resolve_device(settings.PADDLEOCR_DEVICE)
        cache_key = (
            f"local:table:{device}:{settings.PADDLEOCR_LOCAL_PRECISION}:"
            f"{settings.PADDLEOCR_LOCAL_MODEL_DIR or ''}"
        )
        return get_cached_engine(
            cache_key,
            lambda: ocr_local.LocalPPStructureClient(
                device=device,
                precision=settings.PADDLEOCR_LOCAL_PRECISION,
                cpu_threads=settings.PADDLEOCR_LOCAL_CPU_THREADS,
                enable_mkldnn=settings.PADDLEOCR_LOCAL_ENABLE_MKLDNN,
                local_model_dir=settings.PADDLEOCR_LOCAL_MODEL_DIR,
            ),
        )

    settings = get_settings()
    config = _build_ocr_config(settings.PADDLEOCR_NUTRITION_MODEL)
    cache_key = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True)
    return get_cached_engine(cache_key, lambda: PaddleOCR(config))


def warmup() -> None:
    _get_ocr_engine()
    _get_nutrition_ocr_engine()


def _prepare_ocr_input(image_bytes: bytes) -> bytes:
    return image_bytes if _is_local_ocr_mode() else _prepare_image_for_remote_ocr(image_bytes)


def _extract_layout_results(raw_result: Any) -> list[Any]:
    if not isinstance(raw_result, dict):
        return []
    results = raw_result.get("results", [])
    if not results or not isinstance(results[0], dict):
        return []
    layout_results = results[0].get("layoutParsingResults", [])
    return layout_results if isinstance(layout_results, list) else []


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


def recognize_full_text(image_bytes: bytes) -> OCRTextResult:
    engine = _get_ocr_engine()
    try:
        raw_result = engine.ocr(_prepare_ocr_input(image_bytes))
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
        raw_result = engine.ocr(_prepare_ocr_input(image_bytes))
        lines = _extract_text_lines_with_nested_fallback(raw_result)
        raw_text = "\n".join(line["text"] for line in lines if line["text"])

        table_json, has_table = _build_table_json_from_raw_result(
            raw_result,
            fallback_text=raw_text,
        )
        table_html_url = None
        table_xlsx_url = None

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
    if nutrition_image_bytes is None:
        nutrition_image_bytes = full_text_image_bytes

    try:
        if _is_local_ocr_mode():
            full_engine = _get_ocr_engine()
            nutrition_engine = _get_nutrition_ocr_engine()
            if getattr(full_engine, "device", None) == "gpu":
                logger.debug("local_gpu_parallel_may_serialize")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future1 = executor.submit(full_engine.ocr, full_text_image_bytes)
                future2 = executor.submit(nutrition_engine.ocr, nutrition_image_bytes)
                job1_result, job2_result = future1.result(), future2.result()
        else:
            full_text_config = _get_ocr_engine().config
            nutrition_config = _get_nutrition_ocr_engine().config
            prepared_full_text_image_bytes = _prepare_ocr_input(full_text_image_bytes)
            prepared_nutrition_image_bytes = _prepare_ocr_input(nutrition_image_bytes)
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

        table_json, has_table = _build_table_json_from_raw_result(
            job2_result,
            fallback_text=nutrition_raw or full_text_raw,
        )
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
