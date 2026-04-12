from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimeStampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.report import Report
    from app.models.report_conversation_message import ReportConversationMessage
    from app.models.user import User


class ReportConversation(UUIDPrimaryKeyMixin, TimeStampMixin, Base):
    __tablename__ = "report_conversations"
    __table_args__ = (
        Index("idx_report_conversations_user_id_updated_at", "user_id", "updated_at"),
        {"extend_existing": True},
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    suggested_questions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )

    report: Mapped["Report"] = relationship(back_populates="conversation")
    user: Mapped["User"] = relationship(back_populates="report_conversations")
    messages: Mapped[list["ReportConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ReportConversationMessage.created_at.asc()",
    )


__all__ = ["ReportConversation"]
