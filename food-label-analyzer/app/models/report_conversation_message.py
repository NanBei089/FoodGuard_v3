"""数据库表对应的 ORM 模型。"""


from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.report_conversation import ReportConversation


class ReportConversationMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """数据库表模型，字段基本对应表里的列。"""
    __tablename__ = "report_conversation_messages"
    __table_args__ = (
        Index(
            "idx_report_conversation_messages_conversation_id_created_at",
            "conversation_id",
            "created_at",
        ),
        {"extend_existing": True},
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped["ReportConversation"] = relationship(back_populates="messages")


__all__ = ["ReportConversationMessage"]
