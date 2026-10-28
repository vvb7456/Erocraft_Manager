"""Persistent support conversations and image messages."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_naive_now
from app.db.base import Base


class SupportConversation(Base):
    __tablename__ = "manager_support_conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    last_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_read_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    admin_read_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive_now, nullable=False)


class SupportMessage(Base):
    __tablename__ = "manager_support_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sender_id", "client_id", name="uq_support_message_retry"),
        Index("ix_support_messages_conversation", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("manager_support_conversations.id", ondelete="CASCADE"), nullable=False)
    sender_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_type: Mapped[str | None] = mapped_column(String(32))
    image_path: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive_now, nullable=False)
