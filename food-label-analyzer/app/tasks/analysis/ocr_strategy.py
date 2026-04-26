"""Celery 异步任务和分析流程编排。"""


from __future__ import annotations

from typing import Any

import structlog

from app.core.errors import OCRServiceError
from app.core.metrics import record_external_dependency_error
from app.workers import ocr_worker
from app.workers.ocr_worker import OCRParallelResult, OCRTextResult, TableRecognitionResult

logger = structlog.get_logger(__name__)


def _run_ocr_full_text(image_bytes: bytes) -> OCRTextResult:
    return ocr_worker.recognize_full_text(image_bytes)

def _run_ocr_table(image_bytes: bytes) -> TableRecognitionResult:
    return ocr_worker.recognize_nutrition_table(image_bytes)

def _run_ocr_parallel(
    full_text_image_bytes: bytes,
    nutrition_image_bytes: bytes,
) -> OCRParallelResult:
    return ocr_worker.recognize_parallel(
        full_text_image_bytes,
        nutrition_image_bytes=nutrition_image_bytes,
    )

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
        record_external_dependency_error(
            service="ocr",
            operation="parallel_fallback",
            error_type=type(exc).__name__,
        )
        logger.warning(
            "parallel_ocr_fallback_to_sequential",
            task_id=task_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            masked_full_image_bytes=len(masked_full_image),
            cropped_image_bytes=len(cropped_image),
        )

    full_text_result = _run_ocr_full_text(masked_full_image)
    try:
        table_result = _run_ocr_table(cropped_image)
    except OCRServiceError as exc:
        record_external_dependency_error(
            service="ocr",
            operation="cropped_table_scan",
            error_type=type(exc).__name__,
        )
        logger.warning(
            "nutrition_table_cropped_scan_failed",
            task_id=task_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            cropped_image_bytes=len(cropped_image),
        )
        table_result = None

    if _table_result_is_incomplete(table_result):
        cropped_quality = _table_result_quality(table_result)
        try:
            full_image_table_result = _run_ocr_table(image_bytes)
        except OCRServiceError as exc:
            record_external_dependency_error(
                service="ocr",
                operation="full_image_table_fallback",
                error_type=type(exc).__name__,
            )
            logger.warning(
                "nutrition_table_full_image_fallback_failed",
                task_id=task_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                cropped_quality=cropped_quality,
                full_image_bytes=len(image_bytes),
            )
        else:
            selected_table_result = _choose_better_table_result(
                table_result, full_image_table_result
            )
            if selected_table_result is not table_result:
                logger.info(
                    "nutrition_table_full_image_fallback_selected",
                    task_id=task_id,
                    cropped_quality=cropped_quality,
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
