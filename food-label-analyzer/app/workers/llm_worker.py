"""大模型分析模块，负责把 OCR、营养和 RAG 数据整理成健康分析 JSON。"""


from __future__ import annotations

import json
import threading
import time
from typing import Any

import structlog
from openai import OpenAI
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import LLMServiceError
from app.workers.extractor.prompts.food_health_analysis import (
    FoodHealthAnalysisOutput,
    build_food_health_analysis_prompt,
    build_food_health_analysis_repair_prompt,
)

logger = structlog.get_logger(__name__)

_client: OpenAI | None = None
_client_lock = threading.Lock()


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                settings = get_settings()
                _client = OpenAI(
                    base_url=settings.DEEPSEEK_BASE_URL,
                    api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
                    timeout=settings.DEEPSEEK_TIMEOUT,
                    max_retries=settings.DEEPSEEK_MAX_RETRIES,
                )
    return _client


def validate_configuration() -> None:
    settings = get_settings()
    if not settings.DEEPSEEK_BASE_URL.strip():
        raise LLMServiceError("DEEPSEEK_BASE_URL is required")
    if not settings.DEEPSEEK_MODEL.strip():
        raise LLMServiceError("DEEPSEEK_MODEL is required")
    if not settings.DEEPSEEK_API_KEY.get_secret_value().strip():
        raise LLMServiceError("DEEPSEEK_API_KEY is required")
    _get_client()


def _validate_output(payload: dict[str, Any]) -> FoodHealthAnalysisOutput:
    return FoodHealthAnalysisOutput.model_validate(payload)


def _extract_json_content(content: str) -> str:
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def _extract_stream_delta(chunk: Any) -> tuple[str, str | None]:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return "", None

    choice = choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    delta = getattr(choice, "delta", None)
    if delta is None:
        return "", finish_reason

    content = getattr(delta, "content", None)
    if isinstance(content, str) and content:
        return content, finish_reason
    return "", finish_reason


def _collect_stream_content(stream: Any, *, operation: str) -> str:
    started_at = time.time()
    first_delta_ms: int | None = None
    finish_reason: str | None = None
    chunks: list[str] = []

    try:
        for chunk in stream:
            delta, chunk_finish_reason = _extract_stream_delta(chunk)
            if chunk_finish_reason:
                finish_reason = str(chunk_finish_reason)
            if not delta:
                continue
            if first_delta_ms is None:
                first_delta_ms = int((time.time() - started_at) * 1000)
            chunks.append(delta)
    except Exception as exc:
        logger.error(
            "llm_stream_failed",
            operation=operation,
            partial_response=bool(chunks),
            chunks=len(chunks),
            chars=sum(len(item) for item in chunks),
            error=str(exc),
        )
        raise LLMServiceError(f"LLM stream failed during {operation}") from exc

    content = "".join(chunks)
    elapsed_ms = int((time.time() - started_at) * 1000)
    logger.info(
        "llm_stream_completed",
        operation=operation,
        elapsed_ms=elapsed_ms,
        first_delta_ms=first_delta_ms,
        chunks=len(chunks),
        chars=len(content),
        finish_reason=finish_reason,
    )
    if not content.strip():
        raise LLMServiceError("LLM response content is empty")
    return _extract_json_content(content)


def _serialize_inputs(
    other_ocr_raw_text: str,
    nutrition_json: dict[str, Any],
    rag_results_json: dict[str, Any],
    ingredient_terms: list[str] | None = None,
) -> dict[str, Any]:
    terms = [
        term.strip()
        for term in (ingredient_terms or [])
        if isinstance(term, str) and term.strip()
    ]
    if not terms:
        retrieval_results = rag_results_json.get("retrieval_results", [])
        if isinstance(retrieval_results, list):
            for item in retrieval_results:
                if not isinstance(item, dict):
                    continue
                raw_term = item.get("raw_term")
                if isinstance(raw_term, str) and raw_term.strip():
                    terms.append(raw_term.strip())

    return {
        "other_ocr_raw_text": other_ocr_raw_text or "（无 OCR 文本）",
        "nutrition_json": json.dumps(nutrition_json, ensure_ascii=False, indent=2),
        "rag_results_json": json.dumps(rag_results_json, ensure_ascii=False, indent=2),
        "ingredient_terms_json": json.dumps(terms, ensure_ascii=False, indent=2),
        "ingredient_count": len(terms),
    }


