"""Payment fact recording — see ``docs/BILLING_DESIGN.md`` §7.3 / §7.4.

Two public coroutines:

* :func:`add_payment` — idempotent fund-fact insert + invoice/order
  transition. Triggers :func:`apply_paid_order` when an invoice flips to
  ``paid``. Implements the manual_review branches (amount mismatch /
  late payment) per §7.3.
* :func:`mark_transaction_failed` — record a CLOSED/PAYERROR fund fact
  (idempotent on ``(gateway_code, transaction_id)``).

A small :func:`_safe_add_payment` helper wraps :func:`add_payment` so
``order_close`` / ``cancel_order`` / ``order_query`` can convert
:class:`CrossInvoiceTransactionError` into a manual_review incident
without bubbling out (per §8.1).

I3/I5: the fund insert path uses a SAVEPOINT to convert IntegrityError
on the unique ``(gateway_code, transaction_id)`` index into a clean
"already-recorded" return without poisoning the outer tx.

I4 caveat: ``add_payment`` writes to DB only — the actual gateway HTTP
call happens in the caller (webhook handler / order_query) before
invoking us with the result.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from sqlalchemy import exists, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import (
    BillingInvoice,
    BillingInvoiceTransaction,
    BillingOrder,
)
from app.services.billing import incidents

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class CrossInvoiceTransactionError(Exception):
    """Same gateway transaction_id seen against a different invoice / amount.

    The caller (webhook / cancel / order_query) must catch this and write
    a ``manual_review_required`` incident — the fund fact is intentionally
    NOT inserted in this case (the existing row is the source of truth).
    """

    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__(
            f"cross-invoice transaction conflict: {detail!r}"
        )
        self.detail = detail


# --------------------------------------------------------------------------- #
# Public: add_payment
# --------------------------------------------------------------------------- #


async def add_payment(
    db: AsyncSession,
    invoice_id: int,
    *,
    gateway_code: str,
    transaction_id: str,
    amount_fen: int,
    raw_event_id: int | None,
    amount_mismatch_expected: int | None = None,
) -> BillingInvoiceTransaction:
    """Record a successful payment fact and (if appropriate) trigger apply.

    Idempotent on ``(gateway_code, transaction_id)``. Returns the
    transaction row (existing or newly inserted).

    Raises :class:`CrossInvoiceTransactionError` when an existing row has
    the same ``transaction_id`` but a different ``invoice_id`` or
    ``amount_fen`` (caller writes the manual_review incident).

    Manual review branches (per §7.3):

    * ``amount_mismatch`` — caller passed ``amount_mismatch_expected``
      (gateway reported amount differs from invoice.total_fen).
    * ``late_payment_on_void`` — invoice already void or order in a
      terminal state (closed/cancelled).
    * ``late_payment_on_refunded`` — order already refunded.

    In all manual-review branches the fund fact still lands in the
    transaction table and ``order.received_fen`` still increments
    (I5: 资金事实优先), but invoice/order do NOT advance, and we drop
    a ``manual_review_required`` incident outside the tx.
    """
    now = utc_naive_now()
    need_manual_review: str | None = None
    amount_mismatch = amount_mismatch_expected is not None

    # ── 1) Look up existing tx (idempotency check)
    existing = await db.scalar(
        select(BillingInvoiceTransaction)
        .where(
            BillingInvoiceTransaction.gateway_code == gateway_code,
            BillingInvoiceTransaction.transaction_id == transaction_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.invoice_id != invoice_id
            or existing.amount_fen != amount_fen
        ):
            await db.rollback()
            raise CrossInvoiceTransactionError(
                {
                    "incoming_invoice_id": invoice_id,
                    "existing_invoice_id": existing.invoice_id,
                    "incoming_amount_fen": amount_fen,
                    "existing_amount_fen": existing.amount_fen,
                    "transaction_id": transaction_id,
                    "gateway_code": gateway_code,
                }
            )
        return existing

    # ── 2) INSERT under SAVEPOINT to absorb IntegrityError on unique index
    try:
        async with db.begin_nested():
            tx = BillingInvoiceTransaction(
                invoice_id=invoice_id,
                gateway_code=gateway_code,
                transaction_id=transaction_id,
                amount_fen=amount_fen,
                status="succeeded",
                raw_event_id=raw_event_id,
                created_at=now,
                updated_at=now,
            )
            db.add(tx)
            await db.flush()
    except IntegrityError:
        # Another worker raced us; re-fetch and validate.
        existing = await db.scalar(
            select(BillingInvoiceTransaction)
            .where(
                BillingInvoiceTransaction.gateway_code == gateway_code,
                BillingInvoiceTransaction.transaction_id == transaction_id,
            )
            .with_for_update()
        )
        assert existing is not None
        if (
            existing.invoice_id != invoice_id
            or existing.amount_fen != amount_fen
        ):
            await db.rollback()
            raise CrossInvoiceTransactionError(
                {
                    "incoming_invoice_id": invoice_id,
                    "existing_invoice_id": existing.invoice_id,
                    "incoming_amount_fen": amount_fen,
                    "existing_amount_fen": existing.amount_fen,
                    "transaction_id": transaction_id,
                    "gateway_code": gateway_code,
                }
            )
        return existing

    # ── 3) Lock invoice + order
    invoice = await db.scalar(
        select(BillingInvoice).where(BillingInvoice.id == invoice_id).with_for_update()
    )
    if invoice is None:  # pragma: no cover — caller ensures invoice exists
        await db.rollback()
        raise RuntimeError(f"invoice {invoice_id} disappeared during add_payment")

    order = await db.scalar(
        select(BillingOrder)
        .where(BillingOrder.id == invoice.order_id)
        .with_for_update()
    )
    if order is None:  # pragma: no cover
        await db.rollback()
        raise RuntimeError(f"order {invoice.order_id} disappeared during add_payment")

    # ── 4) Materialize order.received_fen (monotonic, never decreased on refund)
    order.received_fen = (order.received_fen or 0) + amount_fen

    # ── 5) Detect manual-review branch
    if amount_mismatch:
        need_manual_review = "amount_mismatch"
        if order.status not in ("manual_review", "refunded"):
            order.status = "manual_review"
    elif invoice.status == "void" or order.status in ("closed", "cancelled"):
        need_manual_review = "late_payment_on_void_invoice"
        if order.status not in ("manual_review", "refunded"):
            order.status = "manual_review"
    elif order.status == "refunded":
        need_manual_review = "late_payment_on_refunded_order"
        # ``refunded`` is a terminal status; we deliberately do NOT promote
        # it to ``manual_review``. The fund fact + incident below still
        # capture the anomaly for ops.
    else:
        # Normal path: recompute remaining + maybe flip invoice → paid
        succeeded_total = await db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        BillingInvoiceTransaction.amount_fen
                        - BillingInvoiceTransaction.refunded_fen
                    ),
                    0,
                )
            ).where(
                BillingInvoiceTransaction.invoice_id == invoice_id,
                BillingInvoiceTransaction.status.in_(["succeeded", "refunded"]),
            )
        )
        remaining = invoice.total_fen - int(succeeded_total or 0)
        if remaining <= 0 and invoice.status == "pending":
            invoice.status = "paid"
            invoice.paid_at = now

    invoice_paid_now = (
        need_manual_review is None
        and invoice.status == "paid"
        and invoice.paid_at == now
    )
    order_id_for_apply = order.id

    await db.commit()

    # ── 6) Outside tx: incident for manual-review branches
    if need_manual_review is not None:
        payload: dict[str, Any] = {
            "subkind": need_manual_review,
            "gateway_transaction_id": transaction_id,
            "amount_fen": amount_fen,
        }
        if amount_mismatch:
            payload["expected"] = amount_mismatch_expected
        await incidents.log_incident(
            "manual_review_required",
            invoice_id=invoice_id,
            order_id=order_id_for_apply,
            transaction_id=tx.id,
            payload=payload,
        )
        return tx

    # ── 7) Trigger apply (only when this call flipped invoice → paid)
    if invoice_paid_now:
        # Late import to avoid circular dependency.
        from app.services.billing import apply_engine

        try:
            await apply_engine.apply_paid_order(
                db, order_id_for_apply, source="callback"
            )
        except Exception:
            logger.exception(
                "apply_paid_order raised after add_payment for order %s",
                order_id_for_apply,
            )
            # apply_engine handles its own retry scheduling; never propagate
            # to the caller (webhook handler must always return 200).

    return tx


# --------------------------------------------------------------------------- #
# Public: mark_transaction_failed
# --------------------------------------------------------------------------- #


async def mark_transaction_failed(
    db: AsyncSession,
    invoice_id: int,
    transaction_id: str,
    *,
    gateway_code: str,
    amount_fen: int,
) -> BillingInvoiceTransaction:
    """Record a CLOSED / PAYERROR fund-failure fact (§7.4).

    Idempotent on ``(gateway_code, transaction_id)``. ``amount_fen`` is
    a placeholder when the gateway didn't tell us; it never participates
    in invoice.remaining_fen accounting (failed transactions are excluded
    from the sum).
    """
    existing = await db.scalar(
        select(BillingInvoiceTransaction)
        .where(
            BillingInvoiceTransaction.gateway_code == gateway_code,
            BillingInvoiceTransaction.transaction_id == transaction_id,
        )
        .with_for_update()
    )
    if existing is not None:
        return existing

    now = utc_naive_now()
    try:
        async with db.begin_nested():
            tx = BillingInvoiceTransaction(
                invoice_id=invoice_id,
                gateway_code=gateway_code,
                transaction_id=transaction_id,
                amount_fen=amount_fen,
                status="failed",
                raw_event_id=None,
                created_at=now,
                updated_at=now,
            )
            db.add(tx)
            await db.flush()
        await db.commit()
        return tx
    except IntegrityError:
        existing = await db.scalar(
            select(BillingInvoiceTransaction).where(
                BillingInvoiceTransaction.gateway_code == gateway_code,
                BillingInvoiceTransaction.transaction_id == transaction_id,
            )
        )
        assert existing is not None
        return existing


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def safe_add_payment(
    db: AsyncSession,
    invoice: BillingInvoice,
    *,
    gateway_code: str,
    transaction_id: str,
    amount_fen: int,
    raw_event_id: int | None = None,
    amount_mismatch_expected: int | None = None,
) -> BillingInvoiceTransaction | None:
    """Wrapper that converts :class:`CrossInvoiceTransactionError` into
    a manual_review incident — used by ``order_close`` / ``cancel_order``
    / ``order_query`` per §8.1 / §8.2 / §8.3.

    Returns the transaction on success or None on cross-invoice conflict.
    """
    try:
        return await add_payment(
            db,
            invoice.id,
            gateway_code=gateway_code,
            transaction_id=transaction_id,
            amount_fen=amount_fen,
            raw_event_id=raw_event_id,
            amount_mismatch_expected=amount_mismatch_expected,
        )
    except CrossInvoiceTransactionError as exc:
        await incidents.log_incident(
            "manual_review_required",
            invoice_id=invoice.id,
            order_id=invoice.order_id,
            payload={"subkind": "cross_invoice_transaction", **exc.detail},
        )
        return None
