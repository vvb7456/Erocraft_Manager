"""Apply engine — see ``docs/BILLING_DESIGN.md`` §9.

Single public coroutine :func:`apply_paid_order` that drives a paid
order through the four-stage idempotent flow:

1. **I1 验证** — 订单等待交付，且存在未退回、未进入退款的有效付款。
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
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ErrorInfo, OperationResult
from app.core.time import utc_naive_now
from app.db.models.billing import (
    BillingInvoice,
    BillingInvoiceTransaction,
    BillingOrder,
    BillingOrderEffect,
    BillingPayment,
    BillingRefund,
)
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.db.repositories.allocation_reservations import (
    InsufficientAllocationsError,
    lock_and_ensure_order_allocations,
    release_order_reservations,
)
from app.services.audit import log_manager_activity
from app.services.billing import incidents
from app.services.runtime import (
    RuntimeError as RuntimeAdapterError,
    wings_runtime_adapter,
)
from app.services.server_engine import (
    CreatedServer,
    ServerBuildPatch,
    ServerEngineError,
    ServerNotFoundError,
    ServerRuntimeSyncError,
    server_engine,
)
from app.services.user_service import mark_user_owned_server

logger = logging.getLogger(__name__)

# Alias kept so tests monkeypatching ``apply_engine.wings_service`` patch the
# exact ``wings_runtime_adapter`` singleton used by both this module and ``server_engine``.
wings_service = wings_runtime_adapter


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

    from app.services.billing.payments import locked_order
    order = await locked_order(db, order_id)
    if order.status != "processing":
        await db.commit()
        return ApplyResult.NOT_OUR_BUSINESS
    if (order.lock_token and cast(datetime, order.locked_until) > now) or (order.next_apply_at and order.next_apply_at > now):
        await db.commit()
        return ApplyResult.LOCK_NOT_ACQUIRED
    my_token = uuid.uuid4().hex
    order.lock_token = my_token
    order.locked_until = now + timedelta(seconds=APPLY_LEASE_SECONDS)
    await db.commit()

    # ── Stage 3: business effect + post actions
    try:
        effect = await db.get(BillingOrderEffect, order_id)
        if effect is None:
            # Path A
            server_id = await _commit_business_effect(db, order)
            await _run_post_actions(db, order, server_id)
            await _mark_post_actions_done(db, order_id)
        elif effect.post_actions_done_at is None:
            # Path B
            await _run_post_actions(db, order, effect.server_id)
            await _mark_post_actions_done(db, order_id)
    except ApplyOrphanError as exc:
        return await _terminate_apply(
            db, order_id, exc, my_token, reason="orphan_resource"
        )
    except Exception as exc:  # noqa: BLE001
        return await _record_failure_and_release(db, order_id, exc, my_token)

    order = await locked_order(db, order_id)
    if order.lock_token != my_token:
        await db.commit()
        return ApplyResult.LOCK_LOST
    apply_retry_count = order.apply_retry_count
    coupon_id = order.coupon_id
    coupon_discount_fen = order.coupon_discount_fen or 0
    order.applied_at = utc_naive_now()
    order.lock_token = None
    order.locked_until = None
    order.next_apply_at = None
    order.last_apply_error = None
    from app.services.billing.payments import update_order_state
    await update_order_state(db, order)
    await db.commit()

    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        operation=OperationResult(action="billing.order.apply", phase="execution", outcome="success", target={"order_id": order_id}),
        detail_key="billing.order.applied",
        detail_params={
            "order_id": order_id,
            "source": source,
            "retries": apply_retry_count,
        },
    )
    # NOTE: 'orderPaid' email template lives in Phase B (post-MVP).
    try:
        from app.services.billing import notify

        await notify.notify_order_paid(order_id)
    except Exception:  # noqa: BLE001 - email is best-effort
        logger.exception("notify_order_paid failed for order %s", order_id)

    # ── Stage 4b: coupon consumption + referral reward (best-effort) ──────
    # Both are downstream of a successful apply and must NEVER reverse
    # the order state. Failures are logged but swallowed.
    if coupon_id is not None:
        try:
            from app.services.billing import coupons as coupon_svc

            await coupon_svc.mark_used_for_order(
                db,
                order_id=order_id,
                actual_discount_fen=coupon_discount_fen,
            )
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.exception(
                "apply_engine: coupon mark_used failed for order %s", order_id
            )
            await log_manager_activity(
                db,
                actor="system",
                category="billing",
                operation=OperationResult(action="billing.coupon.mark_used", phase="execution", outcome="failed", target={"order_id": order_id, "coupon_id": coupon_id}, error=ErrorInfo(code="system.internal_error", detail=str(exc)[:200])),
                detail_key="billing.coupon.mark_used_failed",
                detail_params={
                    "order_id": order_id,
                    "coupon_id": coupon_id,
                    "error": str(exc)[:200],
                },
            )
    try:
        from app.services.billing import referral_rewards

        await db.refresh(order)
        await referral_rewards.try_grant_for_order(db, order)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception(
            "apply_engine: referral grant failed for order %s", order_id
        )
        await log_manager_activity(
            db,
            actor="system",
            category="billing",
            operation=OperationResult(action="billing.referral.grant", phase="execution", outcome="failed", target={"order_id": order_id}, error=ErrorInfo(code="system.internal_error", detail=str(exc)[:200])),
            detail_key="billing.referral.grant_failed",
            detail_params={
                "order_id": order_id,
                "error": str(exc)[:200],
            },
        )
    return ApplyResult.APPLIED


# --------------------------------------------------------------------------- #
# Stage helpers
# --------------------------------------------------------------------------- #


async def has_usable_payment(db: AsyncSession, order_id: int) -> bool:
    """交付重试与正常退款通知可能重叠；已退或退款中的付款不再启动交付。"""
    found = await db.scalar(
        select(
            exists().where(
                BillingInvoiceTransaction.invoice_id.in_(
                    select(BillingInvoice.id).where(
                        BillingInvoice.order_id == order_id
                    )
                ),
                BillingInvoiceTransaction.status == "succeeded",
                ~exists().where(
                    BillingPayment.id == BillingInvoiceTransaction.payment_id,
                    or_(BillingPayment.status != "paid", BillingPayment.channel_refunding.is_(True)),
                ),
                ~exists().where(
                    BillingRefund.transaction_id == BillingInvoiceTransaction.id,
                    BillingRefund.status.in_(("pending", "unknown", "processing", "action_required", "succeeded")),
                ),
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
    elif order.kind == "convert":
        return await _effect_convert(db, order)
    else:  # new_purchase
        return await _effect_new_purchase(db, order)


async def _local_today(db: AsyncSession) -> date:
    """Local-day 'today' — billing periods are day-granular and the
    business definition lives in local time, not UTC.

    Reads the ``TIMEZONE`` runtime setting so the result is correct
    regardless of the host's system timezone (the dev machine runs UTC
    while production runs Asia/Shanghai). Mirrors the ``get_job_today``
    helper used by the automation tasks so apply-time and task-time
    agree on what "today" means.
    """
    from app.core.runtime_settings import AUTOMATION_SPECS
    from app.core.settings_store import get_settings_store
    from app.core.time import local_today

    tz_name = await get_settings_store().get(
        db, "TIMEZONE", AUTOMATION_SPECS["TIMEZONE"].default_value()
    )
    return local_today(str(tz_name))


def _build_patch_from_snapshot(snap: Mapping[str, Any]) -> ServerBuildPatch | None:
    patch = ServerBuildPatch.from_snapshot(snap)
    if all(
        getattr(patch, field) is None
        for field in (
            "memory",
            "swap",
            "disk",
            "io",
            "cpu",
            "allocation_limit",
            "database_limit",
            "backup_limit",
            "oom_disabled",
        )
    ):
        return None
    return patch


async def _effect_upgrade(db: AsyncSession, order: BillingOrder) -> int:
    """Upgrade = prorated plan switch with resource/build updates only.

    No expiration_date change, no Wings container removal, no startup/image
    change (upgrade keeps the server's existing image and startup command).
    """
    if order.target_server_id is None:
        raise ApplyOrphanError(f"upgrade order {order.id} 缺少 target_server_id")

    server_id = int(order.target_server_id)
    snap = order.plan_snapshot or {}
    target_plan_id = snap.get("plan_id") or order.plan_id

    try:
        await server_engine.apply_plan_transition(
            db,
            server_id,
            new_plan_id=int(target_plan_id) if target_plan_id is not None else None,
            build_patch=_build_patch_from_snapshot(snap),
            sync_llm=False,
            auto_unsuspend=False,
        )
    except ServerNotFoundError as exc:
        raise ApplyOrphanError(f"server {server_id} 已删除") from exc
    except ServerEngineError as exc:
        raise ApplyError(str(exc)) from exc

    srv = await db.get(PteroServer, server_id, populate_existing=True)
    if srv is None:
        raise ApplyOrphanError(f"server {server_id} 已删除")

    now = utc_naive_now()
    db.add(
        BillingOrderEffect(
            order_id=order.id,
            server_id=srv.id,
            effect_type="upgrade",
            days=0,
            prev_expiration_date=srv.expiration_date,
            new_expiration_date=srv.expiration_date,
            effect_committed_at=now,
            post_actions_done_at=None,
        )
    )
    await db.commit()
    return int(srv.id)


async def _effect_renew(db: AsyncSession, order: BillingOrder) -> int:
    """Renew = bought time only. Touches no Wings, no resources, no plan_id."""
    if order.target_server_id is None:
        raise ApplyOrphanError(f"renew order {order.id} 缺少 target_server_id")

    server_id = int(order.target_server_id)
    server = await db.scalar(
        select(PteroServer)
        .where(PteroServer.id == server_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if server is None:
        raise ApplyOrphanError(f"server {server_id} 已删除")

    today = await _local_today(db)
    prev = server.expiration_date
    base = prev if prev and prev > today else today
    new_date = base + timedelta(days=order.total_days)
    now = utc_naive_now()

    db.add(
        BillingOrderEffect(
            order_id=order.id,
            server_id=server_id,
            effect_type="renew",
            days=order.total_days,
            prev_expiration_date=prev,
            new_expiration_date=new_date,
            effect_committed_at=now,
            post_actions_done_at=None,
        )
    )
    try:
        # renew_server locks the same server row, updates expiration_date, and
        # commits the pending BillingOrderEffect atomically in one transaction.
        await server_engine.renew_server(
            db,
            server_id,
            new_expiration_date=new_date,
            auto_unsuspend=False,
        )
    except ServerNotFoundError as exc:
        await db.rollback()
        raise ApplyOrphanError(f"server {server_id} 已删除") from exc
    except ServerEngineError as exc:
        await db.rollback()
        raise ApplyError(str(exc)) from exc
    return server_id


async def _effect_convert(db: AsyncSession, order: BillingOrder) -> int:
    """Convert = trial → linked standard plan renewal.

    Syncs Wings build limits first (idempotent with rollback on Wings failure),
    then atomically commits ``plan_id``, ``is_trial=False``, ``expiration_date``,
    and ``BillingOrderEffect`` under a ``FOR UPDATE`` lock in one transaction.
    """
    if order.target_server_id is None:
        raise ApplyOrphanError(f"convert order {order.id} 缺少 target_server_id")

    server_id = int(order.target_server_id)
    snap = order.plan_snapshot or {}
    snap_plan_id = snap.get("plan_id") or order.plan_id
    build_patch = _build_patch_from_snapshot(snap)

    if build_patch is not None:
        try:
            await server_engine.update_build(db, server_id, build_patch)
        except ServerNotFoundError as exc:
            raise ApplyOrphanError(f"server {server_id} 已删除") from exc
        except ServerEngineError as exc:
            raise ApplyError(str(exc)) from exc

    server = await db.scalar(
        select(PteroServer)
        .where(PteroServer.id == server_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if server is None:
        await db.rollback()
        raise ApplyOrphanError(f"server {server_id} 已删除")

    today = await _local_today(db)
    prev = server.expiration_date
    base = prev if prev and prev > today else today
    new_date = base + timedelta(days=order.total_days)
    now = utc_naive_now()

    db.add(
        BillingOrderEffect(
            order_id=order.id,
            server_id=server_id,
            effect_type="convert",
            days=order.total_days,
            prev_expiration_date=prev,
            new_expiration_date=new_date,
            effect_committed_at=now,
            post_actions_done_at=None,
        )
    )
    try:
        # apply_plan_transition(build_patch=None) locks the same row, applies
        # plan_id/is_trial/expiration_date, and commits BillingOrderEffect in one tx.
        await server_engine.apply_plan_transition(
            db,
            server_id,
            new_plan_id=int(snap_plan_id) if snap_plan_id is not None else None,
            build_patch=None,
            new_expiration_date=new_date,
            update_expiration=True,
            clear_trial=True,
            sync_llm=False,
            auto_unsuspend=False,
        )
    except ServerNotFoundError as exc:
        await db.rollback()
        raise ApplyOrphanError(f"server {server_id} 已删除") from exc
    except ServerEngineError as exc:
        await db.rollback()
        raise ApplyError(str(exc)) from exc
    return server_id


async def _effect_new_purchase(db: AsyncSession, order: BillingOrder) -> int:
    """Consume reserved allocations to provision a live server + Wings push."""
    order_id = int(order.id)
    order_user_id = int(order.user_id)
    order_no = str(order.order_no)
    order_total_days = int(order.total_days)
    order_reserved_node_id = order.reserved_node_id
    order_reserved_alloc_id = order.reserved_allocation_id
    snap = order.plan_snapshot or {}
    snap_plan_id = snap.get("plan_id") or order.plan_id
    if snap_plan_id is None:
        raise ApplyError(f"order {order_id} has no plan_id in snapshot or FK")
    is_trial = snap.get("plan_type", "standard") == "trial"

    today = await _local_today(db)
    new_date = today + timedelta(days=order_total_days)
    target_external = f"order:{order_id}"

    # Branch A: idempotent resume when a previous attempt already inserted the
    # server row (e.g. Wings timed out without confirming cleanup, or process
    # crashed between Wings create and writing BillingOrderEffect).
    if order.target_server_id is not None:
        server = await db.get(PteroServer, order.target_server_id)
        if server is None:
            raise ApplyOrphanError(f"server {order.target_server_id} 不存在")
        try:
            await wings_service.create_server(db, server.node_id, server.uuid)
        except RuntimeAdapterError as exc:
            raise ApplyError(f"wings.create_server 失败: {exc}") from exc

        now = utc_naive_now()
        await db.execute(
            update(PteroServer)
            .where(PteroServer.id == server.id)
            .values(
                external_id=target_external,
                expiration_date=new_date,
                plan_id=int(snap_plan_id),
                is_trial=is_trial,
                updated_at=now,
            )
        )
        db.add(
            BillingOrderEffect(
                order_id=order_id,
                server_id=server.id,
                effect_type="new_purchase",
                days=order_total_days,
                prev_expiration_date=None,
                new_expiration_date=new_date,
                effect_committed_at=now,
                post_actions_done_at=None,
            )
        )
        await mark_user_owned_server(db, server.owner_id)
        await db.commit()
        return int(server.id)

    # Branch B: first delivery — consume reserved allocations and create live server.
    user = await db.get(PteroUser, order_user_id)
    if user is None:
        raise ApplyOrphanError(f"user {order_user_id} 不存在")
    node_id = order_reserved_node_id or snap.get("node_id")
    if node_id is None:
        raise ApplyOrphanError(f"order {order_id} 缺少目标节点信息")
    alloc_count = max(1, int(snap.get("allocation_limit") or 1))
    username = str(user.username)

    try:
        primary_id, extra_ids = await lock_and_ensure_order_allocations(
            db,
            node_id=int(node_id),
            order_id=order_id,
            count=alloc_count,
            preferred_primary_id=order_reserved_alloc_id,
        )
    except InsufficientAllocationsError as exc:
        await db.rollback()
        raise ApplyError(f"节点可用端口不足: {exc}") from exc

    async def _bind_order_on_db_created(
        session: AsyncSession, created_row: CreatedServer
    ) -> None:
        order_row = await session.get(BillingOrder, order_id)
        if order_row is None:
            raise ApplyOrphanError(f"order {order_id} 不存在")
        order_row.reserved_node_id = int(node_id)
        order_row.reserved_allocation_id = primary_id
        order_row.reserved_additional_allocations = extra_ids or None
        order_row.target_server_id = created_row.id

    async def _clear_order_on_db_compensated(
        session: AsyncSession, _created_row: CreatedServer
    ) -> None:
        await session.execute(
            update(BillingOrder)
            .where(BillingOrder.id == order_id)
            .values(target_server_id=None, updated_at=utc_naive_now())
        )

    try:
        # confirm_clean_on_runtime_failure=True preserves 5A anti-duplicate-container
        # semantics: only delete the DB row, restore strong reservations, and clear
        # target_server_id (in one atomic tx via on_db_compensated) when Wings confirms
        # no container remains; otherwise keep the row for same-UUID retry.
        # plan_snapshot=None defers LLM provisioning to _run_post_actions (Path A/B).
        created = await server_engine.create_server(
            db,
            owner_id=order_user_id,
            node_id=int(node_id),
            allocation_id=primary_id,
            egg_id=int(snap["egg_id"]),
            name=f"{username}-{order_no[-6:]}",
            memory=snap["memory_mb"],
            swap=snap["swap_mb"],
            disk=snap["disk_mb"],
            io=snap["io"],
            cpu=snap["cpu"],
            image=snap["docker_image"],
            startup=snap["startup_command"],
            environment={
                key: str(value)
                for key, value in (snap.get("env_snapshot") or {}).items()
            },
            database_limit=snap["database_limit"],
            backup_limit=snap["backup_limit"],
            allocation_limit=snap["allocation_limit"],
            oom_disabled=snap["oom_disabled"],
            description="",
            external_id=target_external,
            allocation_additional=extra_ids or None,
            consuming_order_id=order_id,
            expiration_date=new_date,
            plan_id=int(snap_plan_id),
            is_trial=is_trial,
            plan_snapshot=None,
            confirm_clean_on_runtime_failure=True,
            restore_order_reservations_on_failure=True,
            on_db_created=_bind_order_on_db_created,
            on_db_compensated=_clear_order_on_db_compensated,
        )
    except ApplyOrphanError:
        await db.rollback()
        raise
    except ServerRuntimeSyncError as create_exc:
        params = create_exc.params or {}
        created_id = params.get("server_id")
        node_confirmed_clean = bool(params.get("node_confirmed_clean"))
        if node_confirmed_clean:
            if created_id is None or (
                await db.get(PteroServer, int(created_id), populate_existing=True)
            ) is None:
                order.target_server_id = None
            else:
                order.target_server_id = int(created_id)
        elif created_id is not None:
            order.target_server_id = int(created_id)
        raise ApplyError(f"wings.create_server 失败: {create_exc}") from create_exc
    except ServerEngineError as exc:
        await db.rollback()
        raise ApplyError(f"创建服务器记录失败: {exc}") from exc

    # Wings succeeded — commit effect row (has_owned_server already marked by server_engine).
    order.target_server_id = created.id
    now = utc_naive_now()
    db.add(
        BillingOrderEffect(
            order_id=order_id,
            server_id=created.id,
            effect_type="new_purchase",
            days=order_total_days,
            prev_expiration_date=None,
            new_expiration_date=new_date,
            effect_committed_at=now,
            post_actions_done_at=None,
        )
    )
    await mark_user_owned_server(db, order_user_id)
    await db.commit()
    return created.id


# --------------------------------------------------------------------------- #
# Post-actions
# --------------------------------------------------------------------------- #


async def _run_post_actions(
    db: AsyncSession, order: BillingOrder, server_id: int
) -> None:
    order_id = order.id

    # 1) Unsuspend if needed (idempotent; also re-enables LLM token in real time).
    server = await db.get(PteroServer, server_id)
    if server is not None and server.is_suspended:
        await server_engine.unsuspend_server(db, server_id)

    # 2) LLM free quota provision (best-effort — must never block the order).
    # Renew does NOT trigger provision — it doesn't change the plan's LLM
    # config, and the key follows server status (sync job handles
    # suspend/unsuspend).
    #
    #   * upgrade / convert -> always call update_for_upgrade. It reconciles
    #     the key to the NEW snapshot, INCLUDING revoking it when the new plan
    #     has no LLM quota (otherwise converting away from an LLM plan would
    #     leak the NewAPI token + key row).
    #   * new_purchase (and other kinds) -> provision only if the new plan
    #     actually grants LLM quota.
    if server is not None and order.kind != "renew":
        snapshot = order.plan_snapshot or {}
        try:
            from app.services.llm_provision import provision as llm_provision
            if order.kind in ("upgrade", "convert"):
                await llm_provision.update_for_upgrade(db, server_id, snapshot)
            else:
                llm_enabled = bool(snapshot.get("llm_enabled")) and int(
                    snapshot.get("llm_quota_grant", 0)
                ) > 0
                if llm_enabled:
                    await llm_provision.provision_for_server(
                        db, server_id, server.owner_id, snapshot
                    )
            await db.commit()
        except Exception:
            logger.warning(
                "LLM provision failed for order %s server %s (non-blocking)",
                order_id, server_id, exc_info=True,
            )
            await db.rollback()


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
    order_id: int,
    exc: Exception,
    my_token: str,
) -> ApplyResult:
    logger.exception("apply failed for order %s", order_id)
    await db.rollback()
    terminal = False
    last_error = str(exc)[:500]

    row = await db.scalar(
        select(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.lock_token == my_token,
        )
        .with_for_update()
    )
    if row is None:
        await db.rollback()
        return ApplyResult.LOCK_LOST

    row.last_apply_error = last_error
    row.lock_token = None
    row.locked_until = None
    # Wings 请求期间可能完成退款；失败收尾不能把退款状态改回交付重试。
    if row.status != "processing":
        from app.services.billing.payments import update_order_state
        await update_order_state(db, row)
        need_cleanup = False
        if row.status == "refunded" and row.applied_at is None:
            await release_order_reservations(db, row.id)
            need_cleanup = row.kind == "new_purchase" and row.target_server_id is not None
        await db.commit()
        if need_cleanup:
            from app.services.billing.orders import cleanup_unapplied_order
            await cleanup_unapplied_order(order_id)
        return ApplyResult.NOT_OUR_BUSINESS
    row.apply_retry_count += 1
    if row.apply_retry_count > len(RETRY_DELAYS):
        row.status = "apply_failed"
        row.next_apply_at = None
        terminal = True
    else:
        delay = RETRY_DELAYS[row.apply_retry_count - 1]
        row.next_apply_at = utc_naive_now() + timedelta(seconds=delay)
    apply_retry_count = row.apply_retry_count
    coupon_id = row.coupon_id
    await db.commit()

    if terminal:
        await incidents.log_incident(
            "apply_retries_exhausted",
            order_id=order_id,
            payload={"last_error": last_error},
        )
        await log_manager_activity(
            db,
            actor="system",
            category="billing",
            operation=OperationResult(action="billing.order.apply", phase="execution", outcome="failed", target={"order_id": order_id}, error=ErrorInfo(code="billing.order.apply_failed", detail=last_error)),
            detail_key="billing.order.apply_failed",
            detail_params={"order_id": order_id, "error": last_error},
        )
        try:
            from app.services.billing import notify

            await notify.notify_order_apply_failed(order_id)
            await notify.notify_order_apply_alert(order_id)
        except Exception:  # noqa: BLE001 - email is best-effort
            logger.exception(
                "notify apply_failed/alert failed for order %s", order_id
            )
        # Release reserved coupon — the order is dead, the user keeps the
        # coupon. Best-effort, swallow errors so we don't mask the
        # underlying apply failure.
        if coupon_id is not None:
            try:
                from app.services.billing import coupons as coupon_svc

                await coupon_svc.release_for_order(db, order_id=order_id)
            except Exception:
                await db.rollback()
                logger.exception(
                    "apply_engine: coupon release on permanent failure "
                    "failed for order %s", order_id,
                )
        return ApplyResult.PERMANENT_FAILURE
    # First retry failure (apply_retry_count == 1) → admin alert per §14.
    if apply_retry_count == 1:
        try:
            from app.services.billing import notify

            await notify.notify_order_apply_alert(order_id)
        except Exception:  # noqa: BLE001 - email is best-effort
            logger.exception(
                "notify apply_alert (first failure) failed for order %s",
                order_id,
            )
    return ApplyResult.RETRY_SCHEDULED


async def _terminate_apply(
    db: AsyncSession,
    order_id: int,
    exc: Exception,
    my_token: str,
    *,
    reason: str,
) -> ApplyResult:
    """Unrecoverable orphan — straight to apply_failed, no retry."""
    logger.error("apply terminated for order %s: %s", order_id, exc)
    await db.rollback()
    last_error = f"{reason}: {exc}"[:500]

    row = await db.scalar(
        select(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.lock_token == my_token,
        )
        .with_for_update()
    )
    if row is None:
        await db.rollback()
        return ApplyResult.LOCK_LOST

    if row.status == "processing":
        row.status = "apply_failed"
    row.last_apply_error = last_error
    row.next_apply_at = None
    row.lock_token = None
    row.locked_until = None
    need_cleanup = False
    if row.status == "refunded" and row.applied_at is None:
        await release_order_reservations(db, row.id)
        need_cleanup = row.kind == "new_purchase" and row.target_server_id is not None
    coupon_id = row.coupon_id
    await db.commit()
    if need_cleanup:
        from app.services.billing.orders import cleanup_unapplied_order
        await cleanup_unapplied_order(order_id)

    await incidents.log_incident(
        "apply_retries_exhausted",
        order_id=order_id,
        payload={"reason": reason, "error": last_error},
    )
    await log_manager_activity(
        db,
        actor="system",
        category="billing",
        operation=OperationResult(action="billing.order.apply", phase="execution", outcome="failed", target={"order_id": order_id}, error=ErrorInfo(code="billing.order.apply_failed", detail=reason)),
        detail_key="billing.order.apply_terminated",
        detail_params={"order_id": order_id, "reason": reason},
    )
    # Release coupon on terminate too — same rationale as the retry-
    # exhausted path above.
    if coupon_id is not None:
        try:
            from app.services.billing import coupons as coupon_svc

            await coupon_svc.release_for_order(db, order_id=order_id)
        except Exception:
            await db.rollback()
            logger.exception(
                "apply_engine: coupon release on terminate failed for order %s",
                order_id,
            )
    return ApplyResult.PERMANENT_FAILURE