def analyze(
    other_ocr_raw_text: str,
    nutrition_json: dict,
    rag_results_json: dict,
    rule_based_score: int | None = None,
    recognized_ingredient_terms: list[str] | None = None,
    ingredients_text: str | None = None,
) -> dict[str, Any]:
    """调用大模型生成健康分析报告。"""
    validate_configuration()
    settings = get_settings()
    client = _get_client()
    prompt = build_food_health_analysis_prompt()
    inputs = _serialize_inputs(
        other_ocr_raw_text,
        nutrition_json,
        rag_results_json,
        ingredient_terms=recognized_ingredient_terms,
    )

    score_hint = (
        f"\n\n【强制要求】健康评分必须使用规则计算分数 {rule_based_score}，不得自行计算。"
        if rule_based_score is not None
        else ""
    )
    prompt_with_hint = prompt + score_hint

    start = time.time()
    content = ""
    logger.info("llm_call_started", model=settings.DEEPSEEK_MODEL)
    try:
        stream = client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            temperature=settings.DEEPSEEK_TEMPERATURE,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt_with_hint.format(**inputs)},
            ],
            stream=True,
        )
        content = _collect_stream_content(stream, operation="analysis")
        payload = json.loads(content)
        result = _validate_output(payload)
        elapsed_ms = int((time.time() - start) * 1000)
        logger.info("llm_call_success", elapsed_ms=elapsed_ms, score=result.score)
        return result.model_dump()
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("llm_output_parse_failed", error=str(exc)[:200])
        return _repair(inputs, str(exc), content, retry_count=0)
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.error("llm_call_failed", elapsed_ms=elapsed_ms, error=str(exc))
        if isinstance(exc, LLMServiceError):
            raise
        raise LLMServiceError(f"LLM call failed: {exc}") from exc


def _repair(
    original_inputs: dict[str, Any],
    validation_errors: str,
    previous_output: str,
    retry_count: int,
) -> dict[str, Any]:
    settings = get_settings()
    max_repair = settings.DEEPSEEK_MAX_RETRIES
    if retry_count >= max_repair:
        logger.error(
            "llm_repair_exhausted",
            retry_count=retry_count,
            errors=validation_errors[:500],
            last_output=previous_output[:500],
        )
        raise LLMServiceError("LLM output repair failed after maximum retries")

    logger.warning(
        "llm_repair_triggered", retry=retry_count + 1, errors=validation_errors[:200]
    )
    repair_prompt = build_food_health_analysis_repair_prompt()
    repair_inputs = {
        **original_inputs,
        "validation_errors": validation_errors,
        "previous_output_json": previous_output or "{}",
    }

    start = time.time()
    content = ""
    try:
        stream = _get_client().chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": repair_prompt.format(**repair_inputs)},
            ],
            stream=True,
        )
        content = _collect_stream_content(stream, operation="repair")
        payload = json.loads(content)
        result = _validate_output(payload)
        elapsed_ms = int((time.time() - start) * 1000)
        logger.info("llm_repair_success", retry=retry_count + 1, elapsed_ms=elapsed_ms)
        return result.model_dump()
    except (json.JSONDecodeError, ValidationError) as exc:
        return _repair(original_inputs, str(exc), content, retry_count + 1)
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.error(
            "llm_repair_call_failed",
            retry=retry_count + 1,
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )
        if isinstance(exc, LLMServiceError):
            raise
        raise LLMServiceError(f"LLM repair call failed: {exc}") from exc


__all__ = ["analyze", "validate_configuration"]
