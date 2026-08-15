"""Billing background tasks — see ``docs/BILLING_DESIGN.md`` §8.1 / §8.3 / §9.5.

Three independent jobs registered by ``app/jobs/scheduler.py``:

* :func:`run_order_close` (``ORDER_CLOSE_JOB_ID``) — every 1 min:
  closes pending orders past their invoice ``due_at``. Last-second
  payment race handled by gateway 二次确认 + ``safe_add_payment``.
* :func:`run_order_query` (``ORDER_QUERY_JOB_ID``) — every 3 min:
  proactively queries hupijiao for pending orders before due_at to
  catch missed webhooks; recovered SUCCESSes go through
  ``safe_add_payment``.
* :func:`run_apply_retry` (``APPLY_RETRY_JOB_ID``) — every 1 min:
  re-runs ``apply_paid_order`` for processing orders whose
  ``next_apply_at`` has elapsed (or was never set due to a stage-2
  lock failure on the first attempt).

All three use independent sessions per candidate to keep one bad order
from blocking the rest of the batch.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import (
    BillingInvoice,
    BillingInvoiceTransaction,
    BillingOrder,
)
from app.db.session import get_session_factory
from app.services import server_lifecycle
from app.services.billing import incidents, payments
from app.services.billing.apply_engine import apply_paid_order
from app.services.billing.gateway import registry as gateway_registry
from app.services.billing.gateway.base import GatewayError, QueryResult

logger = logging.getLogger(__name__)

ORDER_CLOSE_JOB_ID = "billing_order_close"
ORDER_QUERY_JOB_ID = "billing_order_query"
APPLY_RETRY_JOB_ID = "billing_apply_retry"
REFUND_RETRY_JOB_ID = "billing_refund_retry"
PLACEHOLDER_LEAK_JOB_ID = "billing_placeholder_leak_monitor"

_BATCH_LIMIT = 100
_CLOSE_LEASE = timedelta(minutes=2)


def _query_payment_amount(
    invoice: BillingInvoice, result: QueryResult
) -> tuple[int, int | None]:
    """Return (actual amount, expected-on-mismatch marker) for query results.

    ``safe_add_payment`` treats a non-``None`` marker as an explicit amount
    mismatch. Only pass it when the gateway supplied an amount that differs;
    gateways that omit the amount retain the invoice total as the best local
    value and follow the normal path.
    """
    amount_fen = (
        result.amount_fen if result.amount_fen is not None else invoice.total_fen
    )
    mismatch_expected = (
        invoice.total_fen
        if result.amount_fen is not None and result.amount_fen != invoice.total_fen
        else None
    )
    return amount_fen, mismatch_expected


# --------------------------------------------------------------------------- #
# order_close — §8.1
# --------------------------------------------------------------------------- #


async def run_order_close() -> None:
    """Scan pending orders past invoice.due_at and drive them to closed."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        now = utc_naive_now()
        candidates = (
            await db.execute(
                select(BillingOrder.id)
                .join(BillingInvoice, BillingInvoice.order_id == BillingOrder.id)
                .where(
                    BillingOrder.status == "pending",
                    BillingInvoice.due_at <= now,
                )
                .limit(_BATCH_LIMIT)
            )
        ).scalars().all()

    for oid in candidates:
        async with session_factory() as db:
            try:
                await _close_one_order(db, oid)
            except Exception:
                logger.exception("order_close failed for order %s", oid)


