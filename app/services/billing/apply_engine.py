"""Apply engine — see ``docs/BILLING_DESIGN.md`` §9.

Single public coroutine :func:`apply_paid_order` that drives a paid
order through the four-stage idempotent flow:

1. **I1 验证** — there must be at least one ``succeeded`` or ``refunded``
   transaction for the order; nudge ``status: pending → processing``.
2. **I3 抢锁** — ``lock_token`` + ``locked_until`` + ``next_apply_at``
   gates concurrent retries.
3. **业务效果 + 后置动作** — three convergent paths:
   * Path A: no effect row yet — write effect, then post-actions.
   * Path B: effect row but post-actions undone — re-run post-actions.
   * Path C: both done — straight to applied.
4. **processing → applied** — terminal transition, audit + email.

Failures route through :func:`_record_failure_and_release` (retryable,
exponential backoff) or :func:`_terminate_apply` (orphan resource etc.).

The ``source`` parameter is purely audit metadata. Only ``admin-force``
(handled in §11, not here) bypasses ``next_apply_at`` — webhook /
order_query / retry all respect it identically.
"""

from __future__ import annotations

import enum
import logging
import uuid
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import exists, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import (
    BillingInvoice,
    BillingInvoiceTransaction,
    BillingOrder,
    BillingOrderEffect,
)
from app.db.models.manager import ServerMeta
from app.db.models.pterodactyl import PteroServer
from app.services import server_lifecycle
from app.services.audit import log_manager_activity
from app.services.billing import incidents
from app.services.wings import WingsServiceError, wings_service

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants — see §9.1
# --------------------------------------------------------------------------- #

# 1m, 5m, 15m, 1h, 4h
RETRY_DELAYS = [60, 5 * 60, 15 * 60, 60 * 60, 4 * 60 * 60]
APPLY_LEASE_SECONDS = 5 * 60
"""Lock lease for apply runs. After expiry another worker may take over."""


# --------------------------------------------------------------------------- #
# Result enum + exceptions
# --------------------------------------------------------------------------- #


class ApplyResult(str, enum.Enum):
    APPLIED = "applied"
    NOT_PAID = "not_paid"
    NOT_OUR_BUSINESS = "not_our_business"
    LOCK_NOT_ACQUIRED = "lock_not_acquired"
    LOCK_LOST = "lock_lost"
    RETRY_SCHEDULED = "retry_scheduled"
    PERMANENT_FAILURE = "permanent_failure"


class ApplyError(Exception):
    """Recoverable error during business-effect commit; triggers retry."""


class ApplyOrphanError(Exception):
    """Unrecoverable: the order's target resource is gone (e.g. user
    deleted server before apply ran). Routed to terminal apply_failed
    immediately, no retry."""


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #


async def apply_paid_order(
    db: AsyncSession,
    order_id: int,
    *,
    source: Literal["callback", "query", "retry", "admin-force"],
) -> ApplyResult:
    """Drive a paid order to ``applied`` (or schedule retry / fail)."""
    now = utc_naive_now()

    # ── Stage 1: I1 fact check + push to processing
    if not await _has_succeeded_payment(db, order_id):
        return ApplyResult.NOT_PAID

    await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.status == "pending",
        )
        .values(status="processing")
    )
    await db.commit()

    order = await db.get(BillingOrder, order_id)
    if order is None or order.status != "processing":
        # Already applied / cancelled / refunded / closed / etc.
        return ApplyResult.NOT_OUR_BUSINESS

    # ── Stage 2: claim lock (I3)
    my_token = uuid.uuid4().hex
    rc = await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
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
        )
        .values(
            lock_token=my_token,
            locked_until=now + timedelta(seconds=APPLY_LEASE_SECONDS),
        )
    )
    await db.commit()
    if rc.rowcount == 0:
        return ApplyResult.LOCK_NOT_ACQUIRED

    # Re-fetch with lock-acquired snapshot.
    await db.refresh(order)

    # ── Stage 3: business effect + post actions
    effect = await db.get(BillingOrderEffect, order_id)
    server_id: int | None = None
    if effect is None:
        # Path A
        try:
            server_id = await _commit_business_effect(db, order)
        except ApplyOrphanError as exc:
            return await _terminate_apply(
                db, order, exc, my_token, reason="orphan_resource"
            )
        except Exception as exc:  # noqa: BLE001
            return await _record_failure_and_release(db, order, exc, my_token)

        try:
            await _run_post_actions(db, order, server_id)
        except Exception as exc:  # noqa: BLE001
            return await _record_failure_and_release(db, order, exc, my_token)
        await _mark_post_actions_done(db, order_id)
    elif effect.post_actions_done_at is None:
        # Path B
        try:
            await _run_post_actions(db, order, effect.server_id)
        except Exception as exc:  # noqa: BLE001
            return await _record_failure_and_release(db, order, exc, my_token)
        await _mark_post_actions_done(db, order_id)
    # Path C: nothing to do, just close out below.

    # ── Stage 4: processing → applied
    apply_now = utc_naive_now()
    rc = await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.lock_token == my_token,
        )
        .values(
            status="applied",
            applied_at=apply_now,
            lock_token=None,
            locked_until=None,
            next_apply_at=None,
            last_apply_error=None,
        )
    )
    await db.commit()
    if rc.rowcount == 0:
        return ApplyResult.LOCK_LOST

    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        status="success",
        detail_key="billing.order.applied",
        detail_params={
            "order_id": order_id,
            "source": source,
            "retries": order.apply_retry_count,
        },
    )
    # NOTE: 'orderPaid' email template lives in Phase B (post-MVP).
    try:
        from app.services.billing import notify

        await notify.notify_order_paid(order_id)
    except Exception:  # noqa: BLE001 - email is best-effort
        logger.exception("notify_order_paid failed for order %s", order_id)
    return ApplyResult.APPLIED


