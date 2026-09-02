"""Admin-facing billing schemas — see ``docs/BILLING_DESIGN.md`` §11.

Splits per domain:

* :class:`AdminOrderOut` / :class:`AdminOrderListItem` — admin order projections
* :class:`OrderTransactionOut` — fund-fact summary embedded in order detail
* :class:`OrderEffectOut` — apply effect summary embedded in order detail
* :class:`ForceCloseRequest` — reason note required by §11.4

User-facing order schemas live in ``billing_orders.py``; refunds in
``billing_refunds.py``; incidents in ``billing_incidents.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanSnapshotPeriodOut(BaseModel):
    """Selected billing period inside a plan snapshot."""

    model_config = ConfigDict(extra="allow")
    count: int
    discount_pct: float
    total_fen: int
    total_days: int


class PlanSnapshotOut(BaseModel):
    """§3.3.1 plan snapshot — frozen plan/pricing at order creation time.

    ``extra="allow"`` because old orders may carry ``schema_version=1`` rows
    with a slightly different field set, and apply_engine reads from this blob
    by key — the schema must not strip unknown fields.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int
    plan_id: int
    plan_name: str
    plan_code: str
    price_fen: int
    days: int
    currency_code: str
    selected_period: PlanSnapshotPeriodOut
    egg_id: int
    nest_id: int
    node_id: int | None = None
    docker_image: str
    startup_command: str
    env_snapshot: dict[str, str] = Field(default_factory=dict)
    cpu: int
    memory_mb: int
    disk_mb: int
    swap_mb: int
    io: int
    database_limit: int
    backup_limit: int
    allocation_limit: int
    oom_disabled: bool


# --------------------------------------------------------------------------- #
# Read projections
# --------------------------------------------------------------------------- #


class OrderTransactionOut(BaseModel):
    """Fund fact summary — ``manager_billing_invoice_transactions`` row."""

    id: int
    invoice_id: int
    gateway_code: str
    transaction_id: str
    amount_fen: int
    refunded_fen: int
    status: str
    created_at: str
    updated_at: str


class OrderEffectOut(BaseModel):
    """Apply effect summary — ``manager_billing_order_effects`` row."""

    order_id: int
    effect_type: str
    server_id: int
    days: int
    prev_expiration_date: str | None
    new_expiration_date: str
    effect_committed_at: str
    post_actions_done_at: str | None


class OrderRefundSummary(BaseModel):
    """Refund summary embedded in admin order detail."""

    id: int
    refund_no: str
    transaction_id: int
    amount_fen: int
    status: str
    reason: str | None
    previous_order_status: str
    gateway_refund_id: str | None
    retry_count: int
    last_error: str | None
    initiated_by: int | None
    initiated_by_username: str | None = None
    created_at: str
    updated_at: str


class AdminOrderListItem(BaseModel):
    """Slim row for ``GET /api/admin/billing/orders``."""

    id: int
    order_no: str
    user_id: int
    owner_username: str | None = None
    plan_id: int | None
    plan_code: str
    plan_name: str
    kind: str
    channel: str = "alipay"
    external_order_id: str | None = None
    operator: str = "system"
    channel_note: str | None = None
    period_count: int
    total_fen: int
    total_days: int
    target_server_id: int | None
    target_server_name: str | None = None
    status: str
    received_fen: int
    refunded_fen: int
    created_at: str
    updated_at: str


class OrderListResponse(BaseModel):
    """Paginated envelope for ``GET /api/admin/billing/orders``.

    Mirrors ``CouponListResponse`` so the admin DataTable can compute
    ``totalPages = ceil(total / perPage)`` instead of guessing.
    """

    items: list[AdminOrderListItem]
    total: int


class AdminInvoiceOut(BaseModel):
    """Invoice projection used by admin order detail."""

    id: int
    invoice_no: str
    status: str
    total_fen: int
    currency_code: str
    due_at: str | None
    paid_at: str | None
    gateway_code: str | None
    gateway_prepay_id: str | None
    code_url: str | None
    pay_url: str | None
    pay_url_h5: str | None = None
    created_at: str
    updated_at: str


class AdminOrderOut(BaseModel):
    """Full admin order detail — includes invoices, transactions, effect, refunds."""

    id: int
    order_no: str
    user_id: int
    owner_username: str | None = None
    plan_id: int | None
    plan_snapshot: PlanSnapshotOut
    kind: str
    channel: str = "alipay"
    external_order_id: str | None = None
    operator: str = "system"
    channel_note: str | None = None
    period_count: int
    discount_pct: float
    total_fen: int
    total_days: int
    target_server_id: int | None
    target_server_name: str | None = None
    reserved_node_id: int | None
    reserved_allocation_id: int | None
    status: str
    received_fen: int
    refunded_fen: int
    apply_retry_count: int
    next_apply_at: str | None
    last_apply_error: str | None
    applied_at: str | None
    closed_at: str | None
    cancelled_at: str | None
    created_at: str
    updated_at: str
    invoices: list[AdminInvoiceOut]
    transactions: list[OrderTransactionOut]
    effect: OrderEffectOut | None
    refunds: list[OrderRefundSummary]


# --------------------------------------------------------------------------- #
# Write requests
# --------------------------------------------------------------------------- #


class ForceCloseRequest(_Forbid):
    """``POST /api/admin/billing/orders/:id/force-close`` payload."""

    note: str = Field(min_length=1, max_length=500)


class ForceApplyRequest(_Forbid):
    """``POST /api/admin/billing/orders/:id/force-apply`` (no body needed)."""


class CleanupPlaceholderRequest(_Forbid):
    """``POST /api/admin/billing/orders/:id/cleanup-placeholder`` (no body)."""


class ActionAck(_Forbid):
    """Common ACK envelope for admin order actions (force-apply / force-close /
    cleanup-placeholder).

    ``result`` is a free-form action-specific outcome string
    (e.g. ``apply_engine.ApplyResult`` value for ``force-apply``;
    ``"ok"`` for the other two).
    """

    order_id: int
    action: str
    result: str
