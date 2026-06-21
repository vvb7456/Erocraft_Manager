"""Billing ORM models — see ``docs/BILLING_DESIGN.md`` §3.

All models map to ``manager_billing_*`` tables created by Alembic
revision ``0012``. Stick to the wire format defined in that revision —
new columns require a follow-up migration.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CHAR,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_naive_now
from app.db.base import Base


# ── shared enum value tuples (keep in sync with baseline + trial migration) ─
PLAN_TYPE_VALUES = ("standard", "trial")
ORDER_KIND_VALUES = ("renew", "new_purchase", "upgrade", "convert")
ORDER_STATUS_VALUES = (
    "pending",
    "processing",
    "applied",
    "apply_failed",
    "closed",
    "cancelled",
    "refunding",
    "refunded",
    "manual_review",
)
INVOICE_STATUS_VALUES = ("pending", "paid", "void")
TX_STATUS_VALUES = ("succeeded", "failed", "refunded")
EFFECT_TYPE_VALUES = ("renew", "new_purchase", "upgrade", "convert")
REFUND_STATUS_VALUES = ("pending", "succeeded", "failed")
REFUND_PREV_STATUS_VALUES = ("applied", "apply_failed", "manual_review")
INCIDENT_KIND_VALUES = (
    "manual_review_required",
    "apply_retries_exhausted",
    "refund_retries_exhausted",
    "placeholder_leak",
    "placeholder_cleanup_failed",
)
INCIDENT_STATUS_VALUES = ("open", "investigating", "resolved", "wontfix")
COUPON_SOURCE_VALUES = (
    "referral_inviter",
    "referral_invitee",
    "admin_grant",
    "promo",
)
COUPON_STATUS_VALUES = ("unused", "reserved", "used", "revoked")


class BillingPlan(Base):
    """v2 single-plan model — see ``BILLING_DESIGN.md`` §3.2.

    No ``kind`` column (plans are products, ``kind`` is an order-level
    intent). Resource fields are mandatory; ``period_options`` is a JSON
    array of ``{count: int, discount_pct: number}`` validated by
    :class:`app.schemas.billing.PlanIn`.
    """

    __tablename__ = "manager_billing_plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    price_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="CNY")

    period_options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    egg_id: Mapped[int] = mapped_column(Integer, nullable=False)
    nest_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    swap_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    io: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    database_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backup_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allocation_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    oom_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    docker_image: Mapped[str] = mapped_column(String(255), nullable=False)
    startup_command: Mapped[str] = mapped_column(Text, nullable=False)
    env_defaults: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_label: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Trial-plan support (20260619_trial migration). ``plan_type`` is
    # ``standard`` (default) or ``trial``. A trial plan mirrors the
    # resource fields of its ``linked_plan_id`` (a standard plan with the
    # same egg); admin edits the linked plan, not the trial's resources.
    # Trial plans: low price to attract first-time subscribers; on
    # expiry they are deleted with zero grace (not the global suspend/
    # delete cadence), and their only renewal path is a ``convert`` order
    # that rebinds the server to the linked standard plan.
    plan_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="standard",
    )
    linked_plan_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_plans.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now, onupdate=utc_naive_now
    )


class BillingOrder(Base):
    __tablename__ = "manager_billing_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    plan_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    kind: Mapped[str] = mapped_column(
        Enum(*ORDER_KIND_VALUES, name="billing_order_kind"), nullable=False
    )
    # v2 period / pricing fields (locked at order creation; apply reads these,
    # never re-derives from plan).
    period_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    discount_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    total_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    total_days: Mapped[int] = mapped_column(Integer, nullable=False)
    target_server_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reserved_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reserved_allocation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reserved_additional_allocations: Mapped[list[int] | None] = mapped_column(
        JSON, nullable=True
    )
    # v3 coupon: snapshot of the discount applied (so price stays
    # reproducible across cancel/refund). ``coupon_id`` is NULL until the
    # user picks one; set when create_order reserves the coupon. The
    # discount is locked at order creation, never recomputed.
    coupon_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_coupons.id", ondelete="SET NULL"),
        nullable=True,
    )
    coupon_discount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    status: Mapped[str] = mapped_column(
        Enum(*ORDER_STATUS_VALUES, name="billing_order_status"),
        nullable=False,
        default="pending",
    )
    received_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refunded_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    apply_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_apply_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_apply_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lock_token: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now, onupdate=utc_naive_now
    )


class BillingInvoice(Base):
    __tablename__ = "manager_billing_invoices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*INVOICE_STATUS_VALUES, name="billing_invoice_status"),
        nullable=False,
        default="pending",
    )
    total_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="CNY")
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    gateway_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gateway_prepay_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gateway_code_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    gateway_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now, onupdate=utc_naive_now
    )


class BillingInvoiceItem(Base):
    __tablename__ = "manager_billing_invoice_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    price_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now, onupdate=utc_naive_now
    )


class BillingInvoiceTransaction(Base):
    __tablename__ = "manager_billing_invoice_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    gateway_code: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    fee_fen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(*TX_STATUS_VALUES, name="billing_tx_status"), nullable=False
    )
    refunded_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now, onupdate=utc_naive_now
    )


class BillingOrderEffect(Base):
    __tablename__ = "manager_billing_order_effects"

    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_orders.id", ondelete="CASCADE"),
        primary_key=True,
    )
    effect_type: Mapped[str] = mapped_column(
        Enum(*EFFECT_TYPE_VALUES, name="billing_effect_type"), nullable=False
    )
    server_id: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    prev_expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    effect_committed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    post_actions_done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BillingRefund(Base):
    __tablename__ = "manager_billing_refunds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    refund_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    transaction_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_invoice_transactions.id"),
        nullable=False,
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("manager_billing_orders.id"), nullable=False
    )
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*REFUND_STATUS_VALUES, name="billing_refund_status"),
        nullable=False,
        default="pending",
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    previous_order_status: Mapped[str] = mapped_column(
        Enum(*REFUND_PREV_STATUS_VALUES, name="billing_refund_prev_status"),
        nullable=False,
        default="applied",
    )
    gateway_refund_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    initiated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now, onupdate=utc_naive_now
    )


class BillingPaymentEvent(Base):
    __tablename__ = "manager_billing_payment_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    gateway_code: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    invoice_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_body: Mapped[str] = mapped_column(Text(length=(1 << 32) - 1), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    process_result: Mapped[str | None] = mapped_column(String(64), nullable=True)


class BillingIncident(Base):
    __tablename__ = "manager_billing_incidents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(
        Enum(*INCIDENT_KIND_VALUES, name="billing_incident_kind"), nullable=False
    )
    order_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    invoice_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    server_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*INCIDENT_STATUS_VALUES, name="billing_incident_status"),
        nullable=False,
        default="open",
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CouponTemplate(Base):
    """Admin-defined coupon recipe. See ``REFERRAL_AND_COUPON_DESIGN.md`` §4.2.

    Templates define the *rules*; instances (``Coupon``) carry a *snapshot*
    of the rules at issuance so future template edits don't retroactively
    change already-issued coupons (invariant C1).
    """

    __tablename__ = "manager_billing_coupon_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    min_order_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # NULL = applies to all plans / all kinds. Otherwise a JSON array of
    # plan ids / order kinds (``new_purchase`` / ``renew`` / ``upgrade``).
    applicable_plan_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    applicable_order_kinds: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now, onupdate=utc_naive_now
    )


class Coupon(Base):
    """Issued coupon instance — snapshot-immutable per invariant C1.

    State machine: ``unused`` → ``reserved`` → ``used`` (terminal) /
    ``revoked`` (terminal). Coupons released from ``reserved`` (order
    cancel / fail) always revert to ``unused``; expiry is a derived
    fact (``status == 'unused' AND expires_at <= now``), not a stored
    state — there is no scheduled job to materialize it.
    """

    __tablename__ = "manager_billing_coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(CHAR(16), nullable=False, unique=True)
    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manager_billing_coupon_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        Enum(*COUPON_SOURCE_VALUES, name="billing_coupon_source"), nullable=False
    )
    # Free-form back-reference: for referral grants this is the referral row id;
    # for admin_grant it's the admin user id; for promo it's NULL.
    source_ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(*COUPON_STATUS_VALUES, name="billing_coupon_status"),
        nullable=False,
        default="unused",
    )
    # Snapshot copy of template values — frozen at issuance.
    discount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    min_order_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applicable_plan_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    applicable_order_kinds: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reserved_order_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_order_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Captured at apply-time: how much we actually subtracted (may differ
    # from snapshot ``discount_fen`` if the order subtotal was < discount).
    actual_discount_fen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_naive_now, onupdate=utc_naive_now
    )
