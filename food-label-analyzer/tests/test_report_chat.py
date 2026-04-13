from __future__ import annotations

import asyncio
import importlib
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.error_handlers import register_exception_handlers
from app.models.report import Report
from app.models.report_conversation import ReportConversation
from app.models.user import User
from tests.conftest import load_required_env


def _build_report_chat_app(monkeypatch):
    load_required_env(monkeypatch)
    api_module = importlib.reload(importlib.import_module("app.api.v1.report_chat"))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_module.router, prefix="/reports")
    return app, api_module


def test_report_chat_router_endpoints(monkeypatch) -> None:
    app, api_module = _build_report_chat_app(monkeypatch)
    schema_module = importlib.reload(importlib.import_module("app.schemas.report_chat"))

    current_user = User(
        email="user@example.com",
        password_hash="hashed",
        is_verified=True,
        is_active=True,
    )
    current_user.id = uuid.uuid4()
    fake_db = AsyncMock()
    fake_db.add = Mock()

    async def fake_refresh(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    fake_db.refresh = AsyncMock(side_effect=fake_refresh)
    fake_db.add = Mock()

    async def fake_refresh(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    fake_db.refresh = AsyncMock(side_effect=fake_refresh)
    fake_db.add = Mock()

    async def fake_refresh(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    fake_db.refresh = AsyncMock(side_effect=fake_refresh)
    report_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()

    async def override_db():
        yield fake_db

    async def override_user():
        return current_user

    async def fake_get_report_conversation(report_id_value, user_id, db):
        assert report_id_value == report_id
        assert user_id == current_user.id
        return schema_module.ReportConversationResponse(
            conversation_id=conversation_id,
            report_id=report_id_value,
            suggested_questions=["这款食品适合高血压人群吗？"],
            messages=[
                schema_module.ReportConversationMessageSchema(
                    message_id=message_id,
                    role="assistant",
                    content="这份报告提示钠含量偏高。",
                    created_at=datetime.now(timezone.utc),
                )
            ],
        )

    async def fake_get_or_generate_suggestions(report_id_value, user_id, db):
        assert report_id_value == report_id
        assert user_id == current_user.id
        return schema_module.ReportChatSuggestionsResponse(
            suggested_questions=[
                "这份报告里最值得关注的风险是什么？",
                "这款食品适合高血压人群吗？",
            ]
        )

    async def fake_stream_report_chat(report_id_value, user_id, message, db):
        assert report_id_value == report_id
        assert user_id == current_user.id
        assert message == "这款食品适合高血压人群吗？"

        async def stream():
            yield (
                f"event: meta\ndata: {json.dumps({'conversation_id': str(conversation_id), 'user_message_id': str(message_id)})}\n\n"
            )
            yield 'event: delta\ndata: {"text": "钠含量偏高，"}\n\n'
            yield (
                f'event: done\ndata: {json.dumps({"message_id": str(uuid.uuid4()), "role": "assistant", "content": "钠含量偏高，建议控制摄入。", "created_at": "2026-04-12T00:00:00Z"}, ensure_ascii=False)}\n\n'
            )

        return stream()

    app.dependency_overrides[api_module.get_db] = override_db
    app.dependency_overrides[api_module.get_current_user] = override_user
    monkeypatch.setattr(api_module, "get_report_conversation", fake_get_report_conversation)
    monkeypatch.setattr(
        api_module,
        "get_or_generate_suggestions",
        fake_get_or_generate_suggestions,
    )
    monkeypatch.setattr(api_module, "stream_report_chat", fake_stream_report_chat)

    with TestClient(app) as client:
        conversation_response = client.get(f"/reports/{report_id}/chat")
        suggestions_response = client.post(f"/reports/{report_id}/chat/suggestions")
        stream_response = client.post(
            f"/reports/{report_id}/chat/stream",
            json={"message": "这款食品适合高血压人群吗？"},
        )

    assert conversation_response.status_code == 200
    assert (
        conversation_response.json()["data"]["suggested_questions"][0]
        == "这款食品适合高血压人群吗？"
    )
    assert suggestions_response.status_code == 200
    assert len(suggestions_response.json()["data"]["suggested_questions"]) == 2
    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in stream_response.text
    assert "event: delta" in stream_response.text
    assert "event: done" in stream_response.text


def test_report_chat_router_returns_null_when_conversation_missing(monkeypatch) -> None:
    app, api_module = _build_report_chat_app(monkeypatch)

    current_user = User(
        email="user@example.com",
        password_hash="hashed",
        is_verified=True,
        is_active=True,
    )
    current_user.id = uuid.uuid4()
    fake_db = AsyncMock()

    async def override_db():
        yield fake_db

    async def override_user():
        return current_user

    async def fake_get_report_conversation(report_id_value, user_id, db):
        assert report_id_value is not None
        assert user_id == current_user.id
        return None

    app.dependency_overrides[api_module.get_db] = override_db
    app.dependency_overrides[api_module.get_current_user] = override_user
    monkeypatch.setattr(api_module, "get_report_conversation", fake_get_report_conversation)

    with TestClient(app) as client:
        response = client.get(f"/reports/{uuid.uuid4()}/chat")

    assert response.status_code == 200
    assert response.json()["data"] is None


def test_report_chat_service_uses_cached_suggestions(monkeypatch) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.report_chat_service")
    )

    report_id = uuid.uuid4()
    user_id = uuid.uuid4()
    report = Report(
        task_id=uuid.uuid4(),
        user_id=user_id,
        llm_output_json={},
        score=80,
    )
    report.id = report_id
    report.created_at = datetime.now(timezone.utc)
    report.conversation = ReportConversation(
        report_id=report_id,
        user_id=user_id,
        suggested_questions=["问题一", "问题二"],
    )
    report.conversation.messages = []

    fake_db = AsyncMock()
    fake_db.add = Mock()

    async def fake_refresh(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    fake_db.refresh = AsyncMock(side_effect=fake_refresh)
    fake_db.add = Mock()

    async def fake_refresh(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    fake_db.refresh = AsyncMock(side_effect=fake_refresh)
    fake_db.add = Mock()

    async def fake_refresh(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    fake_db.refresh = AsyncMock(side_effect=fake_refresh)
    fake_db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: report)
    )

    async def should_not_run(*args, **kwargs):
        raise AssertionError("LLM should not be called when cache exists")

    monkeypatch.setattr(
        service_module, "generate_suggested_questions", should_not_run
    )

    result = asyncio.run(
        service_module.get_or_generate_suggestions(report_id, user_id, fake_db)
    )

    assert result.suggested_questions == ["问题一", "问题二"]


def test_report_chat_service_returns_null_conversation_without_creating(
    monkeypatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.report_chat_service")
    )

    report_id = uuid.uuid4()
    user_id = uuid.uuid4()
    report = Report(
        task_id=uuid.uuid4(),
        user_id=user_id,
        llm_output_json={},
        score=80,
    )
    report.id = report_id
    report.created_at = datetime.now(timezone.utc)
    report.conversation = None

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: report)
    )

    result = asyncio.run(
        service_module.get_report_conversation(report_id, user_id, fake_db)
    )

    assert result is None
    fake_db.add.assert_not_called()
    fake_db.commit.assert_not_awaited()


def test_report_chat_service_suggestions_do_not_create_conversation(monkeypatch) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.report_chat_service")
    )

    report_id = uuid.uuid4()
    user_id = uuid.uuid4()
    report = Report(
        task_id=uuid.uuid4(),
        user_id=user_id,
        ingredients_text="水、白砂糖、食用盐",
        nutrition_json=None,
        rag_results_json=None,
        llm_output_json={
            "score": 80,
            "summary": "这份食品整体风险中等。",
            "hazards": [],
            "benefits": [],
            "ingredients": [],
            "health_advice": [],
        },
        score=80,
    )
    report.id = report_id
    report.created_at = datetime.now(timezone.utc)
    report.conversation = None

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: report)
    )

    monkeypatch.setattr(service_module, "_get_preference", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service_module,
        "generate_suggested_questions",
        AsyncMock(return_value=["这份报告里最值得关注的风险是什么？"]),
    )

    result = asyncio.run(
        service_module.get_or_generate_suggestions(report_id, user_id, fake_db)
    )

    assert result.suggested_questions == ["这份报告里最值得关注的风险是什么？"]
    fake_db.add.assert_not_called()
    fake_db.commit.assert_not_awaited()