# --------------------------------------------------------------------------- #
# Stage helpers
# --------------------------------------------------------------------------- #


async def _has_succeeded_payment(db: AsyncSession, order_id: int) -> bool:
    """I1: at least one succeeded/refunded transaction on any of the
    order's invoices (refunded still counts as 'we received money')."""
    found = await db.scalar(
        select(
            exists().where(
                BillingInvoiceTransaction.invoice_id.in_(
                    select(BillingInvoice.id).where(
                        BillingInvoice.order_id == order_id
                    )
                ),
                BillingInvoiceTransaction.status.in_(["succeeded", "refunded"]),
            )
        )
    )
    return bool(found)


# --------------------------------------------------------------------------- #
# Business effects
# --------------------------------------------------------------------------- #


async def _commit_business_effect(db: AsyncSession, order: BillingOrder) -> int:
    if order.kind == "renew":
        return await _effect_renew(db, order)
    elif order.kind == "upgrade":
        return await _effect_upgrade(db, order)
    else:  # new_purchase
        return await _effect_new_purchase(db, order)


def _local_today() -> date:
    """Local-day 'today' — billing periods are day-granular and the
    business definition lives in local time, not UTC."""
    return date.today()


async def _effect_upgrade(db: AsyncSession, order: BillingOrder) -> int:
    """Upgrade = prorated plan switch with resource/build updates only.

    No expiration_date change, no Wings container removal, no startup/image
    change (upgrade keeps the server's existing image and startup command).
    """
    if order.target_server_id is None:
        raise ApplyOrphanError(f"upgrade order {order.id} 缺少 target_server_id")

    server = await db.get(PteroServer, order.target_server_id)
    if server is None:
        raise ApplyOrphanError(f"server {order.target_server_id} 已删除")

    snap = order.plan_snapshot or {}

    from app.services import server_management  # local import

    try:
        await server_management.update_build(
            db, server.id,
            cpu=snap.get("cpu"),
            memory=snap.get("memory_mb"),
            disk=snap.get("disk_mb"),
            swap=snap.get("swap_mb"),
            io=snap.get("io"),
            database_limit=snap.get("database_limit"),
            backup_limit=snap.get("backup_limit"),
            allocation_limit=snap.get("allocation_limit"),
            oom_disabled=snap.get("oom_disabled"),
        )
        # Update plan binding (don't touch expiration)
        meta = await db.scalar(
            select(ServerMeta)
            .where(ServerMeta.server_id == server.id)
            .with_for_update()
        )
        if meta is None:
            meta = ServerMeta(server_id=server.id)
        old_plan_id = meta.plan_id
        meta.plan_id = snap.get("plan_id") or order.plan_id
        db.add(meta)
        await db.commit()

        # Write effect row for audit/reversal trail
        now = utc_naive_now()
        db.add(
            BillingOrderEffect(
                order_id=order.id,
                server_id=server.id,
                effect_type="upgrade",
                days=0,  # upgrade doesn't add days
                prev_expiration_date=server.expiration_date,
                new_expiration_date=server.expiration_date,  # no change
                effect_committed_at=now,
                post_actions_done_at=None,
            )
        )
        await db.commit()

        return server.id

    except Exception:
        # server_management functions already do compensation rollback on
        # their own; we just let it bubble up to _record_failure_and_release.
        raise


