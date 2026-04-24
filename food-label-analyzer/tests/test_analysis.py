from __future__ import annotations

import asyncio
import importlib
import io
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.dialects import postgresql
from starlette.datastructures import UploadFile

from app.core.error_handlers import register_exception_handlers
from app.core.errors import (
    FileTooLargeError,
    InvalidFileTypeError,
    TooManyConcurrentTasksError,
)
from app.models.analysis_task import AnalysisTask, TaskStatus
from app.models.report import Report
from app.models.user import User
from app.schemas.analysis_data import SUPPORTED_HEALTH_ADVICE_GROUPS
from app.workers.ocr_worker import OCRParallelResult, OCRTextResult, TableRecognitionResult
from tests.conftest import load_required_env


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _ScalarsResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return SimpleNamespace(all=lambda: self._items)


class _SyncDbContext:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, exc_type, exc, traceback):
        return False


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color=(255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_file(filename: str, payload: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(payload))


def _build_analysis_app(monkeypatch: pytest.MonkeyPatch):
    load_required_env(monkeypatch)
    api_module = importlib.reload(importlib.import_module("app.api.v1.analysis"))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_module.router)
    return app, api_module


def _health_advice_payload() -> list[dict[str, str]]:
    return [
        {
            "group": group,
            "risk": "warning",
            "advice": f"{group} should limit this product and monitor sodium intake carefully every week.",
            "hint": "Limit intake",
        }
        for group in sorted(SUPPORTED_HEALTH_ADVICE_GROUPS)
    ]


def _llm_output_payload(score: int = 88) -> dict[str, object]:
    return {
        "score": score,
        "summary": "S" * 60,
        "top_risks": ["salt"],
        "ingredients": [],
        "health_advice": _health_advice_payload(),
    }


def test_validate_file_accepts_png_and_rejects_invalid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    task_service_module = importlib.reload(
        importlib.import_module("app.services.task_service")
    )

    payload, content_type = asyncio.run(
        task_service_module.validate_file(_upload_file("tiny.png", _png_bytes()))
    )
    assert content_type == "image/png"
    assert payload.startswith(b"\x89PNG")

    with pytest.raises(InvalidFileTypeError):
        asyncio.run(
            task_service_module.validate_file(_upload_file("bad.png", b"not-an-image"))
        )


def test_validate_file_rejects_large_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    load_required_env(monkeypatch)
    task_service_module = importlib.reload(
        importlib.import_module("app.services.task_service")
    )
    oversized = b"x" * ((10 * 1024 * 1024) + 1)

    with pytest.raises(FileTooLargeError):
        asyncio.run(
            task_service_module.validate_file(_upload_file("big.png", oversized))
        )


def test_validate_file_accepts_limit_boundary_and_rejects_one_byte_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    task_service_module = importlib.reload(
        importlib.import_module("app.services.task_service")
    )
    payload = _png_bytes()
    monkeypatch.setattr(
        task_service_module,
        "get_settings",
        lambda: SimpleNamespace(
            max_upload_size_bytes=len(payload),
            MAX_UPLOAD_SIZE_MB=1,
            allowed_image_types_list=["image/png"],
        ),
    )

    accepted_payload, content_type = asyncio.run(
        task_service_module.validate_file(_upload_file("tiny.png", payload))
    )
    assert accepted_payload == payload
    assert content_type == "image/png"

    with pytest.raises(FileTooLargeError):
        asyncio.run(
            task_service_module.validate_file(
                _upload_file("tiny.png", payload + b"x")
            )
        )


def test_create_task_with_limit_guard_raises_when_limit_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    task_service_module = importlib.reload(
        importlib.import_module("app.services.task_service")
    )
    fake_db = AsyncMock()
    fake_db.add = AsyncMock()
    fake_db.execute = AsyncMock(side_effect=[None, _ScalarResult(3)])

    with pytest.raises(TooManyConcurrentTasksError):
        asyncio.run(
            task_service_module.create_task_with_limit_guard(
                uuid.uuid4(),
                "uploads/key.png",
                "https://example.com/key.png",
                fake_db,
            )
        )

    fake_db.add.assert_not_called()


def test_get_task_status_payload_includes_report_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    task_service_module = importlib.reload(
        importlib.import_module("app.services.task_service")
    )
    task = AnalysisTask(
        user_id=uuid.uuid4(),
        image_key="uploads/u/test.png",
        image_url="https://example.com/image.png",
        status=TaskStatus.COMPLETED,
    )
    task.id = uuid.uuid4()
    task.created_at = datetime.now(timezone.utc)
    task.completed_at = datetime.now(timezone.utc)
    report = Report(
        task_id=task.id,
        user_id=task.user_id,
        score=90,
        llm_output_json={},
        nutrition_parse_source="ocr_text",
    )
    report.id = uuid.uuid4()
    task.report = report

    payload = asyncio.run(
        task_service_module.get_task_status_payload(task, AsyncMock())
    )

    assert payload.report_id == report.id
    assert payload.nutrition_parse_source == "ocr_text"
    assert payload.progress_message == "分析完成"


