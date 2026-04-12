from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from app.core.errors import StorageServiceError
from app.services.storage_service import get_storage_service
from app.workers.ocr_worker import OCRTextResult, TableRecognitionResult

logger = structlog.get_logger(__name__)


def _build_artifact_urls(
    full_text_result: OCRTextResult,
    table_result: TableRecognitionResult | None,
) -> dict[str, str] | None:
    artifact_urls: dict[str, str] = {}
    if full_text_result.artifact_json_url:
        artifact_urls["ocr_full_json_url"] = full_text_result.artifact_json_url
    if table_result and table_result.table_html_url:
        artifact_urls["table_html_url"] = table_result.table_html_url
    if table_result and table_result.table_xlsx_url:
        artifact_urls["table_xlsx_url"] = table_result.table_xlsx_url
    return artifact_urls or None

def _build_artifact_object_key(
    user_id: str, task_id: str, *parts: str, extension: str
) -> str:
    prefix = "/".join(part.strip("/") for part in parts if part)
    return f"reports/{user_id}/{task_id}/{prefix}.{extension}"

def _upload_artifact_bytes(
    user_id: str,
    task_id: str,
    *,
    parts: tuple[str, ...],
    extension: str,
    data: bytes,
    content_type: str,
) -> str:
    object_key = _build_artifact_object_key(
        user_id,
        task_id,
        *parts,
        extension=extension,
    )
    asyncio.run(
        get_storage_service().upload_artifact(
            data=data,
            object_key=object_key,
            content_type=content_type,
        )
    )
    return object_key

def _upload_json_artifact(
    user_id: str,
    task_id: str,
    *,
    parts: tuple[str, ...],
    payload: dict[str, Any] | list[Any],
) -> str:
    return _upload_artifact_bytes(
        user_id,
        task_id,
        parts=parts,
        extension="json",
        data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json",
    )

def _persist_analysis_artifacts(
    *,
    task_id: str,
    user_id: str,
    source_image_key: str,
    bbox: dict[str, Any] | None,
    masked_full_image: bytes | None,
    cropped_image: bytes | None,
    full_text_result: OCRTextResult,
    table_result: TableRecognitionResult | None,
    nutrition_json: dict[str, Any],
    rag_results_json: dict[str, Any],
    llm_output_json: dict[str, Any],
) -> dict[str, str] | None:
    artifact_refs = _build_artifact_urls(full_text_result, table_result) or {}
    artifact_refs["source_image_key"] = source_image_key

    try:
        if bbox:
            artifact_refs["nutrition_bbox_key"] = _upload_json_artifact(
                user_id,
                task_id,
                parts=("vision", "nutrition_bbox"),
                payload=bbox,
            )
            if masked_full_image:
                artifact_refs["masked_image_key"] = _upload_artifact_bytes(
                    user_id,
                    task_id,
                    parts=("images", "masked_full"),
                    extension="jpg",
                    data=masked_full_image,
                    content_type="image/jpeg",
                )
            if cropped_image:
                artifact_refs["cropped_image_key"] = _upload_artifact_bytes(
                    user_id,
                    task_id,
                    parts=("images", "nutrition_crop"),
                    extension="jpg",
                    data=cropped_image,
                    content_type="image/jpeg",
                )

        artifact_refs["ocr_full_result_key"] = _upload_json_artifact(
            user_id,
            task_id,
            parts=("ocr", "full_text_result"),
            payload=full_text_result.model_dump(),
        )
        if table_result is not None:
            artifact_refs["nutrition_table_result_key"] = _upload_json_artifact(
                user_id,
                task_id,
                parts=("ocr", "nutrition_table_result"),
                payload=table_result.model_dump(),
            )
        if nutrition_json:
            artifact_refs["nutrition_parse_key"] = _upload_json_artifact(
                user_id,
                task_id,
                parts=("analysis", "nutrition"),
                payload=nutrition_json,
            )
        if rag_results_json:
            artifact_refs["rag_results_key"] = _upload_json_artifact(
                user_id,
                task_id,
                parts=("analysis", "rag_results"),
                payload=rag_results_json,
            )
        if llm_output_json:
            artifact_refs["llm_output_key"] = _upload_json_artifact(
                user_id,
                task_id,
                parts=("analysis", "llm_output"),
                payload=llm_output_json,
            )
    except StorageServiceError as exc:
        logger.warning(
            "analysis_artifact_upload_failed",
            task_id=task_id,
            user_id=user_id,
            error_message=str(exc),
        )

    return artifact_refs or None
