"""Schemas for billing orders + invoice summaries.

See ``docs/BILLING_DESIGN.md`` §6 (order creation) and §8 (cancellation).
Order responses embed a slim invoice projection; full invoice CRUD lives
in a future ``billing_invoices.py`` once admin-side invoice listing is
implemented.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateOrderRequest(_Forbid):
    """``POST /api/user/orders`` payload — see ``BILLING_DESIGN.md`` §6.

    Cross-field rules:

    * ``kind == 'renew'``: ``target_server_id`` required, ``plan_code`` forbidden
      (server's bound plan is read from ``server_meta.plan_id``).
    * ``kind == 'new_purchase'``: ``plan_code`` required, ``target_server_id``
      forbidden (a placeholder server row is created during order placement).
    * ``kind == 'upgrade'``: both ``target_server_id`` and ``plan_code`` required;
      ``period_count`` is forced to 1 server-side and total_fen is the prorated
      diff between new and old plan over the server's remaining days.
    * ``period_count`` must hit a configured ``plan.period_options[*].count``
      for renew/new_purchase; ignored for upgrade (forced to 1).
    """

    kind: str = Field(pattern=r"^(renew|new_purchase|upgrade|convert)$")
    plan_code: str | None = Field(default=None, max_length=64)
    target_server_id: int | None = Field(default=None, gt=0)
    period_count: int = Field(default=1, ge=1, le=24)
    gateway_code: str = Field(min_length=1, max_length=32)
    # Optional coupon code applied at order placement. See
    # ``REFERRAL_AND_COUPON_DESIGN.md`` §6. Empty/whitespace is treated as
    # absent so the frontend can ship a value-less ``<select>`` cleanly.
    coupon_code: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "CreateOrderRequest":
        if self.kind == "renew":
            if self.target_server_id is None:
                raise ValueError("续费订单必须提供 target_server_id")
            if self.plan_code is not None:
                raise ValueError("续费订单不应提供 plan_code（从服务器读取套餐）")
        elif self.kind == "upgrade":
            if self.target_server_id is None:
                raise ValueError("升级订单必须提供 target_server_id")
            if self.plan_code is None:
                raise ValueError("升级订单必须提供 plan_code")
        elif self.kind == "convert":
            # Trial → linked standard plan. target_server_id required; the
            # target plan is resolved server-side from the trial's
            # linked_plan_id, so plan_code is forbidden here.
            if self.target_server_id is None:
                raise ValueError("转换订单必须提供 target_server_id")
            if self.plan_code is not None:
                raise ValueError("转换订单不应提供 plan_code（从试用套餐的关联标准套餐读取）")
        else:  # new_purchase
            if self.plan_code is None:
                raise ValueError("新购订单必须提供 plan_code")
            if self.target_server_id is not None:
                raise ValueError("新购订单不应提供 target_server_id")
        return self


class OrderInvoiceOut(BaseModel):
    """Invoice summary embedded in order responses."""

    id: int
    invoice_no: str
    status: str
    total_fen: int
    currency_code: str
    due_at: str | None
    paid_at: str | None
    gateway_code: str | None
    gateway_prepay_id: str | None = None
    transaction_id: str | None = None
    code_url: str | None
    pay_url: str | None


class OrderOut(BaseModel):
    """Order detail returned to user-side endpoints."""

    id: int
    order_no: str
    user_id: int
    plan_id: int | None
    plan_code: str
    plan_name: str
    kind: str
    period_count: int
    discount_pct: float
    total_fen: int
    total_days: int
    currency_code: str
    target_server_id: int | None
    target_server_name: str | None = None
    status: str
    received_fen: int
    refunded_fen: int
    created_at: str
    updated_at: str
    applied_at: str | None
    closed_at: str | None
    cancelled_at: str | None
    invoice: OrderInvoiceOut | None
    coupon_id: int | None = None
    coupon_code: str | None = None
    coupon_discount_fen: int | None = None


class CreateOrderResponse(BaseModel):
    order: OrderOut