def test_analysis_upload_route_success(monkeypatch: pytest.MonkeyPatch) -> None:
    app, api_module = _build_analysis_app(monkeypatch)
    fake_db = AsyncMock()
    current_user = User(
        email="user@example.com",
        password_hash="hashed",
        is_verified=True,
        is_active=True,
    )
    current_user.id = uuid.uuid4()
    fake_task = SimpleNamespace(
        id=uuid.uuid4(),
        status=SimpleNamespace(value="pending"),
        created_at=datetime.now(timezone.utc),
    )
    storage = SimpleNamespace(
        upload_image=AsyncMock(
            return_value=("uploads/key.png", "https://example.com/key.png")
        ),
        delete_image=AsyncMock(),
    )
    events: list[str] = []

    async def fake_commit() -> None:
        events.append("commit")

    async def override_db():
        yield fake_db

    async def override_user():
        return current_user

    app.dependency_overrides[api_module.get_db] = override_db
    app.dependency_overrides[api_module.get_current_user] = override_user
    monkeypatch.setattr(
        api_module, "validate_file", AsyncMock(return_value=(b"img", "image/png"))
    )
    monkeypatch.setattr(api_module, "get_storage_service", lambda: storage)
    monkeypatch.setattr(
        api_module,
        "create_task_with_limit_guard",
        AsyncMock(return_value=fake_task),
    )
    update_celery_task_id = AsyncMock(side_effect=lambda *args: events.append("update"))
    fake_db.commit = AsyncMock(side_effect=fake_commit)
    send_task = Mock(
        side_effect=lambda *args, **kwargs: events.append("send")
        or SimpleNamespace(id="broker-generated-id")
    )
    monkeypatch.setattr(api_module, "update_celery_task_id", update_celery_task_id)
    monkeypatch.setattr(api_module.celery_app, "send_task", send_task)

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("tiny.png", _png_bytes(), "image/png")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["task_id"] == str(fake_task.id)
    assert payload["data"]["status"] == "queued"
    expected_celery_task_id = f"analysis:{fake_task.id}"
    send_task.assert_called_once_with(
        "analysis.process_image",
        args=[str(fake_task.id), "uploads/key.png", str(current_user.id)],
        queue="analysis",
        task_id=expected_celery_task_id,
    )
    update_celery_task_id.assert_awaited_once_with(
        fake_task.id,
        expected_celery_task_id,
        fake_db,
    )
    assert events == ["update", "commit", "send"]


def test_analysis_upload_route_rolls_back_when_enqueue_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, api_module = _build_analysis_app(monkeypatch)
    fake_db = AsyncMock()
    fake_db.rollback = AsyncMock()
    current_user = User(
        email="user@example.com",
        password_hash="hashed",
        is_verified=True,
        is_active=True,
    )
    current_user.id = uuid.uuid4()
    fake_task = SimpleNamespace(
        id=uuid.uuid4(),
        status=SimpleNamespace(value="pending"),
        created_at=datetime.now(timezone.utc),
    )
    storage = SimpleNamespace(
        upload_image=AsyncMock(
            return_value=("uploads/key.png", "https://example.com/key.png")
        ),
        delete_image=AsyncMock(),
    )

    async def override_db():
        yield fake_db

    async def override_user():
        return current_user

    app.dependency_overrides[api_module.get_db] = override_db
    app.dependency_overrides[api_module.get_current_user] = override_user
    monkeypatch.setattr(
        api_module, "validate_file", AsyncMock(return_value=(b"img", "image/png"))
    )
    monkeypatch.setattr(api_module, "get_storage_service", lambda: storage)
    monkeypatch.setattr(
        api_module,
        "create_task_with_limit_guard",
        AsyncMock(return_value=fake_task),
    )
    monkeypatch.setattr(api_module, "update_celery_task_id", AsyncMock())
    mark_task_enqueue_failed = AsyncMock()
    monkeypatch.setattr(
        api_module,
        "mark_task_enqueue_failed",
        mark_task_enqueue_failed,
    )
    monkeypatch.setattr(
        api_module.celery_app,
        "send_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("tiny.png", _png_bytes(), "image/png")},
        )

    assert response.status_code == 503
    fake_db.rollback.assert_not_awaited()
    assert fake_db.commit.await_count == 2
    mark_task_enqueue_failed.assert_awaited_once_with(
        fake_task.id,
        "分析任务入队失败",
        fake_db,
    )
    storage.delete_image.assert_awaited_once_with("uploads/key.png")


