from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import structlog
from sqlalchemy import delete, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import LLMServiceError, ReportNotFoundError, ValidationException
from app.models.report import Report
from app.models.report_conversation import ReportConversation
from app.models.report_conversation_message import ReportConversationMessage
from app.models.user_preference import UserPreference
from app.schemas.analysis_data import NutritionData
from app.schemas.common import serialize_datetime_to_z
from app.schemas.report_chat import (
    ReportConversationMessageSchema,
    ReportConversationResponse,
    ReportChatSuggestionsResponse,
)
from app.services.report_service import (
    _build_analysis,
    _build_nutrition_table,
    _build_rag_summary,
    _format_nutrition,
    _safe_validate,
    _sanitize_ingredients_text,
)
from app.workers.report_chat_worker import (
    generate_suggested_questions,
    stream_report_answer,
)

logger = structlog.get_logger(__name__)


def _normalize_suggested_questions(value: list[str], limit: int) -> list[str]:
    normalized: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized[:limit]


def _build_message_schema(
    message: ReportConversationMessage,
) -> ReportConversationMessageSchema:
    return ReportConversationMessageSchema(
        message_id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
    )


def _build_conversation_response(
    conversation: ReportConversation,
) -> ReportConversationResponse:
    return ReportConversationResponse(
        conversation_id=conversation.id,
        report_id=conversation.report_id,
        suggested_questions=list(conversation.suggested_questions or []),
        messages=[_build_message_schema(item) for item in conversation.messages],
    )


def _build_preference_context(
    preference: UserPreference | None,
) -> dict[str, list[str]]:
    if preference is None:
        return {
            "focus_groups": [],
            "health_conditions": [],
            "allergies": [],
        }
    return {
        "focus_groups": list(preference.focus_groups or []),
        "health_conditions": list(preference.health_conditions or []),
        "allergies": list(preference.allergies or []),
    }


def _build_report_context(report: Report) -> dict[str, Any]:
    validated_nutrition = _safe_validate(NutritionData, report.nutrition_json)
    analysis = _build_analysis(report.llm_output_json, report.score)
    rag_summary = _build_rag_summary(
        report.rag_results_json,
        final_ingredient_count=len(analysis.ingredients),
    )
    nutrition_table = _build_nutrition_table(validated_nutrition)
    return {
        "report_id": str(report.id),
        "ingredients_text": _sanitize_ingredients_text(report.ingredients_text),
        "nutrition": _format_nutrition(validated_nutrition),
        "nutrition_table": (
            nutrition_table.model_dump(mode="json") if nutrition_table else None
        ),
        "analysis": analysis.model_dump(mode="json"),
        "rag_summary": rag_summary.model_dump(mode="json"),
        "created_at": serialize_datetime_to_z(report.created_at),
    }


def _build_fallback_suggestions(
    report: Report,
    preference_context: dict[str, list[str]],
) -> list[str]:
    analysis = _build_analysis(report.llm_output_json, report.score)
    suggestions: list[str] = []
    if analysis.hazards:
        suggestions.append(f"这份报告里最需要注意的风险是什么？")
    if preference_context["health_conditions"]:
        focus = preference_context["health_conditions"][0]
        suggestions.append(f"这款食品适合有{focus}的人群吗？")
    if preference_context["allergies"]:
        allergen = preference_context["allergies"][0]
        suggestions.append(f"这份报告里有没有和{allergen}相关的过敏风险？")
    if analysis.ingredients:
        suggestions.append(f"配料里最值得重点关注的是哪几项？")
    suggestions.append("这款食品更适合偶尔吃还是长期购买？")
    return _normalize_suggested_questions(
        suggestions,
        get_settings().REPORT_CHAT_SUGGESTION_COUNT,
    )


