from __future__ import annotations

import io
import uuid
from typing import Literal, cast

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import (
    FileTooLargeError,
    InvalidFileTypeError,
    TaskNotFoundError,
    TooManyConcurrentTasksError,
)
from app.models.analysis_task import AnalysisTask, TaskStatus
from app.models.report import Report
from app.schemas.analysis import (
    STATUS_MESSAGES,
    TaskStatusResponse,
    sanitize_error_message,
    to_external_task_status,
)

UPLOAD_CHUNK_SIZE = 1024 * 1024
_ADVISORY_LOCK_SQL = text("SELECT pg_advisory_xact_lock(:lock_key)")


def _detect_image_type(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _task_slot_lock_key(user_id: uuid.UUID) -> int:
    return user_id.int & ((1 << 63) - 1)


async def _acquire_task_slot_lock(user_id: uuid.UUID, db: AsyncSession) -> None:
    await db.execute(_ADVISORY_LOCK_SQL, {"lock_key": _task_slot_lock_key(user_id)})


async def validate_file(file: UploadFile) -> tuple[bytes, str]:
    settings = get_settings()
    if file is None or not file.filename:
        raise InvalidFileTypeError("上传文件缺失")

    file_chunks: list[bytes] = []
    file_size = 0

    while True:
        chunk = await file.read(UPLOAD_CHUNK_SIZE)
        if not chunk:
            break

        file_size += len(chunk)
        if file_size > settings.max_upload_size_bytes:
            raise FileTooLargeError(f"上传文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制")
        file_chunks.append(chunk)

    if file_size == 0:
        raise InvalidFileTypeError("上传文件为空")

    file_bytes = b"".join(file_chunks)
    content_type = _detect_image_type(file_bytes)
    if content_type is None or content_type not in settings.allowed_image_types_list:
        raise InvalidFileTypeError("仅支持 JPG、PNG 和 WEBP 图片")

    try:
        with Image.open(io.BytesIO(file_bytes)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidFileTypeError("上传图片已损坏") from exc

    return file_bytes, content_type


async def _assert_concurrent_limit_available(
    user_id: uuid.UUID, db: AsyncSession
) -> None:
    settings = get_settings()
    result = await db.execute(
        select(func.count())
        .select_from(AnalysisTask)
        .where(
            AnalysisTask.user_id == user_id,
            AnalysisTask.status.in_((TaskStatus.PENDING, TaskStatus.PROCESSING)),
        )
    )
    count = int(result.scalar_one())
    if count >= settings.USER_MAX_CONCURRENT_TASKS:
        raise TooManyConcurrentTasksError()


async def _create_task_record(
    user_id: uuid.UUID,
    image_key: str,
    image_url: str,
    db: AsyncSession,
) -> AnalysisTask:
    task = AnalysisTask(
        user_id=user_id,
        image_key=image_key,
        image_url=image_url,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    await db.flush()
    return task


async def create_task_with_limit_guard(
    user_id: uuid.UUID,
    image_key: str,
    image_url: str,
    db: AsyncSession,
) -> AnalysisTask:
    await _acquire_task_slot_lock(user_id, db)
    await _assert_concurrent_limit_available(user_id, db)
    return await _create_task_record(user_id, image_key, image_url, db)


async def update_celery_task_id(
    task_id: uuid.UUID, celery_task_id: str, db: AsyncSession
) -> None:
    task = await db.get(AnalysisTask, task_id)
    if task is not None:
        task.celery_task_id = celery_task_id
        await db.flush()


async def get_task_with_permission(
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AnalysisTask:
    result = await db.execute(
        select(AnalysisTask)
        .options(selectinload(AnalysisTask.report))
        .where(AnalysisTask.id == task_id, AnalysisTask.user_id == user_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError()
    return task


async def get_task_status_payload(
    task: AnalysisTask, db: AsyncSession
) -> TaskStatusResponse:
    report = task.report
    if report is None and task.status == TaskStatus.COMPLETED:
        result = await db.execute(select(Report).where(Report.task_id == task.id))
        report = result.scalar_one_or_none()
    external_status = cast(
        "Literal['queued', 'processing', 'completed', 'failed']",
        to_external_task_status(task.status.value),
    )
    nutrition_parse_source = cast(
        "Literal['table_recognition', 'ocr_text', 'llm_fallback', 'empty', 'failed'] | None",
        report.nutrition_parse_source if report is not None else None,
    )

    return TaskStatusResponse(
        task_id=task.id,
        status=external_status,
        progress_message=STATUS_MESSAGES.get(
            external_status,
            "系统正在处理中",
        ),
        created_at=task.created_at,
        completed_at=task.completed_at,
        report_id=report.id if report is not None else None,
        error_message=sanitize_error_message(task.error_message),
        nutrition_parse_source=nutrition_parse_source,
    )


__all__ = [
    "create_task_with_limit_guard",
    "get_task_status_payload",
    "get_task_with_permission",
    "update_celery_task_id",
    "validate_file",
]
