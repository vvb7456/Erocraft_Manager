"""Manager-owned tables stored in the Panel database."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.pterodactyl import PteroServer


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ServerMeta(Base):
    __tablename__ = "manager_server_meta"

    server_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("servers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    server: Mapped["PteroServer"] = relationship("PteroServer", back_populates="meta")


class ManagerActivityLog(Base):
    __tablename__ = "manager_activity_logs"
    __table_args__ = (
        Index("idx_timestamp", "timestamp"),
        Index("idx_actor", "actor"),
        Index("idx_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    detail_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail_params: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemSetting(Base):
    __tablename__ = "manager_system_settings"
    __table_args__ = (Index("idx_category", "category"),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="runtime")
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="string")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=_utc_now,
        onupdate=_utc_now,
    )


class ManagerPasswordReset(Base):
    __tablename__ = "manager_password_resets"
    __table_args__ = (Index("idx_pw_reset_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ManagerEmailChange(Base):
    __tablename__ = "manager_email_changes"
    __table_args__ = (Index("idx_email_change_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    new_email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ManagerEmailTemplate(Base):
    __tablename__ = "manager_email_templates"

    template_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=_utc_now,
        onupdate=_utc_now,
    )
