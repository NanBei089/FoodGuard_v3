from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from app.core.errors import (
    AnalysisPayloadError,
    EmbeddingServiceError,
    LLMServiceError,
    OCRServiceError,
    StorageServiceError,
)
from app.models.analysis_task import TaskStatus
from app.tasks.analysis.artifacts import _persist_analysis_artifacts
from app.tasks.analysis.ingredient_fallback import _ensure_ingredient_coverage
from app.tasks.analysis.ocr_strategy import (
    _choose_better_table_result,
    _run_ocr_full_text,
    _run_ocr_parallel,
    _run_ocr_table,
    _run_ocr_with_bbox_fallback,
    _table_result_is_incomplete,
    _table_result_quality,
)
from app.tasks.analysis.persistence import (
    _complete_task_with_report,
    _download_image,
    _update_task_status,
)
from app.tasks.celery_app import celery_app
from app.workers import llm_worker, ocr_worker, rag_worker, yolo_worker
from app.workers.extractor import ingredient_extractor, nutrition_extractor
from app.workers.ocr_worker import TableRecognitionResult

logger = structlog.get_logger(__name__)
_INTERNAL_ANALYSIS_ERROR_MESSAGE = "Internal analysis pipeline error"


def _to_plain_data(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, (dict, list, str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return {
            key: item for key, item in vars(value).items() if not key.startswith("_")
        }
    return value


def _require_dict_payload(payload_name: str, value: Any) -> dict[str, Any]:
    plain_value = _to_plain_data(value)
    if not isinstance(plain_value, dict):
        raise AnalysisPayloadError(f"{payload_name} payload must be a dict")
    return plain_value


def _extract_score(llm_output_json: dict[str, Any]) -> int:
    raw_score = llm_output_json.get("score", 0)
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))

def _run_rag(ingredient_terms: list[str], ingredients_text: str) -> dict[str, Any]:
    try:
        return rag_worker.retrieve_all(ingredient_terms, ingredients_text)
    except NotImplementedError:
        raise
    except EmbeddingServiceError:
        raise

def _run_llm(
    full_text: str,
    nutrition_json: dict[str, Any],
    rag_results_json: dict[str, Any],
    ingredient_terms: list[str],
    ingredients_text: str,
) -> dict[str, Any]:
    try:
        return llm_worker.analyze(
            full_text,
            nutrition_json,
            rag_results_json,
            recognized_ingredient_terms=ingredient_terms,
            ingredients_text=ingredients_text,
        )
    except TypeError as exc:
        if (
            "recognized_ingredient_terms" not in str(exc)
            and "ingredients_text" not in str(exc)
        ):
            raise LLMServiceError("LLM analysis failed") from exc
        return llm_worker.analyze(full_text, nutrition_json, rag_results_json)
    except NotImplementedError:
        raise
    except LLMServiceError:
        raise