async def _close_one_order(db: AsyncSession, order_id: int) -> None:
    my_token = uuid.uuid4().hex
    now = utc_naive_now()

    # 1) Claim + lease
    rc = await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.status == "pending",
            or_(
                BillingOrder.lock_token.is_(None),
                BillingOrder.locked_until.is_(None),
                BillingOrder.locked_until < now,
            ),
        )
        .values(lock_token=my_token, locked_until=now + _CLOSE_LEASE)
    )
    await db.commit()
    if rc.rowcount == 0:
        return

    target_server_id: int | None = None
    closed_in_this_run = False

    try:
        invoice = await db.scalar(
            select(BillingInvoice).where(BillingInvoice.order_id == order_id)
        )
        if invoice is None:
            logger.error("order_close: order %s has no invoice", order_id)
            return

        gateway_code = invoice.gateway_code or "hupijiao"
        await gateway_registry.ensure_loaded(db)
        try:
            gateway = gateway_registry.get(gateway_code)
        except KeyError:
            logger.warning(
                "order_close: gateway %r not registered; skipping order %s",
                gateway_code, order_id,
            )
            return

        # 2) Gateway query (outside tx, I4)
        try:
            result = await gateway.query_by_out_trade_no(invoice.invoice_no)
        except GatewayError as exc:
            logger.warning(
                "order_close: gateway query failed for order %s: %s — retrying next round",
                order_id, exc,
            )
            return

        if result.status == "SUCCESS":
            # Last-second payment — release lock then hand off to add_payment.
            amount_fen, mismatch_expected = _query_payment_amount(invoice, result)
            await db.execute(
                update(BillingOrder)
                .where(
                    BillingOrder.id == order_id,
                    BillingOrder.lock_token == my_token,
                )
                .values(lock_token=None, locked_until=None)
            )
            await db.commit()
            await payments.safe_add_payment(
                db,
                invoice,
                gateway_code=gateway_code,
                transaction_id=result.transaction_id or "",
                amount_fen=amount_fen,
                raw_event_id=None,
                amount_mismatch_expected=mismatch_expected,
            )
            return

        # 2.5) Best-effort gateway close. A query that already reports CLOSED
        # is definitive, so skip the close API and continue to local close.
        if result.status != "CLOSED":
            # At this point the absolute gateway deadline has already elapsed;
            # closing an existing WAIT_BUYER_PAY trade makes the rejection
            # immediate. ALREADY_PAID is the reachable query/close race.
            try:
                close_outcome = await gateway.close_trade(invoice.invoice_no)
            except GatewayError as exc:
                logger.warning(
                    "order_close: trade close failed for order %s: %s — proceeding with local close",
                    order_id, exc,
                )
                close_outcome = None
            else:
                if close_outcome == "ALREADY_PAID":
                    try:
                        result2 = await gateway.query_by_out_trade_no(invoice.invoice_no)
                    except GatewayError as exc:
                        logger.warning(
                            "order_close: re-query after ALREADY_PAID failed for order %s: %s",
                            order_id, exc,
                        )
                        # The trade may still be transitioning at the gateway;
                        # do not turn an inconclusive ALREADY_PAID response into
                        # a local close. The lease is released in ``finally``
                        # and a later close/query cycle can reconcile it.
                        return
                    if result2.status == "SUCCESS":
                        amount_fen, mismatch_expected = _query_payment_amount(
                            invoice, result2
                        )
                        await db.execute(
                            update(BillingOrder)
                            .where(
                                BillingOrder.id == order_id,
                                BillingOrder.lock_token == my_token,
                            )
                            .values(lock_token=None, locked_until=None)
                        )
                        await db.commit()
                        await payments.safe_add_payment(
                            db,
                            invoice,
                            gateway_code=gateway_code,
                            transaction_id=result2.transaction_id or "",
                            amount_fen=amount_fen,
                            raw_event_id=None,
                            amount_mismatch_expected=mismatch_expected,
                        )
                        return
                    if result2.status != "CLOSED":
                        logger.warning(
                            "order_close: re-query after ALREADY_PAID returned %s for order %s; "
                            "deferring local close",
                            result2.status,
                            order_id,
                        )
                        return

        # 3) Confirmed unpaid — flip to closed (double-condition guard)
        no_payment_subq = ~exists().where(
            BillingInvoiceTransaction.invoice_id == invoice.id,
            BillingInvoiceTransaction.status.in_(["succeeded", "refunded"]),
        )
        close_now = utc_naive_now()
        rc2 = await db.execute(
            update(BillingOrder)
            .where(
                BillingOrder.id == order_id,
                BillingOrder.lock_token == my_token,
                BillingOrder.status == "pending",
                no_payment_subq,
            )
            .values(
                status="closed",
                closed_at=close_now,
                lock_token=None,
                locked_until=None,
            )
        )
        if rc2.rowcount > 0:
            await db.execute(
                update(BillingInvoice)
                .where(BillingInvoice.order_id == order_id)
                .values(status="void")
            )
            target_server_id = await db.scalar(
                select(BillingOrder.target_server_id).where(
                    BillingOrder.id == order_id
                )
            )
            # Keep the terminal transition and coupon release in one
            # transaction.  ``release_for_order`` is status-guarded and
            # idempotent; a retry after a crash therefore cannot consume or
            # double-release the coupon.  If the release cannot be flushed,
            # roll back the close so a later job can retry both operations.
            try:
                from app.services.billing import coupons as coupon_svc

                await coupon_svc.release_for_order(
                    db, order_id=order_id, commit=False
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "order_close: coupon release failed for order %s; "
                    "close will be retried",
                    order_id,
                )
                return
            closed_in_this_run = True
        else:
            await db.commit()

        # 4) Cleanup placeholder for new_purchase orders only.
        if closed_in_this_run and target_server_id is not None:
            order_kind = await db.scalar(
                select(BillingOrder.kind).where(BillingOrder.id == order_id)
            )
            if order_kind == "new_purchase":
                try:
                    await server_lifecycle.delete_server(db, target_server_id)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "placeholder cleanup failed for closed order %s: %s",
                        order_id, exc,
                    )
                    await incidents.log_incident(
                        "placeholder_cleanup_failed",
                        order_id=order_id,
                        server_id=target_server_id,
                        payload={"phase": "order_close", "error": str(exc)},
                    )
    finally:
        # 5) Idempotent lock release
        try:
            await db.execute(
                update(BillingOrder)
                .where(
                    BillingOrder.id == order_id,
                    BillingOrder.lock_token == my_token,
                )
                .values(lock_token=None, locked_until=None)
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("order_close: lock release failed for %s", order_id)


# --------------------------------------------------------------------------- #
# order_query — §8.3
# --------------------------------------------------------------------------- #


async def run_order_query() -> None:
    """Catch missed webhooks for pending orders before due_at."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        now = utc_naive_now()
        rows = (
            await db.execute(
                select(
                    BillingOrder.id,
                    BillingInvoice.invoice_no,
                    BillingInvoice.id.label("invoice_id"),
                    BillingInvoice.gateway_code,
                )
                .join(BillingInvoice, BillingInvoice.order_id == BillingOrder.id)
                .where(
                    BillingOrder.status == "pending",
                    BillingInvoice.due_at > now,
                    # Normally a successful create_invoice stores the
                    # gateway-side prepay id.  An ambiguous timeout has no
                    # such id, but orders.py persists gateway_code and the
                    # invoice number so this job can still reconcile a
                    # provider-side trade accepted before the timeout.
                    or_(
                        BillingInvoice.gateway_prepay_id.is_not(None),
                        BillingInvoice.gateway_code.is_not(None),
                    ),
                )
                .limit(_BATCH_LIMIT)
            )
        ).all()

    for order_id, invoice_no, invoice_id, gateway_code in rows:
        async with session_factory() as db:
            try:
                await _query_one_order(
                    db, order_id, invoice_no, invoice_id, gateway_code
                )
            except Exception:
                logger.exception("order_query failed for order %s", order_id)


async def _query_one_order(
    db: AsyncSession,
    order_id: int,
    invoice_no: str,
    invoice_id: int,
    gateway_code: str | None,
) -> None:
    code = gateway_code or "hupijiao"
    await gateway_registry.ensure_loaded(db)
    try:
        gateway = gateway_registry.get(code)
    except KeyError:
        return
    try:
        result = await gateway.query_by_out_trade_no(invoice_no)
    except GatewayError:
        return  # retry next round

    invoice = await db.get(BillingInvoice, invoice_id)
    if invoice is None:
        return

    if result.status == "SUCCESS":
        amount_fen, mismatch_expected = _query_payment_amount(invoice, result)
        await payments.safe_add_payment(
            db,
            invoice,
            gateway_code=code,
            transaction_id=result.transaction_id or "",
            amount_fen=amount_fen,
            raw_event_id=None,
            amount_mismatch_expected=mismatch_expected,
        )
    elif result.status == "CLOSED" and result.transaction_id:
        await payments.mark_transaction_failed(
            db,
            invoice_id,
            result.transaction_id,
            gateway_code=code,
            amount_fen=result.amount_fen or invoice.total_fen,
        )
    # NOTPAY / USERPAYING / NOTFOUND / PROCESSING: ignore until next round.


# --------------------------------------------------------------------------- #
# apply_retry — §9.5
# --------------------------------------------------------------------------- #


async def run_apply_retry() -> None:
    """Re-run apply for processing orders whose lock + next_apply_at allow."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        now = utc_naive_now()
        candidates = (
            await db.execute(
                select(BillingOrder.id).where(
                    BillingOrder.status == "processing",
                    or_(
                        BillingOrder.lock_token.is_(None),
                        BillingOrder.locked_until.is_(None),
                        BillingOrder.locked_until < now,
                    ),
                    or_(
                        BillingOrder.next_apply_at.is_(None),
                        BillingOrder.next_apply_at <= now,
                    ),
                ).limit(_BATCH_LIMIT)
            )
        ).scalars().all()

    for oid in candidates:
        async with session_factory() as db:
            try:
                await apply_paid_order(db, oid, source="retry")
            except Exception:
                logger.exception("apply_retry failed for order %s", oid)


# --------------------------------------------------------------------------- #
# refund_retry — §10.3
# --------------------------------------------------------------------------- #


async def run_refund_retry() -> None:
    """Drive pending/failed refunds forward; the only推动者 (no webhook)."""
    from app.services.billing.refunds import (
        list_pending_refunds,
        reconcile_refund_once,
    )

    session_factory = get_session_factory()
    async with session_factory() as db:
        candidates = await list_pending_refunds(db, limit=_BATCH_LIMIT)
        ids = [r.id for r in candidates]

    for rid in ids:
        async with session_factory() as db:
            try:
                outcome = await reconcile_refund_once(db, rid)
                if outcome != "noop":
                    logger.info("refund_retry refund=%s outcome=%s", rid, outcome)
            except Exception:
                logger.exception("refund_retry failed for refund %s", rid)


async def run_placeholder_leak_monitor() -> None:
    """Detect placeholder rows that violate the design invariant (§4.2 / §13.5).

    Invariant: a ``new_purchase`` order in terminal state ``closed`` /
    ``cancelled`` whose effect was never written must have no surviving
    placeholder ``panel.servers`` row (``external_id LIKE 'pending:%'``)
    pointed to by ``order.target_server_id``. Cleanup on cancel /
    force-close already attempts removal; this job catches code-bug or
    Wings-blip leaks. One ``placeholder_leak`` incident per offending
    order. Self-deduplicates: skips orders already with an *open*
    incident of this kind.
    """
    from app.db.models.billing import BillingIncident, BillingOrderEffect
    from app.db.models.pterodactyl import PteroServer

    session_factory = get_session_factory()
    async with session_factory() as db:
        # Find offending orders. Effect must NOT exist; placeholder server
        # row MUST exist with pending: prefix.
        stmt = (
            select(BillingOrder.id, BillingOrder.target_server_id)
            .join(PteroServer, PteroServer.id == BillingOrder.target_server_id)
            .where(
                BillingOrder.kind == "new_purchase",
                BillingOrder.status.in_(("closed", "cancelled")),
                BillingOrder.target_server_id.is_not(None),
                PteroServer.external_id.like("pending:%"),
                ~exists().where(BillingOrderEffect.order_id == BillingOrder.id),
                # Don't re-raise if there is already an open incident.
                ~exists().where(
                    (BillingIncident.order_id == BillingOrder.id)
                    & (BillingIncident.kind == "placeholder_leak")
                    & (BillingIncident.status == "open")
                ),
            )
            .limit(_BATCH_LIMIT)
        )
        rows = (await db.execute(stmt)).all()

    if not rows:
        return

    logger.warning("placeholder_leak_monitor: %d order(s) flagged", len(rows))
    for order_id, server_id in rows:
        await incidents.log_incident(
            "placeholder_leak",
            order_id=order_id,
            server_id=server_id,
            payload={
                "reason": "terminal order has surviving placeholder server",
                "order_status_set": ["closed", "cancelled"],
            },
        )
