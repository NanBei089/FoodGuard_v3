from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from minio import Minio
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import (
    EmbeddingServiceError,
    LLMServiceError,
    OCRServiceError,
    StorageServiceError,
)
from app.db.session import get_sync_db
from app.models.analysis_task import AnalysisTask, TaskStatus
from app.models.report import Report
from app.schemas.analysis_data import (
    FoodHealthAnalysisOutput,
    NutritionData,
    RAGResults,
)
from app.services.storage_service import get_storage_service
from app.tasks.celery_app import celery_app
from app.workers import llm_worker, ocr_worker, rag_worker, yolo_worker
from app.workers.extractor import ingredient_extractor, nutrition_extractor
from app.workers.ocr_worker import OCRParallelResult, OCRTextResult, TableRecognitionResult

logger = structlog.get_logger(__name__)


def _to_plain_data(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, (dict, list, str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return {
            key: item for key, item in vars(value).items() if not key.startswith("_")
        }
    return value


def _extract_score(llm_output_json: dict[str, Any]) -> int:
    raw_score = llm_output_json.get("score", 0)
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


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
    except Exception as exc:
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


def _run_ocr_full_text(image_bytes: bytes) -> OCRTextResult:
    try:
        return ocr_worker.recognize_full_text(image_bytes)
    except NotImplementedError:
        raise
    except Exception as exc:
        raise OCRServiceError("OCR full-text recognition failed") from exc


def _run_ocr_table(image_bytes: bytes) -> TableRecognitionResult:
    try:
        return ocr_worker.recognize_nutrition_table(image_bytes)
    except NotImplementedError:
        raise
    except Exception as exc:
        raise OCRServiceError("Nutrition table recognition failed") from exc


def _run_ocr_parallel(
    full_text_image_bytes: bytes,
    nutrition_image_bytes: bytes,
) -> OCRParallelResult:
    try:
        return ocr_worker.recognize_parallel(
            full_text_image_bytes,
            nutrition_image_bytes=nutrition_image_bytes,
        )
    except NotImplementedError:
        raise
    except Exception as exc:
        raise OCRServiceError("Parallel OCR failed") from exc


def _run_ocr_with_bbox_fallback(
    *,
    task_id: str,
    image_bytes: bytes,
    masked_full_image: bytes,
    cropped_image: bytes,
) -> tuple[OCRTextResult, TableRecognitionResult | None]:
    try:
        parallel_result = _run_ocr_parallel(masked_full_image, cropped_image)
        return parallel_result.full_text, parallel_result.nutrition_table
    except OCRServiceError as exc:
        logger.warning(
            "parallel_ocr_fallback_to_sequential",
            task_id=task_id,
            error_message=str(exc),
        )

    full_text_result = _run_ocr_full_text(masked_full_image)
    try:
        table_result = _run_ocr_table(cropped_image)
    except OCRServiceError as exc:
        logger.warning(
            "nutrition_table_cropped_scan_failed",
            task_id=task_id,
            error_message=str(exc),
        )
        table_result = None

    if _table_result_is_incomplete(table_result):
        try:
            full_image_table_result = _run_ocr_table(image_bytes)
        except OCRServiceError as exc:
            logger.warning(
                "nutrition_table_full_image_fallback_failed",
                task_id=task_id,
                error_message=str(exc),
            )
        else:
            selected_table_result = _choose_better_table_result(
                table_result, full_image_table_result
            )
            if selected_table_result is not table_result:
                logger.info(
                    "nutrition_table_full_image_fallback_selected",
                    task_id=task_id,
                    cropped_quality=_table_result_quality(table_result),
                    full_image_quality=_table_result_quality(full_image_table_result),
                )
                table_result = selected_table_result

    return full_text_result, table_result


def _extract_table_rows(table_result: TableRecognitionResult | None) -> list[list[str]]:
    if table_result is None or not isinstance(table_result.table_json, dict):
        return []

    raw_rows = table_result.table_json.get("rows")
    if not isinstance(raw_rows, list):
        return []

    rows: list[list[str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        row = [str(cell).strip() for cell in raw_row if str(cell).strip()]
        if row:
            rows.append(row)
    return rows


def _table_result_quality(table_result: TableRecognitionResult | None) -> tuple[int, int, int, int]:
    rows = _extract_table_rows(table_result)
    numeric_value_cells = sum(
        1
        for row in rows
        for cell in row[1:]
        if any(char.isdigit() for char in cell)
    )
    multi_column_rows = sum(1 for row in rows if len(row) >= 2)
    fallback_text_len = (
        len((table_result.ocr_fallback_text or "").strip()) if table_result else 0
    )
    return (
        numeric_value_cells,
        multi_column_rows,
        len(rows),
        fallback_text_len,
    )


def _table_result_is_incomplete(table_result: TableRecognitionResult | None) -> bool:
    numeric_value_cells, multi_column_rows, row_count, _ = _table_result_quality(
        table_result
    )
    if row_count == 0:
        return True
    if multi_column_rows == 0:
        return True
    if numeric_value_cells == 0:
        return True
    return False


def _choose_better_table_result(
    primary: TableRecognitionResult | None,
    candidate: TableRecognitionResult | None,
) -> TableRecognitionResult | None:
    primary_quality = _table_result_quality(primary)
    candidate_quality = _table_result_quality(candidate)
    if candidate_quality > primary_quality:
        return candidate
    return primary


def _run_rag(ingredient_terms: list[str], ingredients_text: str) -> dict[str, Any]:
    try:
        return rag_worker.retrieve_all(ingredient_terms, ingredients_text)
    except NotImplementedError:
        raise
    except Exception as exc:
        raise EmbeddingServiceError("RAG retrieval failed") from exc


def _normalize_ingredient_term(term: str) -> str:
    return re.sub(r"\s+", "", str(term or "").strip().lower())


def _dedupe_ingredient_terms(ingredient_terms: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in ingredient_terms:
        normalized = _normalize_ingredient_term(term)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(str(term).strip())
    return deduped


def _build_rag_lookup(rag_results_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    retrieval_results = rag_results_json.get("retrieval_results")
    if not isinstance(retrieval_results, list):
        return lookup

    for item in retrieval_results:
        if not isinstance(item, dict):
            continue

        matches = item.get("matches")
        first_match = matches[0] if isinstance(matches, list) and matches else None
        function_category = None
        if isinstance(first_match, dict):
            raw_category = first_match.get("function_category")
            if isinstance(raw_category, str) and raw_category.strip():
                function_category = raw_category.strip()

        payload = {
            "function_category": function_category,
            "retrieved": bool(item.get("retrieved")),
        }
        for raw_key in (item.get("raw_term"), item.get("normalized_term")):
            normalized = _normalize_ingredient_term(str(raw_key or ""))
            if normalized and normalized not in lookup:
                lookup[normalized] = payload
    return lookup




_COMMON_INGREDIENT_INFO: dict[str, tuple[str, str | None]] = {
    "水": ("食品加工中的基础溶剂和调配介质，本身风险较低，主要影响产品形态与口感。", None),
    "饮用水": ("常见食品基底原料，用于溶解和调配其他成分，本身通常不构成额外健康负担。", None),
    "食用盐": ("提供咸味的基础调味料，过量摄入可能增加钠负担和高血压风险，需控制总摄入量。", None),
    "白砂糖": ("精制蔗糖，主要提供甜味和能量，长期过量摄入可能增加肥胖和龋齿风险。", None),
    "蔗糖": ("常用甜味来源，可改善风味和组织状态，但过量摄入会增加糖负担。", None),
    "葡萄糖": ("易吸收的单糖，常用于调味和补充能量，血糖管理人群需关注摄入量。", None),
    "果葡糖浆": ("常见甜味配料，可改善口感与保湿性，过量摄入会提高额外糖摄入风险。", None),
    "食用植物油": ("提供脂肪酸和能量的常见油脂原料，应结合总脂肪和脂肪酸类型综合评估。", None),
    "小麦粉": ("面制品常见基础原料，主要提供碳水化合物，麸质敏感或过敏人群需特别留意。", None),
    "大豆": ("优质植物蛋白来源，也属于常见过敏原之一，对大豆敏感者应避免食用。", None),
    "牛奶": ("提供蛋白质和钙的常见乳原料，但属于常见过敏原，乳糖不耐受者也需注意。", None),
    "乳粉": ("浓缩乳制品原料，可提升乳香和蛋白质含量，乳制品过敏者应谨慎。", None),
    "鸡蛋": ("优质蛋白来源，常用于改善口感和结构，也是常见过敏原之一。", None),
    "麦芽糊精": ("常用于增稠、赋形或改善口感，升糖较快，控糖人群需关注摄入量。", "增稠剂"),
    "香精": ("用于增强或模拟风味的食品用香料制品，建议结合摄入频率和人群敏感性综合判断。", "食用香精"),
    "食用香精": ("用于增强或调整风味的食品添加剂，通常用量不高，但儿童和敏感人群不宜长期高频摄入。", "食用香精"),
}


def _infer_fallback_risk(term: str) -> str:
    lowered = _normalize_ingredient_term(term)
    if any(keyword in lowered for keyword in ("氢化", "反式", "植脂末")):
        return "danger"
    if any(
        keyword in lowered
        for keyword in (
            "糖",
            "盐",
            "钠",
            "油",
            "脂",
            "黄油",
            "奶油",
            "香精",
            "香料",
            "色素",
            "防腐",
            "甜味剂",
            "乳化",
            "增稠",
        )
    ):
        return "warning"
    return "safe"


def _build_fallback_ingredient_item(
    term: str,
    rag_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    function_category = None
    if isinstance(rag_meta, dict):
        raw_category = rag_meta.get("function_category")
        if isinstance(raw_category, str) and raw_category.strip():
            function_category = raw_category.strip()

    normalized = _normalize_ingredient_term(term)
    common_info = _COMMON_INGREDIENT_INFO.get(normalized)
    if common_info is not None:
        description, default_category = common_info
        return {
            "name": term,
            "risk": _infer_fallback_risk(term),
            "description": description,
            "function_category": function_category or default_category,
            "rules": [],
        }

    risk = _infer_fallback_risk(term)
    if risk == "danger":
        description = (
            f"{term}属于需要重点关注的加工配料，可能带来较高代谢或心血管负担，建议控制摄入频率和总量。"
        )
    elif risk == "warning":
        description = (
            f"{term}在食品中多用于调味、改善口感或稳定性，建议结合配料排序和整体营养负担综合判断。"
        )
    else:
        description = (
            f"{term}常见于食品配方中，当前未见明显高风险信号，但仍应结合食用场景和个人体质综合评估。"
        )

    return {
        "name": term,
        "risk": risk,
        "description": description,
        "function_category": function_category,
        "rules": [],
    }


def _ensure_ingredient_coverage(
    llm_output_json: dict[str, Any],
    ingredient_terms: list[str],
    rag_results_json: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(llm_output_json, dict):
        return {}

    expected_terms = _dedupe_ingredient_terms(ingredient_terms)
    if not expected_terms:
        return llm_output_json

    raw_items = llm_output_json.get("ingredients")
    current_items = raw_items if isinstance(raw_items, list) else []
    covered_terms: set[str] = set()
    normalized_items: list[dict[str, Any]] = []

    for item in current_items:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        normalized = _normalize_ingredient_term(raw_name)
        if not normalized or normalized in covered_terms:
            continue
        covered_terms.add(normalized)
        normalized_items.append(item)

    rag_lookup = _build_rag_lookup(rag_results_json)
    for term in expected_terms:
        normalized = _normalize_ingredient_term(term)
        if normalized in covered_terms:
            continue
        normalized_items.append(
            _build_fallback_ingredient_item(term, rag_lookup.get(normalized))
        )
        covered_terms.add(normalized)

    llm_output_json["ingredients"] = normalized_items
    return llm_output_json


def _run_llm(
    full_text: str,
    nutrition_json: dict[str, Any],
    rag_results_json: dict[str, Any],
    ingredient_terms: list[str],
    ingredients_text: str,
) -> dict[str, Any]:
    try:
        return llm_worker.analyze(
            full_text,
            nutrition_json,
            rag_results_json,
            recognized_ingredient_terms=ingredient_terms,
            ingredients_text=ingredients_text,
        )
    except TypeError as exc:
        if (
            "recognized_ingredient_terms" not in str(exc)
            and "ingredients_text" not in str(exc)
        ):
            raise LLMServiceError("LLM analysis failed") from exc
        return llm_worker.analyze(full_text, nutrition_json, rag_results_json)
    except NotImplementedError:
        raise
    except Exception as exc:
        raise LLMServiceError("LLM analysis failed") from exc


@celery_app.task(
    bind=True,
    name="analysis.process_image",
    max_retries=2,
    soft_time_limit=270,
    time_limit=300,
)
def process_image_task(
    self, task_id: str, image_key: str, user_id: str
) -> dict[str, Any]:
    started_at = perf_counter()
    logger.info(
        "analysis_task_started",
        task_id=task_id,
        image_key=image_key,
        user_id=user_id,
        celery_task_id=self.request.id,
    )
    _update_task_status(task_id, TaskStatus.PROCESSING)
    timings: dict[str, int] = {}

    try:
        step_started = perf_counter()
        image_bytes = _download_image(image_key)
        timings["download_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        bbox = yolo_worker.detect(image_bytes)
        cropped_image = (
            yolo_worker.crop_image(image_bytes, bbox) if bbox else image_bytes
        )
        masked_full_image = (
            yolo_worker.mask_image(image_bytes, bbox) if bbox else image_bytes
        )
        timings["yolo_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        if bbox:
            full_text_result, table_result = _run_ocr_with_bbox_fallback(
                task_id=task_id,
                image_bytes=image_bytes,
                masked_full_image=masked_full_image,
                cropped_image=cropped_image,
            )
        else:
            full_text_result = _run_ocr_full_text(image_bytes)
            try:
                table_result = _run_ocr_table(image_bytes)
            except OCRServiceError as exc:
                logger.warning(
                    "nutrition_table_full_image_scan_failed",
                    task_id=task_id,
                    error_message=str(exc),
                )
                table_result = None
        full_text = full_text_result.raw_text
        timings["ocr_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        nutrition_output = nutrition_extractor.parse(
            table_result.model_dump() if table_result else None,
            (
                table_result.ocr_fallback_text
                if table_result and table_result.ocr_fallback_text
                else full_text or None
            ),
        )
        nutrition_json = _to_plain_data(nutrition_output) or {}
        if not isinstance(nutrition_json, dict):
            nutrition_json = {}
        timings["nutrition_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        ingredient_terms, ingredients_text = ingredient_extractor.extract(full_text)
        timings["ingredients_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        rag_output = _run_rag(ingredient_terms, ingredients_text)
        rag_results_json = _to_plain_data(rag_output) or {}
        if not isinstance(rag_results_json, dict):
            rag_results_json = {}
        timings["rag_ms"] = int((perf_counter() - step_started) * 1000)

        step_started = perf_counter()
        llm_output = _run_llm(
            full_text,
            nutrition_json,
            rag_results_json,
            ingredient_terms,
            ingredients_text,
        )
        llm_output_json = _to_plain_data(llm_output) or {}
        if not isinstance(llm_output_json, dict):
            llm_output_json = {}
        llm_output_json = _ensure_ingredient_coverage(
            llm_output_json,
            ingredient_terms,
            rag_results_json,
        )
        score = _extract_score(llm_output_json)
        timings["llm_ms"] = int((perf_counter() - step_started) * 1000)

        _complete_task_with_report(
            task_id=task_id,
            user_id=user_id,
            ingredients_text=ingredients_text,
            nutrition_json=nutrition_json,
            rag_results_json=rag_results_json,
            llm_output_json=llm_output_json,
            score=score,
            artifact_urls=_persist_analysis_artifacts(
                task_id=task_id,
                user_id=user_id,
                source_image_key=image_key,
                bbox=bbox,
                masked_full_image=masked_full_image if bbox else None,
                cropped_image=cropped_image if bbox else None,
                full_text_result=full_text_result,
                table_result=table_result,
                nutrition_json=nutrition_json,
                rag_results_json=rag_results_json,
                llm_output_json=llm_output_json,
            ),
        )
        total_elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "analysis_task_completed",
            task_id=task_id,
            total_elapsed_ms=total_elapsed_ms,
            timings=timings,
        )
        return {
            "task_id": task_id,
            "status": TaskStatus.COMPLETED.value,
            "total_elapsed_ms": total_elapsed_ms,
        }
    except SoftTimeLimitExceeded:
        error_message = "Analysis timeout"
        _update_task_status(task_id, TaskStatus.FAILED, error_message)
        logger.warning("analysis_task_timeout", task_id=task_id, timings=timings)
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except (
        OCRServiceError,
        LLMServiceError,
        StorageServiceError,
        EmbeddingServiceError,
    ) as exc:
        if self.request.retries < self.max_retries:
            logger.warning(
                "analysis_task_retrying",
                task_id=task_id,
                retries=self.request.retries,
                exception_type=exc.__class__.__name__,
                exception_message=str(exc),
            )
            raise self.retry(exc=exc, countdown=10)
        _update_task_status(task_id, TaskStatus.FAILED, str(exc))
        logger.warning(
            "analysis_task_failed_after_retries",
            task_id=task_id,
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except NotImplementedError as exc:
        _update_task_status(task_id, TaskStatus.FAILED, str(exc))
        logger.warning(
            "analysis_task_not_implemented", task_id=task_id, error_message=str(exc)
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}
    except Exception as exc:
        _update_task_status(task_id, TaskStatus.FAILED, str(exc))
        logger.error(
            "analysis_task_failed",
            task_id=task_id,
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
            exc_info=exc,
        )
        return {"task_id": task_id, "status": TaskStatus.FAILED.value}


__all__ = ["process_image_task"]