def test_analysis_upload_route_deletes_upload_when_limit_guard_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, api_module = _build_analysis_app(monkeypatch)
    fake_db = AsyncMock()
    current_user = User(
        email="user@example.com",
        password_hash="hashed",
        is_verified=True,
        is_active=True,
    )
    current_user.id = uuid.uuid4()
    storage = SimpleNamespace(
        upload_image=AsyncMock(
            return_value=("uploads/key.png", "https://example.com/key.png")
        ),
        delete_image=AsyncMock(),
    )

    async def override_db():
        yield fake_db

    async def override_user():
        return current_user

    app.dependency_overrides[api_module.get_db] = override_db
    app.dependency_overrides[api_module.get_current_user] = override_user
    monkeypatch.setattr(
        api_module, "validate_file", AsyncMock(return_value=(b"img", "image/png"))
    )
    monkeypatch.setattr(api_module, "get_storage_service", lambda: storage)
    monkeypatch.setattr(
        api_module,
        "create_task_with_limit_guard",
        AsyncMock(side_effect=TooManyConcurrentTasksError()),
    )

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("tiny.png", _png_bytes(), "image/png")},
        )

    assert response.status_code == 429
    storage.delete_image.assert_awaited_once_with("uploads/key.png")


def test_update_task_status_uses_mutable_status_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    persistence_module = importlib.reload(
        importlib.import_module("app.tasks.analysis.persistence")
    )
    fake_db = Mock()
    fake_db.execute.return_value = SimpleNamespace(rowcount=1)
    monkeypatch.setattr(
        persistence_module,
        "get_sync_db",
        lambda: _SyncDbContext(fake_db),
    )

    persistence_module._update_task_status(
        str(uuid.uuid4()),
        TaskStatus.PROCESSING,
    )

    statement = fake_db.execute.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "analysis_tasks.status IN" in compiled
    assert "analysis_tasks.id" in compiled


def test_update_task_status_skips_terminal_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    persistence_module = importlib.reload(
        importlib.import_module("app.tasks.analysis.persistence")
    )
    fake_db = Mock()
    fake_db.execute.return_value = SimpleNamespace(rowcount=0)
    logger = SimpleNamespace(info=Mock())
    monkeypatch.setattr(
        persistence_module,
        "get_sync_db",
        lambda: _SyncDbContext(fake_db),
    )
    monkeypatch.setattr(persistence_module, "logger", logger)

    persistence_module._update_task_status(
        str(uuid.uuid4()),
        TaskStatus.FAILED,
        "late failure",
    )

    logger.info.assert_called_once()
    assert logger.info.call_args.args[0] == "analysis_task_status_update_skipped"


def test_complete_task_with_report_is_idempotent_when_already_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    persistence_module = importlib.reload(
        importlib.import_module("app.tasks.analysis.persistence")
    )
    task_id = uuid.uuid4()
    user_id = uuid.uuid4()
    task = AnalysisTask(
        user_id=user_id,
        image_key="uploads/key.png",
        image_url="https://example.com/key.png",
        status=TaskStatus.COMPLETED,
    )
    task.id = task_id
    report = Report(
        task_id=task_id,
        user_id=user_id,
        ingredients_text="old",
        nutrition_json=None,
        rag_results_json=None,
        llm_output_json=_llm_output_payload(score=70),
        score=70,
    )
    report.id = uuid.uuid4()
    fake_db = Mock()
    fake_db.add = Mock()
    fake_db.execute.side_effect = [_ScalarResult(task), _ScalarResult(report)]
    logger = SimpleNamespace(info=Mock())
    monkeypatch.setattr(
        persistence_module,
        "get_sync_db",
        lambda: _SyncDbContext(fake_db),
    )
    monkeypatch.setattr(persistence_module, "logger", logger)

    persistence_module._complete_task_with_report(
        task_id=str(task_id),
        user_id=str(user_id),
        ingredients_text="new",
        nutrition_json=None,
        rag_results_json=None,
        llm_output_json=_llm_output_payload(score=88),
        score=88,
    )

    first_statement = fake_db.execute.call_args_list[0].args[0]
    assert "FOR UPDATE" in str(first_statement.compile(dialect=postgresql.dialect()))
    fake_db.add.assert_not_called()
    assert report.ingredients_text == "old"
    assert report.score == 70
    logger.info.assert_called_once()
    assert logger.info.call_args.args[0] == "analysis_task_completion_skipped_completed"


