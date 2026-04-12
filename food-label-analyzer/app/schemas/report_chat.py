from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import BASE_MODEL_CONFIG


class _ReportChatSchema(BaseModel):
    model_config = BASE_MODEL_CONFIG


class ReportConversationMessageSchema(_ReportChatSchema):
    message_id: UUID = Field(description="Conversation message identifier")
    role: Literal["user", "assistant"] = Field(description="Conversation role")
    content: str = Field(description="Message content")
    created_at: datetime = Field(description="Message creation time")


class ReportConversationResponse(_ReportChatSchema):
    conversation_id: UUID = Field(description="Conversation identifier")
    report_id: UUID = Field(description="Report identifier")
    suggested_questions: list[str] = Field(default_factory=list)
    messages: list[ReportConversationMessageSchema] = Field(default_factory=list)


class ReportChatSuggestionsResponse(_ReportChatSchema):
    suggested_questions: list[str] = Field(default_factory=list)


class ReportChatAskRequest(_ReportChatSchema):
    message: str = Field(min_length=1, max_length=2000, description="User prompt")


__all__ = [
    "ReportChatAskRequest",
    "ReportChatSuggestionsResponse",
    "ReportConversationMessageSchema",
    "ReportConversationResponse",
]