async def _effect_renew(db: AsyncSession, order: BillingOrder) -> int:
    """Renew = bought time only. Touches no Wings, no resources, no plan_id."""
    if order.target_server_id is None:
        raise ApplyOrphanError(f"renew order {order.id} 缺少 target_server_id")

    meta = await db.scalar(
        select(ServerMeta)
        .where(ServerMeta.server_id == order.target_server_id)
        .with_for_update()
    )
    if meta is None:
        raise ApplyOrphanError(
            f"server {order.target_server_id} 已删除"
        )

    today = _local_today()
    prev = meta.expiration_date
    base = prev if prev and prev > today else today
    new_date = base + timedelta(days=order.total_days)

    db.add(
        BillingOrderEffect(
            order_id=order.id,
            server_id=order.target_server_id,
            effect_type="renew",
            days=order.total_days,
            prev_expiration_date=prev,
            new_expiration_date=new_date,
            effect_committed_at=utc_naive_now(),
            post_actions_done_at=None,
        )
    )
    meta.expiration_date = new_date
    await db.commit()
    return order.target_server_id


async def _effect_new_purchase(db: AsyncSession, order: BillingOrder) -> int:
    """Placeholder server → live server: first Wings push + external_id flip
    + meta.expiration_date + meta.plan_id binding."""
    server_id = order.target_server_id
    if server_id is None:
        raise ApplyOrphanError(f"order {order.id} 占位行丢失")

    server = await db.get(PteroServer, server_id)
    if server is None:
        raise ApplyOrphanError(f"placeholder server {server_id} 不存在")

    target_external = f"order:{order.id}"
    # Idempotency: external_id already promoted + effect row exists → done.
    if server.external_id == target_external:
        existing = await db.scalar(
            select(BillingOrderEffect).where(
                BillingOrderEffect.order_id == order.id
            )
        )
        if existing is not None:
            return server_id

    # 1) Outside-tx Wings push (idempotent — Wings returns OK on duplicate uuid).
    try:
        await wings_service.create_server(db, server.node_id, server.uuid)
    except WingsServiceError as exc:
        # Placeholder row stays in panel; retry cycles will re-attempt.
        raise ApplyError(f"wings.create_server 失败: {exc}") from exc

    # 2) In-tx: flip external_id, write effect row, set meta + plan_id binding.
    new_date = _local_today() + timedelta(days=order.total_days)
    now = utc_naive_now()
    await db.execute(
        update(PteroServer)
        .where(PteroServer.id == server_id)
        .values(external_id=target_external, updated_at=now)
    )
    db.add(
        BillingOrderEffect(
            order_id=order.id,
            server_id=server_id,
            effect_type="new_purchase",
            days=order.total_days,
            prev_expiration_date=None,
            new_expiration_date=new_date,
            effect_committed_at=now,
            post_actions_done_at=None,
        )
    )
    # Read plan_id from the immutable snapshot rather than the live FK so
    # that admin plan deletes between order placement and apply still bind
    # the server to its purchased plan id.
    snap_plan_id = (order.plan_snapshot or {}).get("plan_id") or order.plan_id
    await _upsert_meta_expiration_and_plan(
        db, server_id, new_date, snap_plan_id
    )
    await db.commit()
    return server_id


async def _upsert_meta_expiration_and_plan(
    db: AsyncSession,
    server_id: int,
    expiration: date,
    plan_id: int,
) -> None:
    """INSERT ... ON DUPLICATE KEY UPDATE for manager_server_meta."""
    await db.execute(
        text(
            """
            INSERT INTO manager_server_meta (server_id, expiration_date, plan_id)
            VALUES (:sid, :exp, :pid)
            ON DUPLICATE KEY UPDATE
              expiration_date = VALUES(expiration_date),
              plan_id = VALUES(plan_id)
            """
        ).bindparams(sid=server_id, exp=expiration, pid=plan_id)
    )