def test_complete_task_with_report_does_not_overwrite_failed_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    persistence_module = importlib.reload(
        importlib.import_module("app.tasks.analysis.persistence")
    )
    task_id = uuid.uuid4()
    user_id = uuid.uuid4()
    task = AnalysisTask(
        user_id=user_id,
        image_key="uploads/key.png",
        image_url="https://example.com/key.png",
        status=TaskStatus.FAILED,
    )
    task.id = task_id
    fake_db = Mock()
    fake_db.add = Mock()
    fake_db.execute.side_effect = [_ScalarResult(task), _ScalarResult(None)]
    logger = SimpleNamespace(info=Mock())
    monkeypatch.setattr(
        persistence_module,
        "get_sync_db",
        lambda: _SyncDbContext(fake_db),
    )
    monkeypatch.setattr(persistence_module, "logger", logger)

    persistence_module._complete_task_with_report(
        task_id=str(task_id),
        user_id=str(user_id),
        ingredients_text="new",
        nutrition_json=None,
        rag_results_json=None,
        llm_output_json=_llm_output_payload(),
        score=88,
    )

    fake_db.add.assert_not_called()
    assert task.status == TaskStatus.FAILED
    logger.info.assert_called_once()
    assert logger.info.call_args.args[0] == "analysis_task_completion_skipped_failed"


def test_complete_task_with_report_creates_report_and_completes_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    persistence_module = importlib.reload(
        importlib.import_module("app.tasks.analysis.persistence")
    )
    task_id = uuid.uuid4()
    user_id = uuid.uuid4()
    task = AnalysisTask(
        user_id=user_id,
        image_key="uploads/key.png",
        image_url="https://example.com/key.png",
        status=TaskStatus.PROCESSING,
    )
    task.id = task_id
    fake_db = Mock()
    fake_db.add = Mock()
    fake_db.execute.side_effect = [_ScalarResult(task), _ScalarResult(None)]
    monkeypatch.setattr(
        persistence_module,
        "get_sync_db",
        lambda: _SyncDbContext(fake_db),
    )

    persistence_module._complete_task_with_report(
        task_id=str(task_id),
        user_id=str(user_id),
        ingredients_text="salt",
        nutrition_json={"items": [], "parse_method": "ocr_text"},
        rag_results_json=None,
        llm_output_json=_llm_output_payload(score=88),
        score=88,
        artifact_urls={"ocr_full_json_url": "https://example.com/ocr.json"},
    )

    report = fake_db.add.call_args.args[0]
    assert isinstance(report, Report)
    assert report.ingredients_text == "salt"
    assert report.nutrition_parse_source == "ocr_text"
    assert report.score == 88
    assert task.status == TaskStatus.COMPLETED
    assert task.error_message is None
    assert task.completed_at is not None


def test_process_image_task_marks_failed_for_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    statuses: list[tuple[TaskStatus, str | None]] = []

    def fake_update(
        task_id: str, status: TaskStatus, error_message: str | None = None
    ) -> None:
        statuses.append((status, error_message))

    monkeypatch.setattr(analysis_task_module, "_update_task_status", fake_update)
    monkeypatch.setattr(
        analysis_task_module, "_download_image", lambda image_key: b"img"
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker,
        "detect",
        lambda image_bytes: (_ for _ in ()).throw(NotImplementedError("yolo missing")),
    )
    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        result = analysis_task_module.process_image_task.run(
            "task-id", "image-key", str(uuid.uuid4())
        )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert result["status"] == "failed"
    assert statuses[0][0] == TaskStatus.PROCESSING
    assert statuses[-1][0] == TaskStatus.FAILED


def test_process_image_task_retries_retryable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    statuses: list[tuple[TaskStatus, str | None]] = []
    metric_calls: list[dict[str, object]] = []
    dependency_errors: list[dict[str, str]] = []

    class RetryTriggered(Exception):
        pass

    def fake_update(
        task_id: str, status: TaskStatus, error_message: str | None = None
    ) -> None:
        statuses.append((status, error_message))

    def fake_retry(*, exc: Exception, countdown: int) -> None:
        raise RetryTriggered()

    monkeypatch.setattr(analysis_task_module, "_update_task_status", fake_update)
    monkeypatch.setattr(
        analysis_task_module,
        "record_analysis_task_metrics",
        lambda **kwargs: metric_calls.append(kwargs),
    )
    monkeypatch.setattr(
        analysis_task_module,
        "record_external_dependency_error",
        lambda **kwargs: dependency_errors.append(kwargs),
    )
    monkeypatch.setattr(
        analysis_task_module,
        "_download_image",
        lambda image_key: (_ for _ in ()).throw(
            analysis_task_module.StorageServiceError("storage down")
        ),
    )
    monkeypatch.setattr(analysis_task_module.process_image_task, "retry", fake_retry)
    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        with pytest.raises(RetryTriggered):
            analysis_task_module.process_image_task.run(
                "task-id", "image-key", str(uuid.uuid4())
            )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert statuses == [(TaskStatus.PROCESSING, None)]
    assert metric_calls and metric_calls[0]["status"] == "retrying"
    assert dependency_errors == [
        {
            "service": "storage",
            "operation": "process_image_task",
            "error_type": "StorageServiceError",
        }
    ]


