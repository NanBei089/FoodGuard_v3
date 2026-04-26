"""食品标签分析的主流程：下载图片、检测区域、OCR、解析、检索、生成报告。"""


from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol, TypeVar, overload

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from pydantic import ValidationError

from app.core.errors import (
    AnalysisPayloadError,
    EmbeddingServiceError,
    LLMServiceError,
    OCRServiceError,
    StorageServiceError,
)
from app.core.metrics import (
    record_analysis_task_metrics,
    record_external_dependency_error,
)
from app.models.analysis_task import TaskStatus
from app.schemas.analysis_data import IngredientItem, NutritionData, RAGResults
from app.services.score_calculator import calculate_health_score
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
from app.workers.ocr_worker import OCRTextResult, TableRecognitionResult

logger = structlog.get_logger(__name__)
_INTERNAL_ANALYSIS_ERROR_MESSAGE = "Internal analysis pipeline error"
T = TypeVar("T")


@dataclass
class AnalysisContext:
    """保存一次分析任务执行过程中共用的数据。"""
    task_id: str
    image_key: str
    user_id: str
    timings: dict[str, int] = field(default_factory=dict)
    image_bytes: bytes = b""
    bbox: dict[str, Any] | None = None
    cropped_image: bytes = b""
    masked_full_image: bytes = b""
    full_text_result: OCRTextResult | None = None
    table_result: TableRecognitionResult | None = None
    full_text: str = ""
    nutrition_json: dict[str, Any] = field(default_factory=dict)
    ingredient_terms: list[str] = field(default_factory=list)
    ingredients_text: str = ""
    rag_results_json: dict[str, Any] = field(default_factory=dict)
    llm_output_json: dict[str, Any] = field(default_factory=dict)
    score: int = 0
    artifact_urls: dict[str, Any] | None = None


class _SupportsModelDump(Protocol):
    """表示可以导出为普通字典的对象。"""
    def model_dump(self) -> dict[str, Any]:
        ...


@overload
def _to_plain_data(value: None) -> None: ...


@overload
def _to_plain_data(value: dict[str, Any]) -> dict[str, Any]: ...


@overload
def _to_plain_data(value: list[T]) -> list[T]: ...


@overload
def _to_plain_data(value: _SupportsModelDump) -> dict[str, Any]: ...


@overload
def _to_plain_data(value: T) -> T: ...


def _to_plain_data(value: Any) -> Any:
    """把 Pydantic 模型、字典、列表等统一转成普通 Python 数据。"""
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
    """确认某一步输出的是字典；不是字典就认为流程数据不合法。"""
    plain_value = _to_plain_data(value)
    if not isinstance(plain_value, dict):
        raise AnalysisPayloadError(f"{payload_name} payload must be a dict")
    return plain_value


def _calculate_rule_based_score(
    nutrition_json: dict[str, Any],
    rag_results_json: dict[str, Any],
    llm_output_json: dict[str, Any],
) -> int:
    """用规则评分器重新计算健康分，避免直接相信大模型给的分数。"""
    raw_ingredients = llm_output_json.get("ingredients")
    if not isinstance(raw_ingredients, list):
        raise AnalysisPayloadError("llm ingredients payload must be a list")

    try:
        nutrition_data = NutritionData.model_validate(nutrition_json)
        rag_results = RAGResults.model_validate(rag_results_json)
        ingredients = [
            IngredientItem.model_validate(item)
            for item in raw_ingredients
        ]
    except ValidationError as exc:
        raise AnalysisPayloadError("score input payload is invalid") from exc

    score, _ = calculate_health_score(nutrition_data, ingredients, rag_results)
    return score


def _elapsed_ms_since(started_at: float) -> int:
    """计算从开始时间到现在过了多少毫秒。"""
    return int((perf_counter() - started_at) * 1000)


def _record_step_timing(
    context: AnalysisContext, timing_key: str, started_at: float
) -> None:
    """把某个分析步骤的耗时记到任务上下文里。"""
    context.timings[timing_key] = int((perf_counter() - started_at) * 1000)


def _record_task_attempt_metrics(
    *,
    status: str,
    started_at: float,
    timings: dict[str, int],
) -> None:
    """把一次任务尝试的状态和耗时写进监控指标。"""
    record_analysis_task_metrics(
        status=status,
        total_elapsed_ms=_elapsed_ms_since(started_at),
        timings=timings,
    )


