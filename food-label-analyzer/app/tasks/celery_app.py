from __future__ import annotations

import importlib
import os

from chromadb.errors import ChromaError
import structlog
from celery import Celery
from celery.signals import worker_init, worker_process_init

from app.core.config import get_settings
from app.core.errors import EmbeddingServiceError, LLMServiceError, OCRServiceError
from app.core.logging import setup_logging
from app.workers import llm_worker, ocr_worker, rag_worker, yolo_worker

settings = get_settings()
_IS_WINDOWS = os.name == "nt"
_WARMED_UP_PID: int | None = None

celery_app = Celery("food_label_analyzer")
celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_default_queue="analysis",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=270,
    task_time_limit=300,
    worker_max_tasks_per_child=200,
    worker_pool="solo" if _IS_WINDOWS else None,
    worker_concurrency=1 if _IS_WINDOWS else None,
    timezone="Asia/Shanghai",
    enable_utc=True,
)
importlib.import_module("app.tasks.analysis_task")


def _configure_worker_resources() -> None:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    logger = structlog.get_logger(__name__)
    logger.info("celery_worker_initializing")

    try:
        llm_worker.validate_configuration()
    except LLMServiceError as exc:
        logger.warning("llm_configuration_invalid", error=str(exc))

    logger.info("celery_worker_configured")


def _warmup_worker_resources() -> None:
    global _WARMED_UP_PID
    current_pid = os.getpid()
    if _WARMED_UP_PID == current_pid:
        return

    logger = structlog.get_logger(__name__)
    logger.info("celery_worker_warming_up", pid=current_pid)

    try:
        yolo_worker.warmup()
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        logger.warning("yolo_warmup_failed", error=str(exc))

    try:
        ocr_worker.warmup()
    except (ImportError, OSError, RuntimeError, OCRServiceError, ValueError) as exc:
        logger.warning("ocr_warmup_failed", error=str(exc))

    try:
        rag_worker.warmup()
    except (ChromaError, EmbeddingServiceError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("rag_warmup_failed", error=str(exc))

    _WARMED_UP_PID = current_pid
    logger.info("celery_worker_warmed_up", pid=current_pid)


def _initialize_worker_resources() -> None:
    _configure_worker_resources()
    _warmup_worker_resources()


@worker_init.connect
def on_worker_init(**kwargs) -> None:
    _configure_worker_resources()
    if _IS_WINDOWS:
        _warmup_worker_resources()


@worker_process_init.connect
def on_worker_process_init(**kwargs) -> None:
    if not _IS_WINDOWS:
        _warmup_worker_resources()


__all__ = [
    "celery_app",
    "on_worker_init",
    "on_worker_process_init",
    "_configure_worker_resources",
    "_warmup_worker_resources",
    "_initialize_worker_resources",
]