def test_process_image_task_marks_failed_for_invalid_payload_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    statuses: list[tuple[TaskStatus, str | None]] = []

    monkeypatch.setattr(
        analysis_task_module,
        "_update_task_status",
        lambda task_id, status, error_message=None: statuses.append(
            (status, error_message)
        ),
    )
    monkeypatch.setattr(
        analysis_task_module, "_download_image", lambda image_key: b"img"
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker, "detect", lambda image_bytes: None
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_full_text",
        lambda image_bytes: OCRTextResult(
            raw_text="salt, sugar",
            lines=[{"text": "salt, sugar"}],
            blocks=[],
            artifact_json_url="https://example.com/ocr.json",
        ),
    )
    monkeypatch.setattr(
        analysis_task_module.nutrition_extractor,
        "parse",
        lambda *args, **kwargs: ["bad-payload"],
    )

    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        result = analysis_task_module.process_image_task.run(
            "task-id", "image-key", str(uuid.uuid4())
        )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert result["status"] == "failed"
    assert statuses[-1] == (
        TaskStatus.FAILED,
        "Internal analysis pipeline error",
    )


def test_process_image_task_hides_unexpected_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    statuses: list[tuple[TaskStatus, str | None]] = []

    monkeypatch.setattr(
        analysis_task_module,
        "_update_task_status",
        lambda task_id, status, error_message=None: statuses.append(
            (status, error_message)
        ),
    )
    monkeypatch.setattr(
        analysis_task_module, "_download_image", lambda image_key: b"img"
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker,
        "detect",
        lambda image_bytes: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        result = analysis_task_module.process_image_task.run(
            "task-id", "image-key", str(uuid.uuid4())
        )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert result["status"] == "failed"
    assert statuses[-1] == (
        TaskStatus.FAILED,
        "Internal analysis pipeline error",
    )


def test_process_image_task_completes_with_report_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    completions: list[dict[str, object]] = []

    monkeypatch.setattr(
        analysis_task_module, "_update_task_status", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        analysis_task_module, "_download_image", lambda image_key: b"img"
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker, "detect", lambda image_bytes: None
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_full_text",
        lambda image_bytes: OCRTextResult(
            raw_text="salt, sugar",
            lines=[{"text": "salt, sugar"}],
            blocks=[],
            artifact_json_url="https://example.com/ocr.json",
        ),
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_parallel",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_nutrition_table",
        lambda image_bytes: TableRecognitionResult(ocr_fallback_text=""),
    )
    monkeypatch.setattr(
        analysis_task_module.nutrition_extractor,
        "parse",
        lambda table_result, ocr_fallback_text=None: {
            "items": [],
            "parse_method": "ocr_text",
        },
    )
    monkeypatch.setattr(
        analysis_task_module.ingredient_extractor,
        "extract",
        lambda full_raw_text: (["salt", "sugar"], "salt, sugar"),
    )
    monkeypatch.setattr(
        analysis_task_module.rag_worker,
        "retrieve_all",
        lambda ingredient_terms, ingredients_text: {
            "source_file": "chromadb",
            "ingredients_text": ingredients_text,
            "items_total": 0,
            "retrieval_results": [],
        },
    )
    monkeypatch.setattr(
        analysis_task_module.llm_worker,
        "analyze",
        lambda other_ocr_raw_text, nutrition_json, rag_results_json: {
            "score": 88,
            "summary": "S" * 60,
            "top_risks": ["salt"],
            "ingredients": [],
            "health_advice": _health_advice_payload(),
        },
    )

    monkeypatch.setattr(
        analysis_task_module,
        "_persist_analysis_artifacts",
        lambda **kwargs: {"ocr_full_json_url": "https://example.com/ocr.json"},
    )

    def fake_complete(**kwargs):
        completions.append(kwargs)

    monkeypatch.setattr(
        analysis_task_module, "_complete_task_with_report", fake_complete
    )
    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        result = analysis_task_module.process_image_task.run(
            "task-id", "image-key", str(uuid.uuid4())
        )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert result["status"] == "completed"
    assert completions[0]["score"] == 80
    assert completions[0]["llm_output_json"]["score"] == 80
    assert completions[0]["nutrition_json"]["parse_method"] == "ocr_text"
    assert completions[0]["artifact_urls"] == {
        "ocr_full_json_url": "https://example.com/ocr.json"
    }


def test_process_image_task_overrides_llm_score_with_rule_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    completions: list[dict[str, object]] = []
    nutrition_payload = {
        "items": [
            {
                "name": "钠",
                "value": "2000",
                "unit": "mg",
                "daily_reference_percent": "100%",
            }
        ],
        "parse_method": "ocr_text",
    }
    ingredient_payload = {
        "name": "苯甲酸钠",
        "risk": "danger",
        "description": "常见防腐剂，摄入频率较高时需要重点关注总量。",
        "function_category": "防腐剂",
        "rules": ["GB2760-2024"],
    }

    from app.schemas.analysis_data import IngredientItem, NutritionData
    from app.services.score_calculator import calculate_health_score

    expected_score, _ = calculate_health_score(
        NutritionData.model_validate(nutrition_payload),
        [IngredientItem.model_validate(ingredient_payload)],
    )

    monkeypatch.setattr(
        analysis_task_module, "_update_task_status", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        analysis_task_module, "_download_image", lambda image_key: b"img"
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker, "detect", lambda image_bytes: None
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_full_text",
        lambda image_bytes: OCRTextResult(
            raw_text="配料：苯甲酸钠",
            lines=[{"text": "配料：苯甲酸钠"}],
            blocks=[],
        ),
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_nutrition_table",
        lambda image_bytes: TableRecognitionResult(ocr_fallback_text="钠 2000mg 100%"),
    )
    monkeypatch.setattr(
        analysis_task_module.nutrition_extractor,
        "parse",
        lambda table_result, ocr_fallback_text=None: nutrition_payload,
    )
    monkeypatch.setattr(
        analysis_task_module.ingredient_extractor,
        "extract",
        lambda full_raw_text: (["苯甲酸钠"], "配料：苯甲酸钠"),
    )
    monkeypatch.setattr(
        analysis_task_module.rag_worker,
        "retrieve_all",
        lambda ingredient_terms, ingredients_text: {
            "source_file": "chromadb",
            "ingredients_text": ingredients_text,
            "items_total": 1,
            "retrieval_results": [],
        },
    )
    monkeypatch.setattr(
        analysis_task_module.llm_worker,
        "analyze",
        lambda *args, **kwargs: {
            "score": 99,
            "summary": "S" * 60,
            "ingredients": [ingredient_payload],
            "health_advice": _health_advice_payload(),
        },
    )
    monkeypatch.setattr(
        analysis_task_module,
        "_persist_analysis_artifacts",
        lambda **kwargs: {"ocr_full_json_url": "https://example.com/ocr.json"},
    )
    monkeypatch.setattr(
        analysis_task_module,
        "_complete_task_with_report",
        lambda **kwargs: completions.append(kwargs),
    )

    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        result = analysis_task_module.process_image_task.run(
            "task-id", "image-key", str(uuid.uuid4())
        )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert result["status"] == "completed"
    assert expected_score != 99
    assert completions[0]["score"] == expected_score
    assert completions[0]["llm_output_json"]["score"] == expected_score


def test_parse_nutrition_step_includes_full_ocr_text_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    captured: dict[str, object] = {}
    context = analysis_task_module.AnalysisContext(
        task_id="task-id",
        image_key="image-key",
        user_id=str(uuid.uuid4()),
        table_result=TableRecognitionResult(
            table_json={
                "rows": [
                    ["营养成分表 NRV% 每100g 项目 4% 359kJ 能量 0%"],
                ]
            },
            ocr_fallback_text="营养成分表 NRV% 每100g 项目 4% 359kJ 能量 0%",
        ),
        full_text=(
            "<table><tr><td>项目</td><td>每100g</td><td>NRV%</td></tr>"
            "<tr><td>能量</td><td>359kJ</td><td>4%</td></tr></table>"
        ),
    )

    def fake_parse(table_result, ocr_fallback_text=None):
        captured["table_result"] = table_result
        captured["ocr_fallback_text"] = ocr_fallback_text
        return {"items": [], "parse_method": "table_recognition"}

    monkeypatch.setattr(
        analysis_task_module.nutrition_extractor,
        "parse",
        fake_parse,
    )

    analysis_task_module._parse_nutrition_step(context)

    assert "359kJ 能量" in str(captured["ocr_fallback_text"])
    assert "<table>" in str(captured["ocr_fallback_text"])


def test_process_image_task_records_metrics_for_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    metric_calls: list[dict[str, object]] = []
    dependency_errors: list[dict[str, str]] = []

    monkeypatch.setattr(
        analysis_task_module, "_update_task_status", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        analysis_task_module,
        "record_analysis_task_metrics",
        lambda **kwargs: metric_calls.append(kwargs),
    )
    monkeypatch.setattr(
        analysis_task_module,
        "record_external_dependency_error",
        lambda **kwargs: dependency_errors.append(kwargs),
    )
    monkeypatch.setattr(
        analysis_task_module, "_download_image", lambda image_key: b"img"
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker, "detect", lambda image_bytes: None
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_full_text",
        lambda image_bytes: OCRTextResult(
            raw_text="salt, sugar",
            lines=[{"text": "salt, sugar"}],
            blocks=[],
            artifact_json_url="https://example.com/ocr.json",
        ),
    )
    monkeypatch.setattr(
        analysis_task_module,
        "_run_ocr_table",
        lambda image_bytes: TableRecognitionResult(
            table_json={"rows": [["item", "per100g"], ["energy", "120kJ"]]},
            ocr_fallback_text="energy 120kJ",
        ),
    )
    monkeypatch.setattr(
        analysis_task_module.nutrition_extractor,
        "parse",
        lambda table_result, ocr_fallback_text=None: {
            "items": [],
            "parse_method": "ocr_text",
        },
    )
    monkeypatch.setattr(
        analysis_task_module.ingredient_extractor,
        "extract",
        lambda full_raw_text: (["salt", "sugar"], "salt, sugar"),
    )
    monkeypatch.setattr(
        analysis_task_module.rag_worker,
        "retrieve_all",
        lambda ingredient_terms, ingredients_text: {
            "source_file": "chromadb",
            "ingredients_text": ingredients_text,
            "items_total": 0,
            "retrieval_results": [],
        },
    )
    monkeypatch.setattr(
        analysis_task_module.llm_worker,
        "analyze",
        lambda other_ocr_raw_text, nutrition_json, rag_results_json: {
            "score": 88,
            "summary": "S" * 60,
            "top_risks": ["salt"],
            "ingredients": [],
            "health_advice": _health_advice_payload(),
        },
    )
    monkeypatch.setattr(
        analysis_task_module,
        "_persist_analysis_artifacts",
        lambda **kwargs: {"ocr_full_json_url": "https://example.com/ocr.json"},
    )
    monkeypatch.setattr(
        analysis_task_module, "_complete_task_with_report", lambda **kwargs: None
    )

    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        result = analysis_task_module.process_image_task.run(
            "task-id", "image-key", str(uuid.uuid4())
        )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert result["status"] == "completed"
    assert metric_calls and metric_calls[0]["status"] == "completed"
    assert metric_calls[0]["total_elapsed_ms"] >= 0
    assert set(metric_calls[0]["timings"].keys()) >= {
        "download_ms",
        "yolo_ms",
        "ocr_ms",
        "nutrition_ms",
        "ingredients_ms",
        "rag_ms",
        "llm_ms",
    }
    assert dependency_errors == []


def test_process_image_task_runs_parallel_ocr_when_yolo_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    completions: list[dict[str, object]] = []
    parallel_inputs: list[tuple[bytes, bytes]] = []

    monkeypatch.setattr(
        analysis_task_module, "_update_task_status", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        analysis_task_module, "_download_image", lambda image_key: b"img"
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker,
        "detect",
        lambda image_bytes: {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "confidence": 0.9},
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker,
        "crop_image",
        lambda image_bytes, bbox: b"cropped-img",
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker,
        "mask_image",
        lambda image_bytes, bbox: b"masked-img",
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_parallel",
        lambda full_text_image_bytes, nutrition_image_bytes=None: (
            parallel_inputs.append((full_text_image_bytes, nutrition_image_bytes))
            or OCRParallelResult(
                full_text=OCRTextResult(
                    raw_text="salt, sugar",
                    lines=[{"text": "salt, sugar"}],
                    blocks=[],
                    artifact_json_url="https://example.com/ocr.json",
                ),
                nutrition_table=TableRecognitionResult(
                    table_json={"table": [{"name": "energy", "value": "120", "unit": "kJ"}]},
                    ocr_fallback_text="energy 120kJ 2%",
                ),
            )
        ),
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_full_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    monkeypatch.setattr(
        analysis_task_module.nutrition_extractor,
        "parse",
        lambda table_result, ocr_fallback_text=None: {
            "items": [],
            "parse_method": "table_recognition",
        },
    )
    monkeypatch.setattr(
        analysis_task_module.ingredient_extractor,
        "extract",
        lambda full_raw_text: (["salt", "sugar"], "salt, sugar"),
    )
    monkeypatch.setattr(
        analysis_task_module.rag_worker,
        "retrieve_all",
        lambda ingredient_terms, ingredients_text: {
            "source_file": "chromadb",
            "ingredients_text": ingredients_text,
            "items_total": 0,
            "retrieval_results": [],
        },
    )
    monkeypatch.setattr(
        analysis_task_module.llm_worker,
        "analyze",
        lambda other_ocr_raw_text, nutrition_json, rag_results_json: {
            "score": 88,
            "summary": "S" * 60,
            "top_risks": ["salt"],
            "ingredients": [],
            "health_advice": _health_advice_payload(),
        },
    )

    monkeypatch.setattr(
        analysis_task_module,
        "_persist_analysis_artifacts",
        lambda **kwargs: {"ocr_full_json_url": "https://example.com/ocr.json"},
    )
    monkeypatch.setattr(
        analysis_task_module, "_complete_task_with_report", lambda **kwargs: completions.append(kwargs)
    )
    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        result = analysis_task_module.process_image_task.run(
            "task-id", "image-key", str(uuid.uuid4())
        )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert result["status"] == "completed"
    assert parallel_inputs == [(b"masked-img", b"cropped-img")]
    assert completions[0]["nutrition_json"]["parse_method"] == "table_recognition"


def test_process_image_task_falls_back_to_sequential_ocr_when_parallel_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    analysis_task_module = importlib.reload(
        importlib.import_module("app.tasks.analysis_task")
    )
    completions: list[dict[str, object]] = []
    full_text_calls: list[bytes] = []
    table_calls: list[bytes] = []

    monkeypatch.setattr(
        analysis_task_module, "_update_task_status", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        analysis_task_module, "_download_image", lambda image_key: b"img"
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker,
        "detect",
        lambda image_bytes: {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "confidence": 0.9},
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker,
        "crop_image",
        lambda image_bytes, bbox: b"cropped-img",
    )
    monkeypatch.setattr(
        analysis_task_module.yolo_worker,
        "mask_image",
        lambda image_bytes, bbox: b"masked-img",
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_parallel",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            analysis_task_module.OCRServiceError("parallel down")
        ),
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_full_text",
        lambda image_bytes: (
            full_text_calls.append(image_bytes)
            or OCRTextResult(
                raw_text="salt, sugar",
                lines=[{"text": "salt, sugar"}],
                blocks=[],
                artifact_json_url="https://example.com/ocr.json",
            )
        ),
    )
    monkeypatch.setattr(
        analysis_task_module.ocr_worker,
        "recognize_nutrition_table",
        lambda image_bytes: (
            table_calls.append(image_bytes)
            or TableRecognitionResult(
                table_json={
                    "rows": [
                        ["item", "per100g"],
                        ["energy", "120kJ"],
                    ]
                },
                ocr_fallback_text="energy 120kJ 2%",
            )
        ),
    )
    monkeypatch.setattr(
        analysis_task_module.nutrition_extractor,
        "parse",
        lambda table_result, ocr_fallback_text=None: {
            "items": [],
            "parse_method": "table_recognition",
        },
    )
    monkeypatch.setattr(
        analysis_task_module.ingredient_extractor,
        "extract",
        lambda full_raw_text: (["salt", "sugar"], "salt, sugar"),
    )
    monkeypatch.setattr(
        analysis_task_module.rag_worker,
        "retrieve_all",
        lambda ingredient_terms, ingredients_text: {
            "source_file": "chromadb",
            "ingredients_text": ingredients_text,
            "items_total": 0,
            "retrieval_results": [],
        },
    )
    monkeypatch.setattr(
        analysis_task_module.llm_worker,
        "analyze",
        lambda other_ocr_raw_text, nutrition_json, rag_results_json: {
            "score": 88,
            "summary": "S" * 60,
            "top_risks": ["salt"],
            "ingredients": [],
            "health_advice": _health_advice_payload(),
        },
    )
    monkeypatch.setattr(
        analysis_task_module,
        "_persist_analysis_artifacts",
        lambda **kwargs: {"ocr_full_json_url": "https://example.com/ocr.json"},
    )
    monkeypatch.setattr(
        analysis_task_module,
        "_complete_task_with_report",
        lambda **kwargs: completions.append(kwargs),
    )

    analysis_task_module.process_image_task.push_request(id="celery-1", retries=0)
    try:
        result = analysis_task_module.process_image_task.run(
            "task-id", "image-key", str(uuid.uuid4())
        )
    finally:
        analysis_task_module.process_image_task.pop_request()

    assert result["status"] == "completed"
    assert full_text_calls == [b"masked-img"]
    assert table_calls == [b"cropped-img"]
    assert completions[0]["nutrition_json"]["parse_method"] == "table_recognition"