def _record_retryable_dependency_error(exc: Exception, *, operation: str) -> None:
    """把可重试的外部依赖异常记录到监控里。"""
    if isinstance(exc, OCRServiceError):
        service = "ocr"
    elif isinstance(exc, LLMServiceError):
        service = "llm"
    elif isinstance(exc, StorageServiceError):
        service = "storage"
    elif isinstance(exc, EmbeddingServiceError):
        service = "embedding"
    else:
        return

    record_external_dependency_error(
        service=service,
        operation=operation,
        error_type=type(exc).__name__,
    )


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


def _download_source_image(context: AnalysisContext) -> None:
    """从对象存储下载用户上传的原图。"""
    step_started = perf_counter()
    context.image_bytes = _download_image(context.image_key)
    _record_step_timing(context, "download_ms", step_started)


def _detect_and_prepare_images(context: AnalysisContext) -> None:
    """用 YOLO 找营养成分表，并准备裁剪图和遮罩图。"""
    step_started = perf_counter()
    context.bbox = yolo_worker.detect(context.image_bytes)
    context.cropped_image = (
        yolo_worker.crop_image(context.image_bytes, context.bbox)
        if context.bbox
        else context.image_bytes
    )
    context.masked_full_image = (
        yolo_worker.mask_image(context.image_bytes, context.bbox)
        if context.bbox
        else context.image_bytes
    )
    _record_step_timing(context, "yolo_ms", step_started)


def _run_ocr_step(context: AnalysisContext) -> None:
    """根据有没有检测框选择 OCR 策略。"""
    step_started = perf_counter()
    if context.bbox:
        context.full_text_result, context.table_result = _run_ocr_with_bbox_fallback(
            task_id=context.task_id,
            image_bytes=context.image_bytes,
            masked_full_image=context.masked_full_image,
            cropped_image=context.cropped_image,
        )
    else:
        context.full_text_result = _run_ocr_full_text(context.image_bytes)
        try:
            context.table_result = _run_ocr_table(context.image_bytes)
        except OCRServiceError as exc:
            record_external_dependency_error(
                service="ocr",
                operation="nutrition_table_full_image_scan",
                error_type=type(exc).__name__,
            )
            logger.warning(
                "nutrition_table_full_image_scan_failed",
                task_id=context.task_id,
                error_message=str(exc),
            )
            context.table_result = None
    context.full_text = context.full_text_result.raw_text
    _record_step_timing(context, "ocr_ms", step_started)


def _parse_nutrition_step(context: AnalysisContext) -> None:
    """解析营养成分表，得到后续评分要用的营养数据。"""
    step_started = perf_counter()
    table_result = context.table_result
    fallback_parts: list[str] = []
    if table_result and table_result.ocr_fallback_text:
        fallback_parts.append(table_result.ocr_fallback_text.strip())
    if context.full_text and context.full_text.strip():
        full_text = context.full_text.strip()
        if full_text not in fallback_parts:
            fallback_parts.append(full_text)

    nutrition_output = nutrition_extractor.parse(
        table_result.model_dump() if table_result else None,
        "\n\n".join(fallback_parts) or None,
    )
    context.nutrition_json = _require_dict_payload("nutrition", nutrition_output)
    _record_step_timing(context, "nutrition_ms", step_started)


def _extract_ingredients_step(context: AnalysisContext) -> None:
    """从 OCR 全文中提取配料表。"""
    step_started = perf_counter()
    context.ingredient_terms, context.ingredients_text = ingredient_extractor.extract(
        context.full_text
    )
    _record_step_timing(context, "ingredients_ms", step_started)


def _retrieve_rag_step(context: AnalysisContext) -> None:
    """用配料词去知识库里检索相关标准和说明。"""
    step_started = perf_counter()
    rag_output = _run_rag(context.ingredient_terms, context.ingredients_text)
    context.rag_results_json = _require_dict_payload("rag", rag_output)
    _record_step_timing(context, "rag_ms", step_started)


