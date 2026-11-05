"""Refund-related schemas — see ``docs/BILLING_DESIGN.md`` §10."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RefundCreateRequest(_Forbid):
    """申请支付交易全额退款，或登记外部订单全额退款。"""

    transaction_id: int | None = Field(default=None, gt=0, description="本地 invoice_transactions.id")
    external_refund_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    reason: str = Field(min_length=1, max_length=80)


class RefundOut(BaseModel):
    """Refund row projection."""

    id: int
    refund_no: str
    transaction_id: int | None
    payment_id: int | None
    order_id: int
    amount_fen: int
    status: str
    reason: str | None
    gateway_refund_id: str | None
    external_refund_id: str | None
    retry_count: int
    last_error: str | None
    initiated_by: int | None
    created_at: str
    updated_at: str
