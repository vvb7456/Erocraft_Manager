"""Refund-related schemas — see ``docs/BILLING_DESIGN.md`` §10."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RefundCreateRequest(_Forbid):
    """``POST /api/admin/billing/orders/:id/refund`` payload — §10.1.

    Always issues a **full** refund of the chosen transaction's remaining
    refundable balance. Partial refunds are not supported.
    """

    transaction_id: int = Field(gt=0, description="本地 invoice_transactions.id")
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
    retry_count: int
    last_error: str | None
    initiated_by: int | None
    created_at: str
    updated_at: str
