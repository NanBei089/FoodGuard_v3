from __future__ import annotations

import json
from typing import Any, AsyncIterator

import structlog
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import LLMServiceError
from app.workers.extractor.prompts.report_chat import (
    SuggestedQuestionsOutput,
    build_report_chat_suggestions_prompt,
    build_report_chat_system_prompt,
    build_report_chat_user_prompt,
)

logger = structlog.get_logger(__name__)

_async_client: AsyncOpenAI | None = None


def _get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        settings = get_settings()
        _async_client = AsyncOpenAI(
            base_url=settings.DEEPSEEK_BASE_URL,
            api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
            timeout=settings.DEEPSEEK_TIMEOUT,
            max_retries=settings.DEEPSEEK_MAX_RETRIES,
        )
    return _async_client


def validate_configuration() -> None:
    settings = get_settings()
    if not settings.DEEPSEEK_BASE_URL.strip():
        raise LLMServiceError("DEEPSEEK_BASE_URL is required")
    if not settings.DEEPSEEK_MODEL.strip():
        raise LLMServiceError("DEEPSEEK_MODEL is required")
    if not settings.DEEPSEEK_API_KEY.get_secret_value().strip():
        raise LLMServiceError("DEEPSEEK_API_KEY is required")
    _get_async_client()


async def generate_suggested_questions(
    report_context: dict[str, Any],
    preference_context: dict[str, Any],
) -> list[str]:
    validate_configuration()
    settings = get_settings()
    prompt = build_report_chat_suggestions_prompt().format(
        report_context_json=json.dumps(report_context, ensure_ascii=False, indent=2),
        preference_context_json=json.dumps(
            preference_context, ensure_ascii=False, indent=2
        ),
        suggestion_count=settings.REPORT_CHAT_SUGGESTION_COUNT,
    )

    try:
        response = await _get_async_client().chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        raise LLMServiceError(f"Suggested questions generation failed: {exc}") from exc

    choices = getattr(response, "choices", None)
    if not choices:
        raise LLMServiceError("LLM response did not include any choices")
    content = getattr(choices[0].message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise LLMServiceError("LLM response content is empty")

    normalized_content = content.strip()
    if normalized_content.startswith("```json"):
        normalized_content = normalized_content[7:]
    elif normalized_content.startswith("```"):
        normalized_content = normalized_content[3:]
    if normalized_content.endswith("```"):
        normalized_content = normalized_content[:-3]

    try:
        payload = json.loads(normalized_content.strip())
        parsed = SuggestedQuestionsOutput.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMServiceError("Suggested questions parsing failed") from exc

    return parsed.questions[: settings.REPORT_CHAT_SUGGESTION_COUNT]


async def stream_report_answer(
    *,
    report_context: dict[str, Any],
    preference_context: dict[str, Any],
    conversation_history: list[dict[str, str]],
    question: str,
) -> AsyncIterator[str]:
    validate_configuration()
    settings = get_settings()

    user_prompt = build_report_chat_user_prompt().format(
        report_context_json=json.dumps(report_context, ensure_ascii=False, indent=2),
        preference_context_json=json.dumps(
            preference_context, ensure_ascii=False, indent=2
        ),
        conversation_history_json=json.dumps(
            conversation_history, ensure_ascii=False, indent=2
        ),
        question=question,
    )

    try:
        stream = await _get_async_client().chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            temperature=0.3,
            messages=[
                {"role": "system", "content": build_report_chat_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
        )
    except Exception as exc:
        raise LLMServiceError(f"Report chat stream failed: {exc}") from exc

    async for chunk in stream:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            continue
        content = getattr(delta, "content", None)
        if isinstance(content, str) and content:
            yield content


__all__ = [
    "generate_suggested_questions",
    "stream_report_answer",
    "validate_configuration",
]
