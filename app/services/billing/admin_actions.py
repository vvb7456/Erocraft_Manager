"""Admin manual-intervention actions on orders — see ``BILLING_DESIGN.md`` §11.

Three actions:

* :func:`force_apply` (§11.3) — push a manual_review/apply_failed order
  through ``apply_paid_order(source='admin-force')``; resets retry state
  so the next attempt is unconditional.
* :func:`force_close` (§11.4) — terminal close on manual_review/apply_failed.
  Resolves any open incidents on the order. If the placeholder server
  exists and effect is unwritten, attempts cleanup; failure → incident.
* :func:`cleanup_placeholder` (§11.5) — release a stranded placeholder
  server row without touching order/funds. Idempotent: missing or
  already-cleaned placeholder returns successfully.

All three return on success (``force_apply`` returns the
:class:`apply_engine.ApplyResult`; the other two return ``None``);
failures raise the :class:`AdminActionError` subclasses for the router
to map to HTTP codes.
"""

from __future__ import annotations

import logging

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import (
    BillingIncident,
    BillingOrder,
    BillingOrderEffect,
)
from app.db.models.pterodactyl import PteroServer
from app.services import server_lifecycle
from app.services.billing import apply_engine, incidents

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


class CannotCleanupPlaceholder(AdminActionError):
    """Order exists but state forbids cleanup — HTTP 409."""


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
    await db.commit()
    # Outside the rowcount tx so apply_paid_order's own tx semantics apply.
    result = await apply_engine.apply_paid_order(db, order_id, source="admin-force")

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

    target_sid = await db.scalar(
        select(BillingOrder.target_server_id).where(BillingOrder.id == order_id)
    )
    effect_exists = bool(
        await db.scalar(
            select(exists().where(BillingOrderEffect.order_id == order_id))
        )
    )
    await db.commit()

    # Same separation as §10.4: only nuke the placeholder when effect not written.
    if target_sid is not None and not effect_exists:
        try:
            await server_lifecycle.delete_server(db, target_sid)
        except Exception as exc:  # noqa: BLE001 — best-effort, incident records details
            logger.exception(
                "force_close placeholder cleanup failed order=%s server=%s",
                order_id,
                target_sid,
            )
            await incidents.log_incident(
                "placeholder_cleanup_failed",
                order_id=order_id,
                server_id=target_sid,
                payload={"phase": "force_close", "error": str(exc)[:500]},
            )
    logger.info(
        "force_close executed by admin=%s order=%s note=%s",
        admin_id,
        order_id,
        note,
    )


# --------------------------------------------------------------------------- #
# §11.5 cleanup_placeholder
# --------------------------------------------------------------------------- #


async def cleanup_placeholder(
    db: AsyncSession, order_id: int, *, admin_id: int | None
) -> None:
    """Release a stranded placeholder server. Does NOT touch order/funds."""
    order = await db.scalar(
        select(BillingOrder).where(BillingOrder.id == order_id)
    )
    if order is None:
        raise OrderNotFound("订单不存在")
    if order.target_server_id is None:
        raise CannotCleanupPlaceholder("订单没有关联占位服务器")

    effect_exists = bool(
        await db.scalar(
            select(exists().where(BillingOrderEffect.order_id == order_id))
        )
    )
    if effect_exists:
        raise CannotCleanupPlaceholder(
            "订单已开通，请改用 DELETE /admin/servers/:id 删除服务器"
        )

    server = await db.scalar(
        select(PteroServer).where(PteroServer.id == order.target_server_id)
    )
    if server is None:
        # Idempotent: another path already cleaned it up.
        logger.info(
            "cleanup_placeholder noop (server gone) order=%s admin=%s",
            order_id,
            admin_id,
        )
        return

    if not (server.external_id or "").startswith("pending:"):
        raise CannotCleanupPlaceholder(
            "对应服务器已转正（external_id 不是 pending: 前缀），不可走清占位流程"
        )

    try:
        await server_lifecycle.delete_server(db, order.target_server_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "cleanup_placeholder delete failed order=%s server=%s",
            order_id,
            order.target_server_id,
        )
        await incidents.log_incident(
            "placeholder_cleanup_failed",
            order_id=order_id,
            server_id=order.target_server_id,
            payload={"phase": "cleanup_placeholder", "error": str(exc)[:500]},
        )
        raise CannotCleanupPlaceholder(
            f"释放占位服务器失败：{exc}"
        ) from exc

    logger.info(
        "cleanup_placeholder ok order=%s server=%s admin=%s",
        order_id,
        order.target_server_id,
        admin_id,
    )
