"""Account bindings and revocable credentials for the limited mini-program console."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MiniProgramBinding(Base):
    __tablename__ = "manager_miniprogram_bindings"
    __table_args__ = (
        UniqueConstraint("appid", "openid", name="uq_mini_wechat_identity"),
        UniqueConstraint("appid", "user_id", name="uq_mini_user_identity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    appid: Mapped[str] = mapped_column(String(32), nullable=False)
    openid: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MiniProgramSession(Base):
    __tablename__ = "manager_miniprogram_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    appid: Mapped[str] = mapped_column(String(32), nullable=False)
    openid: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), nullable=False)
    binding_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("manager_miniprogram_bindings.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
