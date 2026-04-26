"""Celery 异步任务和分析流程编排。"""


from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from minio import Minio
from minio.error import InvalidResponseError, MinioException, S3Error, ServerError
from pydantic import ValidationError
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.errors import StorageServiceError
from app.db.session import get_sync_db
from app.models.analysis_task import AnalysisTask, TaskStatus
from app.models.report import Report
from app.schemas.analysis_data import FoodHealthAnalysisOutput, NutritionData, RAGResults

logger = structlog.get_logger(__name__)
_MUTABLE_TASK_STATUSES = (TaskStatus.PENDING, TaskStatus.PROCESSING)


def _validate_optional_json(
    model_cls, payload: dict[str, Any] | None, field_name: str
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload
    try:
        return model_cls.model_validate(payload).model_dump()
    except ValidationError as exc:
        logger.warning(
            "report_json_validation_skipped",
            field_name=field_name,
            validation_errors=exc.errors(),
        )
        return payload

def _download_image(image_key: str) -> bytes:
    settings = get_settings()
    client = Minio(
        endpoint=settings.minio_client_endpoint,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
        secure=settings.MINIO_USE_SSL,
    )
    response = None
    try:
        response = client.get_object(settings.MINIO_BUCKET_NAME, image_key)
        return response.read()
    except (InvalidResponseError, MinioException, OSError, S3Error, ServerError) as exc:
        raise StorageServiceError("Failed to download source image") from exc
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def _update_task_status(
    task_id: str, status: TaskStatus, error_message: str | None = None
) -> None:
    """更新已有数据或状态。"""
    task_uuid = uuid.UUID(task_id)
    values: dict[str, Any] = {
        "status": status,
        "error_message": error_message,
    }
    if status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        values["completed_at"] = datetime.now(timezone.utc)
    elif status == TaskStatus.PROCESSING:
        values["completed_at"] = None

    # Sync-only persistence helper used by Celery worker tasks.
    with get_sync_db() as db:
        result = db.execute(
            update(AnalysisTask)
            .where(
                AnalysisTask.id == task_uuid,
                AnalysisTask.status.in_(_MUTABLE_TASK_STATUSES),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            logger.info(
                "analysis_task_status_update_skipped",
                task_id=task_id,
                target_status=status.value,
            )


def _complete_task_with_report(
    task_id: str,
    user_id: str,
    ingredients_text: str,
    nutrition_json: dict[str, Any] | None,
    rag_results_json: dict[str, Any] | None,
    llm_output_json: dict[str, Any],
    score: int,
    artifact_urls: dict[str, Any] | None = None,
) -> None:
    task_uuid = uuid.UUID(task_id)
    user_uuid = uuid.UUID(user_id)

    # Sync-only persistence helper used by Celery worker tasks.
    with get_sync_db() as db:
        task_result = db.execute(
            select(AnalysisTask)
            .where(AnalysisTask.id == task_uuid)
            .with_for_update()
        )
        task = task_result.scalar_one_or_none()
        if task is None:
            return

        result = db.execute(select(Report).where(Report.task_id == task_uuid))
        report = result.scalar_one_or_none()
        if task.status == TaskStatus.FAILED:
            logger.info(
                "analysis_task_completion_skipped_failed",
                task_id=task_id,
            )
            return
        if task.status == TaskStatus.COMPLETED and report is not None:
            logger.info(
                "analysis_task_completion_skipped_completed",
                task_id=task_id,
                report_id=str(report.id),
            )
            return

        validated_llm_output = FoodHealthAnalysisOutput.model_validate(
            llm_output_json
        ).model_dump()
        validated_nutrition = _validate_optional_json(
            NutritionData, nutrition_json, "nutrition_json"
        )
        validated_rag_results = _validate_optional_json(
            RAGResults, rag_results_json, "rag_results_json"
        )
        parse_source = None
        nutrition_source_payload = (
            validated_nutrition
            if isinstance(validated_nutrition, dict)
            else nutrition_json
        )
        if isinstance(nutrition_source_payload, dict):
            raw_parse_source = nutrition_source_payload.get("parse_method")
            parse_source = (
                str(raw_parse_source) if isinstance(raw_parse_source, str) else None
            )

        if report is None:
            report = Report(
                task_id=task_uuid,
                user_id=user_uuid,
                score=score,
                llm_output_json=validated_llm_output,
            )
            db.add(report)

        report.ingredients_text = ingredients_text
        report.nutrition_json = validated_nutrition
        report.nutrition_parse_source = parse_source
        report.rag_results_json = validated_rag_results
        report.llm_output_json = validated_llm_output
        report.score = score
        report.artifact_urls = artifact_urls

        task.status = TaskStatus.COMPLETED
        task.error_message = None
        task.completed_at = datetime.now(timezone.utc)