# --------------------------------------------------------------------------- #
# Post-actions
# --------------------------------------------------------------------------- #


async def _run_post_actions(
    db: AsyncSession, order: BillingOrder, server_id: int
) -> None:
    effect = await db.get(BillingOrderEffect, order.id)
    if effect is None:  # pragma: no cover — caller ensures effect exists
        raise ApplyError(f"order {order.id} 后置动作: effect 行丢失")

    # 1) Sync panel description's 到期 line.
    await server_lifecycle.update_server_expiration_description(
        db, server_id, effect.new_expiration_date
    )
    await db.commit()

    # 2) Unsuspend if needed (idempotent — §0 commitment #1).
    server = await db.get(PteroServer, server_id)
    if server is not None and server.is_suspended:
        await server_lifecycle.unsuspend_server(db, server_id)


async def _mark_post_actions_done(db: AsyncSession, order_id: int) -> None:
    await db.execute(
        update(BillingOrderEffect)
        .where(BillingOrderEffect.order_id == order_id)
        .values(post_actions_done_at=utc_naive_now())
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #


async def _record_failure_and_release(
    db: AsyncSession,
    order: BillingOrder,
    exc: Exception,
    my_token: str,
) -> ApplyResult:
    logger.exception("apply failed for order %s", order.id)
    terminal = False
    last_error = str(exc)[:500]

    row = await db.scalar(
        select(BillingOrder)
        .where(
            BillingOrder.id == order.id,
            BillingOrder.lock_token == my_token,
        )
        .with_for_update()
    )
    if row is None:
        await db.rollback()
        return ApplyResult.LOCK_LOST

    row.last_apply_error = last_error
    row.apply_retry_count = (row.apply_retry_count or 0) + 1
    row.lock_token = None
    row.locked_until = None
    if row.apply_retry_count > len(RETRY_DELAYS):
        row.status = "apply_failed"
        row.next_apply_at = None
        terminal = True
    else:
        delay = RETRY_DELAYS[row.apply_retry_count - 1]
        row.next_apply_at = utc_naive_now() + timedelta(seconds=delay)
    await db.commit()

    if terminal:
        await incidents.log_incident(
            "apply_retries_exhausted",
            order_id=order.id,
            payload={"last_error": last_error},
        )
        await log_manager_activity(
            db,
            actor="system",
            category="billing",
            status="failed",
            detail_key="billing.order.apply_failed",
            detail_params={"order_id": order.id, "error": last_error},
        )
        try:
            from app.services.billing import notify

            await notify.notify_order_apply_failed(order.id)
            await notify.notify_order_apply_alert(order.id)
        except Exception:  # noqa: BLE001 - email is best-effort
            logger.exception(
                "notify apply_failed/alert failed for order %s", order.id
            )
        return ApplyResult.PERMANENT_FAILURE
    # First retry failure (apply_retry_count == 1) → admin alert per §14.
    if (row.apply_retry_count or 0) == 1:
        try:
            from app.services.billing import notify

            await notify.notify_order_apply_alert(order.id)
        except Exception:  # noqa: BLE001 - email is best-effort
            logger.exception(
                "notify apply_alert (first failure) failed for order %s",
                order.id,
            )
    return ApplyResult.RETRY_SCHEDULED


async def _terminate_apply(
    db: AsyncSession,
    order: BillingOrder,
    exc: Exception,
    my_token: str,
    *,
    reason: str,
) -> ApplyResult:
    """Unrecoverable orphan — straight to apply_failed, no retry."""
    logger.error("apply terminated for order %s: %s", order.id, exc)
    last_error = f"{reason}: {exc}"[:500]

    row = await db.scalar(
        select(BillingOrder)
        .where(
            BillingOrder.id == order.id,
            BillingOrder.lock_token == my_token,
        )
        .with_for_update()
    )
    if row is None:
        await db.rollback()
        return ApplyResult.LOCK_LOST

    row.status = "apply_failed"
    row.last_apply_error = last_error
    row.next_apply_at = None
    row.lock_token = None
    row.locked_until = None
    await db.commit()

    await incidents.log_incident(
        "apply_retries_exhausted",
        order_id=order.id,
        payload={"reason": reason, "error": last_error},
    )
    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        status="failed",
        detail_key="billing.order.apply_terminated",
        detail_params={"order_id": order.id, "reason": reason},
    )
    return ApplyResult.PERMANENT_FAILURE
