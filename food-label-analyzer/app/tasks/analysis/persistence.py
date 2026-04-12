from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from minio import Minio
from minio.error import InvalidResponseError, MinioException, S3Error, ServerError
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import StorageServiceError
from app.db.session import get_sync_db
from app.models.analysis_task import AnalysisTask, TaskStatus
from app.models.report import Report
from app.schemas.analysis_data import FoodHealthAnalysisOutput, NutritionData, RAGResults

logger = structlog.get_logger(__name__)


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
    task_uuid = uuid.UUID(task_id)
    with get_sync_db() as db:
        task = db.get(AnalysisTask, task_uuid)
        if task is None:
            return
        task.status = status
        task.error_message = error_message
        if status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            task.completed_at = datetime.now(timezone.utc)
        elif status == TaskStatus.PROCESSING:
            task.completed_at = None

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
        validated_nutrition if isinstance(validated_nutrition, dict) else nutrition_json
    )
    if isinstance(nutrition_source_payload, dict):
        raw_parse_source = nutrition_source_payload.get("parse_method")
        parse_source = (
            str(raw_parse_source) if isinstance(raw_parse_source, str) else None
        )

    with get_sync_db() as db:
        task = db.get(AnalysisTask, task_uuid)
        if task is None:
            return

        result = db.execute(select(Report).where(Report.task_id == task_uuid))
        report = result.scalar_one_or_none()
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