async def _get_owned_report(
    report_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Report:
    result = await db.execute(
        select(Report)
        .where(
            Report.id == report_id,
            Report.user_id == user_id,
            Report.deleted_at.is_(None),
        )
        .options(
            selectinload(Report.conversation).selectinload(ReportConversation.messages)
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise ReportNotFoundError()
    return report


async def _get_preference(user_id: uuid.UUID, db: AsyncSession) -> UserPreference | None:
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _get_persisted_conversation(
    report_id: uuid.UUID,
    db: AsyncSession,
) -> ReportConversation | None:
    result = await db.execute(
        select(ReportConversation).where(ReportConversation.report_id == report_id)
    )
    return result.scalar_one_or_none()


async def _get_or_create_conversation_for_write(
    report: Report,
    db: AsyncSession,
) -> tuple[ReportConversation, bool]:
    if report.conversation is not None:
        return report.conversation, False

    conversation = ReportConversation(
        report_id=report.id,
        user_id=report.user_id,
        suggested_questions=[],
    )
    db.add(conversation)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await _get_persisted_conversation(report.id, db)
        if existing is None:
            raise
        return existing, False

    report.conversation = conversation
    return conversation, True


async def get_report_conversation(
    report_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> ReportConversationResponse | None:
    report = await _get_owned_report(report_id, user_id, db)
    conversation = report.conversation
    if conversation is None:
        return None

    if not conversation.messages:
        result = await db.execute(
            select(ReportConversationMessage)
            .where(ReportConversationMessage.conversation_id == conversation.id)
            .order_by(ReportConversationMessage.created_at.asc())
        )
        conversation.messages = list(result.scalars().all())
    return _build_conversation_response(conversation)


async def get_or_generate_suggestions(
    report_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> ReportChatSuggestionsResponse:
    report = await _get_owned_report(report_id, user_id, db)
    conversation = report.conversation
    if conversation is not None:
        existing = _normalize_suggested_questions(
            list(conversation.suggested_questions or []),
            get_settings().REPORT_CHAT_SUGGESTION_COUNT,
        )
        if existing:
            conversation.suggested_questions = existing
            return ReportChatSuggestionsResponse(suggested_questions=existing)

    preference = await _get_preference(user_id, db)
    preference_context = _build_preference_context(preference)
    report_context = _build_report_context(report)

    try:
        suggested_questions = await generate_suggested_questions(
            report_context,
            preference_context,
        )
        suggested_questions = _normalize_suggested_questions(
            suggested_questions,
            get_settings().REPORT_CHAT_SUGGESTION_COUNT,
        )
    except LLMServiceError:
        logger.warning("report_chat_suggestions_fallback", report_id=str(report_id))
        suggested_questions = _build_fallback_suggestions(report, preference_context)

    if conversation is not None:
        conversation.suggested_questions = suggested_questions
        conversation.updated_at = datetime.now(timezone.utc)
        await db.commit()
    return ReportChatSuggestionsResponse(suggested_questions=suggested_questions)


async def _load_recent_history(
    conversation_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict[str, str]]:
    limit = get_settings().REPORT_CHAT_HISTORY_WINDOW
    result = await db.execute(
        select(ReportConversationMessage)
        .where(ReportConversationMessage.conversation_id == conversation_id)
        .order_by(desc(ReportConversationMessage.created_at))
        .limit(limit)
    )
    messages = list(result.scalars().all())
    messages.reverse()
    return [{"role": item.role, "content": item.content} for item in messages]


def _encode_sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_report_chat(
    report_id: uuid.UUID,
    user_id: uuid.UUID,
    message: str,
    db: AsyncSession,
) -> AsyncIterator[str]:
    trimmed_message = message.strip()
    max_chars = get_settings().REPORT_CHAT_MAX_MESSAGE_CHARS
    if not trimmed_message:
        raise ValidationException(message="请输入问题内容")
    if len(trimmed_message) > max_chars:
        raise ValidationException(message=f"问题长度不能超过 {max_chars} 个字符")

    report = await _get_owned_report(report_id, user_id, db)
    preference = await _get_preference(user_id, db)
    report_context = _build_report_context(report)
    preference_context = _build_preference_context(preference)
    conversation, conversation_created = await _get_or_create_conversation_for_write(
        report, db
    )
    history = (
        [] if conversation_created else await _load_recent_history(conversation.id, db)
    )

    user_message = ReportConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=trimmed_message,
    )
    conversation.updated_at = datetime.now(timezone.utc)
    db.add(user_message)
    await db.flush()
    await db.commit()
    await db.refresh(user_message)

    async def event_stream() -> AsyncIterator[str]:
        yield _encode_sse_event(
            "meta",
            {
                "conversation_id": str(conversation.id),
                "user_message_id": str(user_message.id),
            },
        )

        assistant_chunks: list[str] = []
        try:
            async for chunk in stream_report_answer(
                report_context=report_context,
                preference_context=preference_context,
                conversation_history=history,
                question=trimmed_message,
            ):
                assistant_chunks.append(chunk)
                yield _encode_sse_event("delta", {"text": chunk})

            assistant_content = "".join(assistant_chunks).strip()
            if not assistant_content:
                raise LLMServiceError("Assistant response is empty")

            assistant_message = ReportConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=assistant_content,
            )
            conversation.updated_at = datetime.now(timezone.utc)
            db.add(assistant_message)
            await db.flush()
            await db.commit()
            await db.refresh(assistant_message)

            yield _encode_sse_event(
                "done",
                _build_message_schema(assistant_message).model_dump(mode="json"),
            )
        except Exception as exc:
            await db.rollback()
            logger.error(
                "report_chat_stream_failed",
                report_id=str(report_id),
                user_id=str(user_id),
                error=str(exc),
            )
            yield _encode_sse_event(
                "error",
                {
                    "message": (
                        "问答生成失败，请稍后重试"
                        if not isinstance(exc, ValidationException)
                        else exc.message
                    )
                },
            )

    return event_stream()


async def delete_report_conversation(
    report_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    await db.execute(
        delete(ReportConversation).where(ReportConversation.report_id == report_id)
    )


__all__ = [
    "delete_report_conversation",
    "get_or_generate_suggestions",
    "get_report_conversation",
    "stream_report_chat",
]
