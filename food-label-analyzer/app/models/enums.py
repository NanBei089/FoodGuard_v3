"""数据库表对应的 ORM 模型。"""


from __future__ import annotations

import enum


class TaskStatus(str, enum.Enum):

    """数据库表模型，字段基本对应表里的列。"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationType(str, enum.Enum):

    """数据库表模型，字段基本对应表里的列。"""
    REGISTER = "register"
    RESET_PASSWORD = "reset_password"


class NutritionParseSource(str, enum.Enum):

    """数据库表模型，字段基本对应表里的列。"""
    TABLE_RECOGNITION = "table_recognition"
    OCR_TEXT = "ocr_text"
    LLM_FALLBACK = "llm_fallback"
    EMPTY = "empty"
    FAILED = "failed"


__all__ = ["NutritionParseSource", "TaskStatus", "VerificationType"]