def test_report_chat_service_stream_persists_user_and_assistant_messages(
    monkeypatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.report_chat_service")
    )

    report_id = uuid.uuid4()
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    report = Report(
        task_id=uuid.uuid4(),
        user_id=user_id,
        ingredients_text="水、白砂糖、食用盐",
        nutrition_json=None,
        rag_results_json=None,
        llm_output_json={
            "score": 80,
            "summary": "这份食品整体风险中等。",
            "hazards": [],
            "benefits": [],
            "ingredients": [],
            "health_advice": [],
        },
        score=80,
    )
    report.id = report_id
    report.created_at = datetime.now(timezone.utc)
    conversation = ReportConversation(
        report_id=report_id,
        user_id=user_id,
        suggested_questions=[],
    )
    conversation.id = conversation_id
    conversation.messages = []

    fake_db = AsyncMock()
    fake_db.add = Mock()

    async def fake_refresh(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    fake_db.refresh = AsyncMock(side_effect=fake_refresh)

    async def fake_stream_answer(**kwargs):
        yield "这份食品"
        yield "钠含量偏高。"

    monkeypatch.setattr(service_module, "_get_owned_report", AsyncMock(return_value=report))
    monkeypatch.setattr(
        service_module,
        "_get_or_create_conversation_for_write",
        AsyncMock(return_value=(conversation, False)),
    )
    monkeypatch.setattr(
        service_module,
        "_load_recent_history",
        AsyncMock(return_value=[{"role": "assistant", "content": "历史回答"}]),
    )
    monkeypatch.setattr(service_module, "_get_preference", AsyncMock(return_value=None))
    monkeypatch.setattr(service_module, "stream_report_answer", fake_stream_answer)

    async def collect_events():
        stream = await service_module.stream_report_chat(
            report_id,
            user_id,
            "这款食品适合高血压人群吗？",
            fake_db,
        )
        payload: list[str] = []
        async for item in stream:
            payload.append(item)
        return payload

    events = asyncio.run(collect_events())

    assert any("event: meta" in item for item in events)
    assert any("event: delta" in item for item in events)
    assert any("event: done" in item for item in events)
    assert fake_db.add.call_count == 2
    assert fake_db.commit.await_count >= 2


def test_report_chat_service_stream_does_not_persist_assistant_on_failure(
    monkeypatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.report_chat_service")
    )

    report_id = uuid.uuid4()
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    report = Report(
        task_id=uuid.uuid4(),
        user_id=user_id,
        ingredients_text="水、白砂糖、食用盐",
        nutrition_json=None,
        rag_results_json=None,
        llm_output_json={
            "score": 80,
            "summary": "这份食品整体风险中等。",
            "hazards": [],
            "benefits": [],
            "ingredients": [],
            "health_advice": [],
        },
        score=80,
    )
    report.id = report_id
    report.created_at = datetime.now(timezone.utc)
    conversation = ReportConversation(
        report_id=report_id,
        user_id=user_id,
        suggested_questions=[],
    )
    conversation.id = conversation_id
    conversation.messages = []

    fake_db = AsyncMock()
    fake_db.add = Mock()

    async def fake_refresh(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    fake_db.refresh = AsyncMock(side_effect=fake_refresh)

    async def fake_stream_answer(**kwargs):
        yield "部分回答"
        raise RuntimeError("boom")

    monkeypatch.setattr(service_module, "_get_owned_report", AsyncMock(return_value=report))
    monkeypatch.setattr(
        service_module,
        "_get_or_create_conversation_for_write",
        AsyncMock(return_value=(conversation, False)),
    )
    monkeypatch.setattr(
        service_module,
        "_load_recent_history",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(service_module, "_get_preference", AsyncMock(return_value=None))
    monkeypatch.setattr(service_module, "stream_report_answer", fake_stream_answer)

    async def collect_events():
        stream = await service_module.stream_report_chat(
            report_id,
            user_id,
            "这款食品适合高血压人群吗？",
            fake_db,
        )
        payload: list[str] = []
        async for item in stream:
            payload.append(item)
        return payload

    events = asyncio.run(collect_events())

    assert any("event: error" in item for item in events)
    assert fake_db.add.call_count == 1
    fake_db.rollback.assert_awaited()