@celery_app.task(
    bind=True,
    name="analysis.process_image",
    max_retries=2,
    soft_time_limit=270,
    time_limit=300,
)
def process_image_task(
    self, task_id: str, image_key: str, user_id: str
) -> dict[str, Any]:
    started_at = perf_counter()
    logger.info(
        "analysis_task_started",
        task_id=task_id,
        image_key=image_key,
        user_id=user_id,
        celery_task_id=self.request.id,
    )
    _update_task_status(task_id, TaskStatus.PROCESSING)
    timings: dict[str, int] = {}

    try:
        step_started = perf_counter()
        image_bytes = _download_image(image_key)
        timings["download_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        bbox = yolo_worker.detect(image_bytes)
        cropped_image = (
            yolo_worker.crop_image(image_bytes, bbox) if bbox else image_bytes
        )
        masked_full_image = (
            yolo_worker.mask_image(image_bytes, bbox) if bbox else image_bytes
        )
        timings["yolo_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        if bbox:
            full_text_result, table_result = _run_ocr_with_bbox_fallback(
                task_id=task_id,
                image_bytes=image_bytes,
                masked_full_image=masked_full_image,
                cropped_image=cropped_image,
            )
        else:
            full_text_result = _run_ocr_full_text(image_bytes)
            try:
                table_result = _run_ocr_table(image_bytes)
            except OCRServiceError as exc:
                logger.warning(
                    "nutrition_table_full_image_scan_failed",
                    task_id=task_id,
                    error_message=str(exc),
                )
                table_result = None
        full_text = full_text_result.raw_text
        timings["ocr_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        nutrition_output = nutrition_extractor.parse(
            table_result.model_dump() if table_result else None,
            (
                table_result.ocr_fallback_text
                if table_result and table_result.ocr_fallback_text
                else full_text or None
            ),
        )
        nutrition_json = _require_dict_payload("nutrition", nutrition_output)
        timings["nutrition_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        ingredient_terms, ingredients_text = ingredient_extractor.extract(full_text)
        timings["ingredients_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        rag_output = _run_rag(ingredient_terms, ingredients_text)
        rag_results_json = _require_dict_payload("rag", rag_output)
        timings["rag_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        llm_output = _run_llm(
            full_text,
            nutrition_json,
            rag_results_json,
            ingredient_terms,
            ingredients_text,
        )
        llm_output_json = _require_dict_payload("llm", llm_output)
        llm_output_json = _ensure_ingredient_coverage(
            llm_output_json,
            ingredient_terms,
            rag_results_json,
        )
        score = _extract_score(llm_output_json)
        timings["llm_ms"] = int((perf_counter() - step_started) * 1000)

        _complete_task_with_report(
            task_id=task_id,
            user_id=user_id,
            ingredients_text=ingredients_text,
            nutrition_json=nutrition_json,
            rag_results_json=rag_results_json,
            llm_output_json=llm_output_json,
            score=score,
            artifact_urls=_persist_analysis_artifacts(
                task_id=task_id,
                user_id=user_id,
                source_image_key=image_key,
                bbox=bbox,
                masked_full_image=masked_full_image if bbox else None,
                cropped_image=cropped_image if bbox else None,
                full_text_result=full_text_result,
                table_result=table_result,
                nutrition_json=nutrition_json,
                rag_results_json=rag_results_json,
                llm_output_json=llm_output_json,
            ),
        )
        total_elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "analysis_task_completed",
            task_id=task_id,
            total_elapsed_ms=total_elapsed_ms,
            timings=timings,
        )
        return {
            "task_id": task_id,
            "status": TaskStatus.COMPLETED.value,
            "total_elapsed_ms": total_elapsed_ms,
        }
    except SoftTimeLimitExceeded:
        error_message = "Analysis timeout"
        _update_task_status(task_id, TaskStatus.FAILED, error_message)
        logger.warning("analysis_task_timeout", task_id=task_id, timings=timings)
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except (
        OCRServiceError,
        LLMServiceError,
        StorageServiceError,
        EmbeddingServiceError,
    ) as exc:
        if self.request.retries < self.max_retries:
            logger.warning(
                "analysis_task_retrying",
                task_id=task_id,
                retries=self.request.retries,
                exception_type=exc.__class__.__name__,
                exception_message=str(exc),
            )
            raise self.retry(exc=exc, countdown=10)
        _update_task_status(task_id, TaskStatus.FAILED, str(exc))
        logger.warning(
            "analysis_task_failed_after_retries",
            task_id=task_id,
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except NotImplementedError as exc:
        _update_task_status(task_id, TaskStatus.FAILED, str(exc))
        logger.warning(
            "analysis_task_not_implemented", task_id=task_id, error_message=str(exc)
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except Exception as exc:
        _update_task_status(task_id, TaskStatus.FAILED, _INTERNAL_ANALYSIS_ERROR_MESSAGE)
        logger.exception(
            "analysis_task_unexpected_failure",
            task_id=task_id,
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}


__all__ = ["process_image_task"]
