"""Refund initiation + retry-driven status reconciliation.

See ``docs/BILLING_DESIGN.md`` §10. Three public coroutines:

* :func:`initiate_refund` — admin-triggered. Claims the order lock,
  inserts a ``pending`` refund row, calls gateway ``create_refund`` outside
  the tx; on transient/business failure rolls back to previous order
  status and surfaces the error.
* :func:`reconcile_refund_once` — single-row reconciliation step used by
  the ``refund_retry`` job. Queries gateway, advances refund status, and
  on ``SUCCEEDED`` finalizes the refund (tx.refunded_fen ↑, order status
  ↓ to ``refunded`` or ``previous_order_status``).
* :func:`list_pending_refunds` — driver for the retry job.

Hupijiao does **not** push refund webhooks; this job is the single
推动者 (per §10.3). All gateway HTTP happens outside DB transactions
(I4); refund/order/transaction updates happen under FOR UPDATE locks
(I3); ``manager_billing_invoice_transactions.refunded_fen`` is the only
authoritative refund-fact column (I1 corollary).
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import (
    BillingInvoice,
    BillingInvoiceTransaction,
    BillingOrder,
    BillingRefund,
)
from app.services.billing import incidents
from app.services.billing._ids import gen_refund_no
from app.services.billing.gateway import registry as gateway_registry
from app.services.billing.gateway.base import (
    CreateRefundRequest,
    GatewayBusinessError,
    GatewayError,
    GatewayTransientError,
    InvoicePaymentRef,
    QueryRefundRequest,
)

logger = logging.getLogger(__name__)


# Per §10.3 — exhaust-after-N-failures threshold.
_MAX_RETRY = 5
# Per §10.3 — "stuck in PROCESSING for N hours" alert threshold.
_STUCK_HOURS_DEFAULT = 24
# Per §10.3 — only retry rows older than this many minutes.
_RETRY_INTERVAL_MIN = 15


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class RefundError(Exception):
    """Base class for refund-service errors."""


class CannotRefund(RefundError):
    """Order is in a state that disallows refund (or already locked,
    or has no remaining refundable balance)."""


class GatewayUnavailableForRefund(RefundError):
    """Gateway adapter not registered (no env / disabled)."""


# --------------------------------------------------------------------------- #
# Public: initiate_refund
# --------------------------------------------------------------------------- #


async def initiate_refund(
    db: AsyncSession,
    *,
    order_id: int,
    transaction_id: int,
    reason: str | None,
    admin_id: int | None,
) -> BillingRefund:
    """Admin-triggered **full** refund. Implements §10.2.

    Always refunds the entire remaining refundable balance on the
    chosen transaction — partial refunds are not supported (B-002).

    Returns the refund row in ``pending`` state with ``gateway_refund_id``
    populated. Raises :class:`CannotRefund` /
    :class:`GatewayUnavailableForRefund` on input issues; re-raises
    :class:`GatewayError` on gateway failure after rolling back order
    status.
    """
    now = utc_naive_now()
    my_token = uuid.uuid4().hex

    # ── 1) Claim order lock + create pending refund row in one tx
    rc = await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.status.in_(("applied", "apply_failed", "manual_review")),
            or_(
                BillingOrder.lock_token.is_(None),
                BillingOrder.locked_until < now,
            ),
        )
        .values(
            lock_token=my_token,
            locked_until=now + timedelta(minutes=2),
        )
    )
    if rc.rowcount == 0:
        raise CannotRefund(
            "订单当前状态不允许退款，或正被其他流程处理中"
        )

    order = await db.scalar(
        select(BillingOrder).where(BillingOrder.id == order_id).with_for_update()
    )
    assert order is not None
    prev_status = order.status

    tx = await db.scalar(
        select(BillingInvoiceTransaction)
        .where(
            BillingInvoiceTransaction.id == transaction_id,
            BillingInvoiceTransaction.invoice_id.in_(
                select(BillingInvoice.id).where(BillingInvoice.order_id == order_id)
            ),
            BillingInvoiceTransaction.status.in_(("succeeded", "refunded")),
        )
        .with_for_update()
    )
    if tx is None:
        # Release lock before raising.
        await _release_lock(db, order_id, my_token)
        await db.commit()
        raise CannotRefund("找不到对应的成功扣款记录")

    invoice = await db.scalar(
        select(BillingInvoice).where(BillingInvoice.id == tx.invoice_id)
    )
    assert invoice is not None

    max_refundable = tx.amount_fen - (tx.refunded_fen or 0)
    if max_refundable <= 0:
        await _release_lock(db, order_id, my_token)
        await db.commit()
        raise CannotRefund("该笔交易没有可退余额")

    actual_amount = max_refundable

    if prev_status not in ("applied", "apply_failed", "manual_review"):
        # Defensive: rowcount check above already filtered, but the model
        # column may have changed between the UPDATE and our SELECT.
        await _release_lock(db, order_id, my_token)
        await db.commit()
        raise CannotRefund("订单状态在锁定期间发生变化")

    refund = BillingRefund(
        refund_no=gen_refund_no(),
        transaction_id=tx.id,
        order_id=order_id,
        amount_fen=actual_amount,
        status="pending",
        reason=(reason or None),
        previous_order_status=prev_status,
        initiated_by=admin_id,
    )
    db.add(refund)
    order.status = "refunding"
    await db.flush()
    refund_id = refund.id
    refund_no = refund.refund_no
    tx_gateway_code = tx.gateway_code
    tx_total_amount = tx.amount_fen
    invoice_no = invoice.invoice_no
    invoice_prepay_id = invoice.gateway_prepay_id or ""
    await db.commit()

    # ── 2) Gateway call outside DB tx (I4)
    await gateway_registry.ensure_loaded(db)
    try:
        gateway = gateway_registry.get(tx_gateway_code)
    except KeyError as exc:
        # Gateway not registered (HUPIJIAO_APPID/SECRET missing). Roll back.
        await _rollback_failed_refund(db, refund_id, order_id, prev_status, my_token,
                                      "gateway_not_registered")
        raise GatewayUnavailableForRefund(
            f"支付方式 '{tx_gateway_code}' 当前不可用"
        ) from exc

    try:
        result = await gateway.create_refund(
            CreateRefundRequest(
                invoice=InvoicePaymentRef(
                    invoice_no=invoice_no,
                    gateway_prepay_id=invoice_prepay_id or None,
                    transaction_id=None,
                    amount_fen=tx_total_amount,
                ),
                out_refund_no=refund_no,
                reason=reason or "refund",
            )
        )
    except GatewayError as exc:
        await _rollback_failed_refund(
            db, refund_id, order_id, prev_status, my_token, str(exc)[:500]
        )
        raise

    # ── 3) Persist gateway_refund_id, release lock
    await db.execute(
        update(BillingRefund)
        .where(BillingRefund.id == refund_id)
        .values(gateway_refund_id=result.gateway_refund_id, updated_at=utc_naive_now())
    )
    await _release_lock(db, order_id, my_token)
    await db.commit()

    # ── 4) Honor the gateway's synchronous status:
    #   SUCCEEDED → finalize immediately (no need to wait for webhook/poll).
    #   FAILED    → bump retry / mark failed.
    #   PROCESSING / UNKNOWN → leave as 'pending' for the retry job + webhook.
    if result.status == "SUCCEEDED":
        await _finalize_refund_succeeded(db, refund_id)
        try:
            from app.services.billing import notify

            await notify.notify_order_refunded(order_id, refund_id)
        except Exception:  # noqa: BLE001 - email is best-effort
            logger.exception(
                "notify_order_refunded failed for refund_id=%s", refund_id
            )
    elif result.status == "FAILED":
        await _bump_retry(
            db, refund_id, "gateway returned synchronous FAILED status"
        )

    refreshed = await db.scalar(select(BillingRefund).where(BillingRefund.id == refund_id))
    assert refreshed is not None
    return refreshed


# --------------------------------------------------------------------------- #
# Public: reconcile_refund_once  (driven by refund_retry job)
# --------------------------------------------------------------------------- #


async def list_pending_refunds(
    db: AsyncSession, *, limit: int = 100
) -> list[BillingRefund]:
    """Return rows that the retry job should poll right now."""
    cutoff = utc_naive_now() - timedelta(minutes=_RETRY_INTERVAL_MIN)
    rows = await db.execute(
        select(BillingRefund)
        .where(
            BillingRefund.status.in_(("pending", "failed")),
            BillingRefund.retry_count < _MAX_RETRY,
            BillingRefund.updated_at < cutoff,
        )
        .order_by(BillingRefund.id.asc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def reconcile_refund_once(
    db: AsyncSession, refund_id: int, *, stuck_hours: int = _STUCK_HOURS_DEFAULT
) -> str:
    """Drive a single refund row one step forward.

    Returns a short status string (``succeeded`` / ``processing`` /
    ``retried`` / ``failed`` / ``exhausted`` / ``noop``) for logging.
    """
    refund = await db.scalar(
        select(BillingRefund).where(BillingRefund.id == refund_id)
    )
    if refund is None:
        return "noop"
    if refund.status not in ("pending", "failed"):
        return "noop"

    tx = await db.scalar(
        select(BillingInvoiceTransaction).where(
            BillingInvoiceTransaction.id == refund.transaction_id
        )
    )
    if tx is None:  # pragma: no cover — FK should prevent this
        return "noop"
    gateway_code = tx.gateway_code

    # Fetch the original invoice early — adapters like hupijiao need
    # invoice_no for refund-status polling.
    invoice = await db.scalar(
        select(BillingInvoice).where(BillingInvoice.id == tx.invoice_id)
    )
    if invoice is None:  # pragma: no cover — FK should prevent
        return "noop"

    await gateway_registry.ensure_loaded(db)
    try:
        gateway = gateway_registry.get(gateway_code)
    except KeyError:
        # Gateway disabled at runtime; bump retry, leave for next pass.
        await _bump_retry(db, refund_id, "gateway_not_registered")
        return "failed"

    # ── Stage A: query gateway state
    try:
        result = await gateway.query_refund(
            QueryRefundRequest(
                out_refund_no=refund.refund_no,
                gateway_refund_id=refund.gateway_refund_id,
                invoice_no=invoice.invoice_no,
            )
        )
    except GatewayError as exc:
        exhausted = await _bump_retry(db, refund_id, str(exc)[:500])
        return "exhausted" if exhausted else "failed"

    if result == "SUCCEEDED":
        await _finalize_refund_succeeded(db, refund_id)
        try:
            from app.services.billing import notify

            await notify.notify_order_refunded(refund.order_id, refund_id)
        except Exception:  # noqa: BLE001 - email is best-effort
            logger.exception(
                "notify_order_refunded failed for refund_id=%s", refund_id
            )
        return "succeeded"

    if result == "PROCESSING":
        # Still in flight — don't bump retry, but check stuck threshold.
        age_hours = (utc_naive_now() - refund.created_at).total_seconds() / 3600
        if age_hours >= stuck_hours:
            await incidents.log_incident(
                "refund_retries_exhausted",
                order_id=refund.order_id,
                transaction_id=refund.transaction_id,
                payload={
                    "subkind": "stuck_processing",
                    "refund_id": refund.id,
                    "gateway_refund_id": refund.gateway_refund_id,
                    "age_hours": round(age_hours, 1),
                },
            )
        # Bump updated_at so we don't re-poll for another _RETRY_INTERVAL_MIN.
        await db.execute(
            update(BillingRefund)
            .where(BillingRefund.id == refund_id)
            .values(updated_at=utc_naive_now())
        )
        await db.commit()
        return "processing"

    # NOTFOUND / FAILED → re-issue create_refund
    try:
        gw_resp = await gateway.create_refund(
            CreateRefundRequest(
                invoice=InvoicePaymentRef(
                    invoice_no=invoice.invoice_no,
                    gateway_prepay_id=invoice.gateway_prepay_id or None,
                    transaction_id=None,
                    amount_fen=tx.amount_fen,
                ),
                out_refund_no=refund.refund_no,
                reason=refund.reason or "retry",
            )
        )
    except GatewayError as exc:
        exhausted = await _bump_retry(db, refund_id, str(exc)[:500])
        return "exhausted" if exhausted else "failed"

    now = utc_naive_now()
    await db.execute(
        update(BillingRefund)
        .where(BillingRefund.id == refund_id)
        .values(
            status="pending",
            gateway_refund_id=gw_resp.gateway_refund_id,
            last_error=None,
            retry_count=0,
            updated_at=now,
        )
    )
    await db.commit()

    # Honor synchronous status from the re-issued refund (same logic as
    # initiate_refund — gateway may settle instantly).
    if gw_resp.status == "SUCCEEDED":
        await _finalize_refund_succeeded(db, refund_id)
        try:
            from app.services.billing import notify

            await notify.notify_order_refunded(refund.order_id, refund_id)
        except Exception:  # noqa: BLE001 - email is best-effort
            logger.exception(
                "notify_order_refunded failed for refund_id=%s", refund_id
            )
        return "succeeded"
    if gw_resp.status == "FAILED":
        await _bump_retry(
            db, refund_id, "gateway returned synchronous FAILED status"
        )
        return "failed"
    return "retried"


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


async def _release_lock(
    db: AsyncSession, order_id: int, my_token: str
) -> None:
    await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.lock_token == my_token,
        )
        .values(lock_token=None, locked_until=None)
    )


async def _rollback_failed_refund(
    db: AsyncSession,
    refund_id: int,
    order_id: int,
    prev_status: str,
    my_token: str,
    error_msg: str,
) -> None:
    """Mark refund as failed and restore order to its previous status."""
    now = utc_naive_now()
    await db.execute(
        update(BillingRefund)
        .where(BillingRefund.id == refund_id)
        .values(status="failed", last_error=error_msg, updated_at=now)
    )
    await db.execute(
        update(BillingOrder)
        .where(BillingOrder.id == order_id, BillingOrder.lock_token == my_token)
        .values(status=prev_status, lock_token=None, locked_until=None)
    )
    await db.commit()


async def _bump_retry(
    db: AsyncSession, refund_id: int, error_msg: str
) -> bool:
    """Increment retry_count, set last_error. Returns True iff exhausted."""
    now = utc_naive_now()
    refund = await db.scalar(
        select(BillingRefund).where(BillingRefund.id == refund_id).with_for_update()
    )
    if refund is None:
        return False
    refund.retry_count = (refund.retry_count or 0) + 1
    refund.last_error = error_msg
    refund.updated_at = now
    if refund.retry_count >= _MAX_RETRY and refund.status != "succeeded":
        refund.status = "failed"
        await db.commit()
        await incidents.log_incident(
            "refund_retries_exhausted",
            order_id=refund.order_id,
            transaction_id=refund.transaction_id,
            payload={
                "refund_id": refund.id,
                "last_error": error_msg,
            },
        )
        return True
    refund.status = "failed"
    await db.commit()
    return False


async def _finalize_refund_succeeded(
    db: AsyncSession, refund_id: int
) -> None:
    """§10.3 ``_finalize_refund_succeeded`` — single-tx atomic advance.

    Idempotent: re-entering after refund.status='succeeded' returns early.
    """
    now = utc_naive_now()
    refund = await db.scalar(
        select(BillingRefund)
        .where(
            BillingRefund.id == refund_id,
            BillingRefund.status.in_(("pending", "failed")),
        )
        .with_for_update()
    )
    if refund is None:
        return  # already finalized by a concurrent worker

    refund.status = "succeeded"
    refund.last_error = None
    refund.updated_at = now

    tx = await db.scalar(
        select(BillingInvoiceTransaction)
        .where(BillingInvoiceTransaction.id == refund.transaction_id)
        .with_for_update()
    )
    assert tx is not None
    # Full refund only — refund.amount_fen was set to the full remaining
    # refundable balance at initiate time. We assert the invariant rather
    # than supporting partial accumulation.
    tx.refunded_fen = tx.amount_fen
    tx.status = "refunded"
    tx.updated_at = now

    order = await db.scalar(
        select(BillingOrder)
        .where(BillingOrder.id == refund.order_id)
        .with_for_update()
    )
    assert order is not None
    order.refunded_fen = (order.refunded_fen or 0) + refund.amount_fen
    order.status = "refunded"
    order.lock_token = None
    order.locked_until = None
    order.updated_at = now

    # Auto-resolve open incidents on this order
    from app.db.models.billing import BillingIncident
    await db.execute(
        update(BillingIncident)
        .where(
            BillingIncident.order_id == refund.order_id,
            BillingIncident.status == "open",
        )
        .values(
            status="resolved",
            resolution_note="refund finalized",
            resolved_at=now,
        )
    )

    await db.commit()