def _run_llm_step(context: AnalysisContext) -> None:
    """调用大模型生成报告主体，并写入规则评分结果。"""
    step_started = perf_counter()
    llm_output = _run_llm(
        context.full_text,
        context.nutrition_json,
        context.rag_results_json,
        context.ingredient_terms,
        context.ingredients_text,
    )
    context.llm_output_json = _require_dict_payload("llm", llm_output)
    context.llm_output_json = _ensure_ingredient_coverage(
        context.llm_output_json,
        context.ingredient_terms,
        context.rag_results_json,
    )
    context.score = _calculate_rule_based_score(
        context.nutrition_json,
        context.rag_results_json,
        context.llm_output_json,
    )
    context.llm_output_json["score"] = context.score
    _record_step_timing(context, "llm_ms", step_started)


def _persist_result_step(context: AnalysisContext) -> None:
    """保存分析产物，并把报告写入数据库。"""
    if context.full_text_result is None:
        raise AnalysisPayloadError("full_text_result is missing")

    context.artifact_urls = _persist_analysis_artifacts(
        task_id=context.task_id,
        user_id=context.user_id,
        source_image_key=context.image_key,
        bbox=context.bbox,
        masked_full_image=context.masked_full_image if context.bbox else None,
        cropped_image=context.cropped_image if context.bbox else None,
        full_text_result=context.full_text_result,
        table_result=context.table_result,
        nutrition_json=context.nutrition_json,
        rag_results_json=context.rag_results_json,
        llm_output_json=context.llm_output_json,
    )
    _complete_task_with_report(
        task_id=context.task_id,
        user_id=context.user_id,
        ingredients_text=context.ingredients_text,
        nutrition_json=context.nutrition_json,
        rag_results_json=context.rag_results_json,
        llm_output_json=context.llm_output_json,
        score=context.score,
        artifact_urls=context.artifact_urls,
    )


def run_analysis_pipeline(task_id: str, image_key: str, user_id: str) -> AnalysisContext:
    """按顺序跑完整个图片分析流程。"""
    context = AnalysisContext(task_id=task_id, image_key=image_key, user_id=user_id)
    _download_source_image(context)
    _detect_and_prepare_images(context)
    _run_ocr_step(context)
    _parse_nutrition_step(context)
    _extract_ingredients_step(context)
    _retrieve_rag_step(context)
    _run_llm_step(context)
    _persist_result_step(context)
    return context

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
    """Celery 执行入口，负责跑分析任务并处理重试、超时和失败状态。"""
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
        context = run_analysis_pipeline(task_id, image_key, user_id)
        timings = context.timings
        total_elapsed_ms = _elapsed_ms_since(started_at)
        _record_task_attempt_metrics(
            status=TaskStatus.COMPLETED.value,
            started_at=started_at,
            timings=timings,
        )
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
        _record_task_attempt_metrics(
            status="timeout",
            started_at=started_at,
            timings=timings,
        )
        logger.warning("analysis_task_timeout", task_id=task_id, timings=timings)
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except (
        OCRServiceError,
        LLMServiceError,
        StorageServiceError,
        EmbeddingServiceError,
    ) as exc:
        _record_retryable_dependency_error(exc, operation="process_image_task")
        if self.request.retries < self.max_retries:
            _record_task_attempt_metrics(
                status="retrying",
                started_at=started_at,
                timings=timings,
            )
            logger.warning(
                "analysis_task_retrying",
                task_id=task_id,
                retries=self.request.retries,
                exception_type=exc.__class__.__name__,
                exception_message=str(exc),
            )
            raise self.retry(exc=exc, countdown=10)
        _update_task_status(task_id, TaskStatus.FAILED, str(exc))
        _record_task_attempt_metrics(
            status=TaskStatus.FAILED.value,
            started_at=started_at,
            timings=timings,
        )
        logger.warning(
            "analysis_task_failed_after_retries",
            task_id=task_id,
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except NotImplementedError as exc:
        _update_task_status(task_id, TaskStatus.FAILED, str(exc))
        _record_task_attempt_metrics(
            status="not_implemented",
            started_at=started_at,
            timings=timings,
        )
        logger.warning(
            "analysis_task_not_implemented", task_id=task_id, error_message=str(exc)
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except Exception as exc:
        _update_task_status(task_id, TaskStatus.FAILED, _INTERNAL_ANALYSIS_ERROR_MESSAGE)
        _record_task_attempt_metrics(
            status="unexpected_failure",
            started_at=started_at,
            timings=timings,
        )
        logger.exception(
            "analysis_task_unexpected_failure",
            task_id=task_id,
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}


__all__ = ["process_image_task"]
