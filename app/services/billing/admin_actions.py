"""Admin manual-intervention actions on orders — see ``BILLING_DESIGN.md`` §11.

Two actions:

* :func:`force_apply` (§11.3) — push a manual_review/apply_failed order
  through ``apply_paid_order(source='admin-force')``; resets retry state
  so the next attempt is unconditional.
* :func:`force_close` (§11.4) — terminal close on manual_review/apply_failed.
  Resolves any open incidents on the order and releases reserved allocations
  in the same transaction.

``force_apply`` returns the :class:`apply_engine.ApplyResult`; ``force_close``
returns ``None``; failures raise :class:`AdminActionError` subclasses for the
router to map to HTTP codes.
"""

from __future__ import annotations

import logging

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import (
    BillingIncident,
    BillingOrder,
)
from app.db.repositories.allocation_reservations import (
    promote_order_reservations,
    release_order_reservations,
)
from app.services.billing import apply_engine

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class AdminActionError(Exception):
    """Base for admin-action failures with user-facing Chinese message."""


class OrderNotFound(AdminActionError):
    """Path-param order_id does not exist — router maps to HTTP 404."""


class CannotForceApply(AdminActionError):
    """Order exists but state forbids force-apply — HTTP 409."""


class CannotForceClose(AdminActionError):
    """Order exists but state forbids force-close — HTTP 409."""


async def _ensure_order_exists(db: AsyncSession, order_id: int) -> None:
    found = await db.scalar(
        select(exists().where(BillingOrder.id == order_id))
    )
    if not found:
        raise OrderNotFound("订单不存在")


# --------------------------------------------------------------------------- #
# §11.3 force_apply
# --------------------------------------------------------------------------- #


async def force_apply(
    db: AsyncSession, order_id: int, *, admin_id: int | None
) -> apply_engine.ApplyResult:
    """manual_review / apply_failed → processing, then immediate apply.

    Returns the :class:`ApplyResult` from the synchronous apply call so the
    caller can surface the real outcome (applied / retry_scheduled / failed /
    etc.) back to the admin UI.
    """
    await _ensure_order_exists(db, order_id)
    if not await apply_engine.has_usable_payment(db, order_id):
        raise CannotForceApply("该订单没有可用于交付的付款，请先核对退款结果")
    rc = await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.status.in_(("manual_review", "apply_failed")),
        )
        .values(
            status="processing",
            next_apply_at=None,
            apply_retry_count=0,
            last_apply_error=None,
        )
    )
    if rc.rowcount == 0:
        raise CannotForceApply(
            "订单当前状态不允许强制开通（仅 manual_review / apply_failed 可用）"
        )
    await promote_order_reservations(db, order_id)
    await db.commit()
    # Outside the rowcount tx so apply_paid_order's own tx semantics apply.
    result = await apply_engine.apply_paid_order(db, order_id, source="admin-force")

    if result != apply_engine.ApplyResult.APPLIED:
        return result

    # Auto-resolve open incidents on this order
    now = utc_naive_now()
    await db.execute(
        update(BillingIncident)
        .where(
            BillingIncident.order_id == order_id,
            BillingIncident.status == "open",
        )
        .values(
            status="resolved",
            resolution_note=f"force_apply by admin #{admin_id}",
            resolved_by=admin_id,
            resolved_at=now,
        )
    )
    await db.commit()

    logger.info(
        "force_apply executed by admin=%s order=%s result=%s",
        admin_id, order_id, result.value,
    )
    return result


# --------------------------------------------------------------------------- #
# §11.4 force_close
# --------------------------------------------------------------------------- #


async def force_close(
    db: AsyncSession, order_id: int, *, admin_id: int | None, note: str
) -> None:
    """Terminal close on manual_review / apply_failed; resolves incidents."""
    await _ensure_order_exists(db, order_id)
    order = await db.get(BillingOrder, order_id)
    order_kind = order.kind if order is not None else None
    residual_server_id = order.target_server_id if order is not None else None
    now = utc_naive_now()
    rc = await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.status.in_(("manual_review", "apply_failed")),
        )
        .values(status="closed", closed_at=now)
    )
    if rc.rowcount == 0:
        raise CannotForceClose(
            "订单当前状态不允许强制关单（仅 manual_review / apply_failed 可用）"
        )

    # Resolve any open incidents on this order (audit trail of who/why).
    await db.execute(
        update(BillingIncident)
        .where(
            BillingIncident.order_id == order_id,
            BillingIncident.status == "open",
        )
        .values(
            status="resolved",
            resolution_note=note,
            resolved_by=admin_id,
            resolved_at=now,
        )
    )
    await release_order_reservations(db, order_id)

    await db.commit()
    if order_kind == "new_purchase" and residual_server_id is not None:
        from app.services.billing.orders import cleanup_unapplied_order

        await cleanup_unapplied_order(order_id)
    logger.info(
        "force_close executed by admin=%s order=%s note=%s",
        admin_id,
        order_id,
        note,
    )
