"""Short-lived payment-only credentials, independent from account sessions."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WechatPaymentSession(Base):
    __tablename__ = "manager_wechat_payment_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("manager_billing_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scene: Mapped[str] = mapped_column(String(16), nullable=False)
    appid: Mapped[str] = mapped_column(String(32), nullable=False)
    openid: Mapped[str | None] = mapped_column(String(128))
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
