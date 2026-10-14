"""Durable, independently retried deliveries for administrator notifications."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_naive_now
from app.db.base import Base


class NotificationIssue(Base):
    __tablename__ = "manager_notification_issues"

    key: Mapped[str] = mapped_column(String(190), primary_key=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_naive_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_naive_now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class NotificationDelivery(Base):
    __tablename__ = "manager_notification_deliveries"
    __table_args__ = (
        Index("uq_notification_dedup", "dedup_key", unique=True),
        Index("ix_notification_due", "status", "available_at"),
        Index("ix_notification_topic", "topic", "created_at"),
        Index("ix_notification_recipient", "recipient", "last_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    gateway_key: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="wecom")
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_naive_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_naive_now)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(String(500))
    message_id: Mapped[str | None] = mapped_column(String(255))
