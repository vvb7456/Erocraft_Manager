"""Order lifecycle service — see ``docs/BILLING_DESIGN.md`` §6 / §8.

Public surface (Module 1 scope):

* :func:`create_order` — quota-checked + plan-snapshotted order placement
  with inline placeholder server creation for ``new_purchase`` (§6).
* :func:`list_orders` / :func:`get_order` — owner-scoped read helpers.
* :func:`cancel_order` — user-initiated cancel with the same lock+lease+
  gateway-query 二次确认 sequence as the close job (§8.2).

Modules 2+ will extend this file with ``add_payment`` plumbing wired
through ``orders``; this module deliberately only does what the user can
trigger pre-payment.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any, NoReturn

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import BILLING_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.billing import (
    BillingInvoice,
    BillingInvoiceItem,
    BillingInvoiceTransaction,
    BillingOrder,
    BillingPlan,
)
from app.db.models.manager import ServerMeta
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.schemas.billing_orders import CreateOrderRequest
from app.services import panel_db, server_lifecycle
from app.services.audit import log_manager_activity
from app.services.billing import incidents
from app.services.billing._ids import gen_invoice_no, gen_order_no
from app.services.billing.gateway import registry as gateway_registry
from app.services.billing.gateway.base import (
    CreateInvoiceRequest,
    GatewayBusinessError,
    GatewayError,
    GatewayTransientError,
    QueryResult,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Exceptions (mapped to HTTP responses by the router)
# --------------------------------------------------------------------------- #


class OrderError(Exception):
    """Base class for order-flow errors translated to user-facing HTTP."""


class PlanNotPurchasable(OrderError):
    """Plan does not exist, is inactive, or is not bound to the server."""


class InvalidOrderRequest(OrderError):
    """Request payload contradicts server-side state."""


class GatewayUnavailable(OrderError):
    """Gateway create-invoice / query failed; user should retry later."""


class CannotCancel(OrderError):
    """Order is not in a cancellable state (or owned by another user)."""


class OrderAlreadyPaid(OrderError):
    """Cancel attempt raced a successful payment — order moved on."""


class OrderNotFound(OrderError):
    pass


class PendingOrderExists(OrderError):
    """User has an unpaid order (any kind) already outstanding."""
    pass


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _runtime_int(db: AsyncSession, key: str) -> int:
    spec = BILLING_SPECS[key]
    value = await get_settings_store().get(db, key, spec.default_value())
    return int(value)


def _select_period(
    plan: BillingPlan, period_count: int
) -> dict[str, Any]:
    for opt in plan.period_options or []:
        if int(opt["count"]) == period_count:
            return {
                "count": int(opt["count"]),
                "discount_pct": float(opt["discount_pct"]),
            }
    raise InvalidOrderRequest(
        f"period_count={period_count} 不在套餐 {plan.code} 的可选周期内"
    )


def _calc_total(plan: BillingPlan, period: dict[str, Any]) -> tuple[int, int]:
    """Returns (total_fen, total_days). round() banker's rounding is
    acceptable since prices are already integer fen — fractional results
    only occur for ``discount_pct`` not divisible into the price.
    """
    raw = plan.price_fen * period["count"] * (100 - period["discount_pct"])
    # Use Decimal half-up to avoid Python's banker's rounding surprising users.
    total_fen = int((Decimal(str(raw)) / Decimal("100")).quantize(Decimal("1")))
    total_days = plan.days * period["count"]
    if total_fen <= 0 or total_days <= 0:
        raise InvalidOrderRequest("套餐价格/天数计算异常")
    return total_fen, total_days


def _build_snapshot(
    plan: BillingPlan,
    period: dict[str, Any],
    total_fen: int,
    total_days: int,
) -> dict[str, Any]:
    """Materialize §3.3.1 plan_snapshot. apply_engine MUST read from this
    blob exclusively — it is the price/config lock for the order."""
    return {
        "schema_version": 2,
        "plan_id": plan.id,
        "plan_name": plan.display_name,
        "plan_code": plan.code,
        "price_fen": plan.price_fen,
        "days": plan.days,
        "currency_code": plan.currency_code,
        "selected_period": {
            "count": period["count"],
            "discount_pct": period["discount_pct"],
            "total_fen": total_fen,
            "total_days": total_days,
        },
        "egg_id": plan.egg_id,
        "nest_id": plan.nest_id,
        "node_id": plan.node_id,
        "docker_image": plan.docker_image,
        "startup_command": plan.startup_command,
        "env_snapshot": dict(plan.env_defaults or {}),
        "cpu": plan.cpu,
        "memory_mb": plan.memory_mb,
        "disk_mb": plan.disk_mb,
        "swap_mb": plan.swap_mb,
        "io": plan.io,
        "database_limit": plan.database_limit,
        "backup_limit": plan.backup_limit,
        "allocation_limit": plan.allocation_limit,
        "oom_disabled": plan.oom_disabled,
        "plan_type": plan.plan_type,
        "linked_plan_id": plan.linked_plan_id,
        "llm_enabled": plan.llm_enabled,
        "llm_quota_grant": plan.llm_quota_grant,
        "newapi_plan_id": plan.newapi_plan_id,
        "llm_group": plan.llm_group,
    }


# --------------------------------------------------------------------------- #
# One-active-order-per-user invariant
# --------------------------------------------------------------------------- #
#
# Database-side guarantee: a VIRTUAL generated column ``active_user_lock``
# on ``manager_billing_orders`` equals ``user_id`` while status is one of
# ``pending / processing / manual_review`` and NULL otherwise, with a
# UNIQUE index on top. Two concurrent INSERTs cannot both win.
#
# The Python helper below is just a friendly fast-path: it skips the
# expensive plan/gateway/snapshot work when we can already see the
# conflict, and surfaces the existing order_no in the error message.
# The IntegrityError handling around the actual INSERT is what makes
# the invariant correct under concurrency.

_ACTIVE_ORDER_STATUSES = ("pending", "processing", "manual_review")


async def _check_no_pending_order(db: AsyncSession, user: PteroUser) -> None:
    existing = (
        await db.execute(
            select(BillingOrder)
            .where(
                BillingOrder.user_id == user.id,
                BillingOrder.status.in_(_ACTIVE_ORDER_STATUSES),
            )
            .order_by(BillingOrder.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise PendingOrderExists(
            f"您有未完成的订单，请先支付或取消 (订单号：{existing.order_no})"
        )


# --------------------------------------------------------------------------- #
# Public: create_order
# --------------------------------------------------------------------------- #


async def create_order(
    db: AsyncSession,
    user: PteroUser,
    payload: CreateOrderRequest,
) -> BillingOrder:
    """Place an order. See §6 for the canonical sequence.

    Returns the persisted ``BillingOrder`` (refreshed; ``invoice`` accessible
    via a follow-up query). Raises subclasses of :class:`OrderError` for
    user-fixable errors; truly unexpected exceptions propagate.
    """
    # ── 0) No-pending-orders check (applies to all kinds)
    await _check_no_pending_order(db, user)

    # ── 1) Resolve plan + validate kind-specific args ──────────────────────
    plan: BillingPlan | None = None
    if payload.kind == "upgrade":
        server = await db.get(PteroServer, payload.target_server_id)
        if server is None or server.owner_id != user.id:
            raise InvalidOrderRequest("服务器不存在或无权升级")
        if server.is_suspended:
            raise InvalidOrderRequest("服务器不可用，无法升级")
        from app.core.time import local_today  # local import to avoid cycle
        from app.core.runtime_settings import AUTOMATION_SPECS
        from app.core.config import get_settings as _get_app_settings
        _tz_name = await get_settings_store().get(
            db, "TIMEZONE", AUTOMATION_SPECS["TIMEZONE"].default_value()
        )
        today = local_today(str(_tz_name))
        if server.expiration_date is not None and server.expiration_date < today:
            raise InvalidOrderRequest("服务器不可用，无法升级")
        meta = await db.get(ServerMeta, server.id)
        if meta is None or meta.plan_id is None:
            raise InvalidOrderRequest("无套餐服务器无法升级")
        # Trial servers cannot be upgraded until converted to a standard
        # plan. Backend backstop; the frontend disables the upgrade button.
        if meta.is_trial:
            raise InvalidOrderRequest("试用套餐需先转换为标准套餐才能升级")
        old_plan = await db.get(BillingPlan, meta.plan_id)
        if old_plan is None:
            raise PlanNotPurchasable("此服务器关联的套餐已被删除，请联系管理员")
        new_plan = (
            await db.execute(
                select(BillingPlan).where(
                    BillingPlan.code == payload.plan_code,
                    BillingPlan.is_active.is_(True),
                    BillingPlan.egg_id == server.egg_id,
                )
            )
        ).scalar_one_or_none()
        if new_plan is None:
            raise PlanNotPurchasable(f"套餐 {payload.plan_code!r} 不存在或不兼容")
        if new_plan.id == old_plan.id:
            raise InvalidOrderRequest("不能升级为相同的套餐")
        if new_plan.price_fen <= old_plan.price_fen:
            raise InvalidOrderRequest("目标套餐价格不足以升级")
        # period_count forced to 1; build custom snapshot with previous_plan
        period_count = 1
        from app.services.billing._pricing import (
            remaining_billable_days,
            upgrade_diff_fen,
        )
        remaining = remaining_billable_days(server.expiration_date, today)
        diff_fen = upgrade_diff_fen(old_plan, new_plan, remaining)
        if diff_fen <= 0:
            raise InvalidOrderRequest("无效的升级目标")
        plan = new_plan
        total_fen = diff_fen
        total_days = 0
        period = {"count": 1, "discount_pct": 0}
    elif payload.kind == "renew":
        server = await db.get(PteroServer, payload.target_server_id)
        if server is None or server.owner_id != user.id:
            raise InvalidOrderRequest("服务器不存在或无权续费")
        meta = await db.get(ServerMeta, server.id)
        if meta is None or meta.plan_id is None:
            raise PlanNotPurchasable("此服务器未绑定套餐，无法续费")
        # Trial servers cannot be renewed in-place — only converted to
        # their linked standard plan (kind=convert). Backend backstop;
        # the frontend hides the renew button for trial servers.
        if meta.is_trial:
            raise InvalidOrderRequest("试用套餐无法续费，请转换为标准套餐")
        plan = (
            await db.execute(select(BillingPlan).where(BillingPlan.id == meta.plan_id))
        ).scalar_one_or_none()
        if plan is None:
            raise PlanNotPurchasable("此服务器关联的套餐已被删除，请联系管理员")
        # Note: NOT checking is_active — bound servers can always renew (§6).
        period = _select_period(plan, payload.period_count)
        total_fen, total_days = _calc_total(plan, period)
    elif payload.kind == "convert":
        # Trial → its linked standard plan. Only valid for trial servers.
        # The target plan is resolved from the trial plan's linked_plan_id,
        # not from the payload, so the user can't convert to an arbitrary plan.
        server = await db.get(PteroServer, payload.target_server_id)
        if server is None or server.owner_id != user.id:
            raise InvalidOrderRequest("服务器不存在或无权操作")
        meta = await db.get(ServerMeta, server.id)
        if meta is None or meta.plan_id is None:
            raise PlanNotPurchasable("此服务器未绑定套餐，无法转换")
        if not meta.is_trial:
            raise InvalidOrderRequest("仅试用套餐可转换为标准套餐")
        trial_plan = await db.get(BillingPlan, meta.plan_id)
        if trial_plan is None or trial_plan.linked_plan_id is None:
            raise PlanNotPurchasable("试用套餐或其关联标准套餐已被删除，请联系管理员")
        plan = (
            await db.execute(
                select(BillingPlan).where(BillingPlan.id == trial_plan.linked_plan_id)
            )
        ).scalar_one_or_none()
        if plan is None:
            raise PlanNotPurchasable("关联的标准套餐已被删除，请联系管理员")
        period = _select_period(plan, payload.period_count)
        total_fen, total_days = _calc_total(plan, period)
    else:  # new_purchase
        plan = (
            await db.execute(
                select(BillingPlan).where(
                    BillingPlan.code == payload.plan_code,
                    BillingPlan.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise PlanNotPurchasable(f"套餐 {payload.plan_code!r} 不存在或已下架")
        # Trial plans: only users who have never owned a server (via any
        # path) may purchase, and only once. ``has_owned_server`` is a
        # permanent flag set on first server ownership and never reset.
        if plan.plan_type == "trial":
            if user.has_owned_server:
                raise InvalidOrderRequest("试用套餐仅限从未拥有过服务器的用户购买")
        period = _select_period(plan, payload.period_count)
        total_fen, total_days = _calc_total(plan, period)

    # ── 2) Gateway must be registered ──────────────────────────────────────
    await gateway_registry.ensure_loaded(db)
    try:
        gateway = gateway_registry.get(payload.gateway_code)
    except KeyError:
        raise GatewayUnavailable(
            f"支付方式 {payload.gateway_code!r} 未启用"
        )

    snapshot = _build_snapshot(plan, period, total_fen, total_days)
    # For upgrade orders, add the old plan snapshot
    if payload.kind == "upgrade":
        assert old_plan is not None
        snapshot["previous_plan"] = {
            "plan_id": old_plan.id,
            "plan_code": old_plan.code,
            "plan_name": old_plan.display_name,
            "price_fen": old_plan.price_fen,
            "days": old_plan.days,
        }

    # ── 2b) Coupon resolution (pre-flight only — actual reserve happens in
    # the order tx below so we share atomicity with the IntegrityError
    # guard). See ``REFERRAL_AND_COUPON_DESIGN.md`` §6.
    from app.services.billing import coupons as coupon_svc
    raw_code = (payload.coupon_code or "").strip()
    coupon_code_norm: str | None = raw_code.upper() if raw_code else None
    coupon_discount_fen = 0
    if coupon_code_norm:
        preview = await coupon_svc.get_by_code_for_user(
            db, user.id, coupon_code_norm
        )
        if preview is None:
            raise InvalidOrderRequest("优惠券不存在或不属于你")
        ok, reason = coupon_svc._is_applicable(
            preview,
            order_kind=payload.kind,
            plan_id=plan.id,
            subtotal_fen=total_fen,
            now=utc_naive_now(),
        )
        if not ok:
            raise InvalidOrderRequest(coupon_svc._reason_to_msg(reason))
        # Invariant C4: discount can never push the total below 0.
        coupon_discount_fen = min(preview.discount_fen, total_fen)
        snapshot["coupon"] = {
            "id": preview.id,
            "code": preview.code,
            "template_id": preview.template_id,
            "discount_fen": preview.discount_fen,
            "applied_fen": coupon_discount_fen,
        }

    payable_total_fen = total_fen - coupon_discount_fen
    # The billing schema intentionally rejects zero/negative invoice totals.
    # Reject a fully-covered order before reserving the coupon or creating a
    # placeholder server, so the caller receives a clean 400 and no state is
    # left behind.
    if payable_total_fen <= 0:
        raise InvalidOrderRequest("优惠券抵扣后订单金额必须大于0")
    timeout_min = await _runtime_int(db, "BILLING_ORDER_PAY_TIMEOUT_MIN")

    # ── 4) Transaction: order + invoice + item (+ placeholder server) ─────
    now = utc_naive_now()
    order_no = gen_order_no()
    invoice_no = gen_invoice_no()

    placeholder_server_id: int | None = None
    try:
        order = BillingOrder(
            order_no=order_no,
            user_id=user.id,
            plan_id=plan.id,
            plan_snapshot=snapshot,
            kind=payload.kind,
            period_count=period["count"],
            discount_pct=Decimal(str(period["discount_pct"])),
            total_fen=payable_total_fen,
            total_days=total_days,
            coupon_discount_fen=coupon_discount_fen,
            target_server_id=(
                payload.target_server_id if payload.kind in ("renew", "upgrade", "convert") else None
            ),
            status="pending",
            received_fen=0,
            refunded_fen=0,
        )
        db.add(order)
        await db.flush()

        # Atomically claim coupon inside the same tx so a concurrent order
        # can't grab the same coupon. The reserve helper raises
        # CouponNotUsable / CouponNotApplicable which we translate.
        if coupon_code_norm:
            try:
                reserved = await coupon_svc.reserve_for_order(
                    db,
                    user_id=user.id,
                    coupon_code=coupon_code_norm,
                    order_id=order.id,
                    order_kind=payload.kind,
                    plan_id=plan.id,
                    subtotal_fen=total_fen,
                )
            except coupon_svc.CouponError as exc:
                await db.rollback()
                raise InvalidOrderRequest(str(exc)) from exc
            order.coupon_id = reserved.id

        if payload.kind == "new_purchase":
            placeholder_server_id = await _create_placeholder_server(
                db, user=user, order=order, plan=plan, snapshot=snapshot,
            )
            order.target_server_id = placeholder_server_id
            order.reserved_node_id = plan.node_id

        invoice = BillingInvoice(
            invoice_no=invoice_no,
            order_id=order.id,
            user_id=user.id,
            status="pending",
            total_fen=payable_total_fen,
            currency_code=plan.currency_code,
            due_at=now + timedelta(minutes=timeout_min),
        )
        db.add(invoice)
        await db.flush()
        invoice_due_at = invoice.due_at

        item_desc = (
            f"{plan.display_name} ({total_days}天 = "
            f"{plan.days}天 × {period['count']})"
        )
        if coupon_code_norm:
            item_desc += f" - 优惠券 {coupon_code_norm} 抵扣 ¥{coupon_discount_fen / 100:.2f}"

        db.add(
            BillingInvoiceItem(
                invoice_id=invoice.id,
                ref_type="order",
                ref_id=order.id,
                description=item_desc,
                price_fen=payable_total_fen,
                quantity=1,
                meta={
                    "plan_code": plan.code,
                    "days_per_period": plan.days,
                    "period_count": period["count"],
                    "discount_pct": period["discount_pct"],
                    **(
                        {
                            "coupon_code": coupon_code_norm,
                            "coupon_discount_fen": coupon_discount_fen,
                            "subtotal_fen_before_coupon": total_fen,
                        } if coupon_code_norm else {}
                    ),
                },
            )
        )

        # Concurrency guard: the unique index ``uk_billing_orders_active_user``
        # (virtual column ``active_user_lock``) raises IntegrityError if this
        # user already has another active order. We translate it into
        # PendingOrderExists below.
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uk_billing_orders_active_user" in str(exc.orig):
            raise PendingOrderExists(
                "您有未完成的订单，请先支付或取消"
            ) from exc
        raise
    except Exception:
        await db.rollback()
        raise

    # ── 5) Outside the transaction (I4): call gateway ──────────────────────
    try:
        site_url = str(await _runtime_site_url(db)).rstrip("/")
        return_url = f"{site_url}/#/pay/{order.id}"
        notify_url = f"{site_url}/api/webhook/{gateway.code}"
        gw_result = await gateway.create_invoice(
            CreateInvoiceRequest(
                invoice_no=invoice_no,
                amount_fen=payable_total_fen,
                title=plan.display_name,
                notify_url=notify_url,
                return_url=return_url,
                due_at=invoice_due_at,
            )
        )
    except GatewayBusinessError as exc:
        # A deterministic gateway rejection means no remote trade was
        # accepted. It is safe to remove the local order, invoice and
        # placeholder (if any), and release the coupon reservation.
        logger.warning(
            "create_invoice failed for order %s: %s — rolling back",
            order_no, exc,
        )
        await _rollback_failed_order(
            db, order_id=order.id, placeholder_server_id=placeholder_server_id,
        )
        raise GatewayUnavailable(str(exc)) from exc
    except (GatewayTransientError, GatewayError) as exc:
        # A timeout/transport/signature/unknown gateway result is ambiguous:
        # the provider may have accepted the trade even though no response
        # reached us. Keep the pending order and make it queryable by its
        # invoice number; deleting it here could leave a customer-paid trade
        # with no local financial record.
        await _mark_gateway_creation_uncertain(
            db,
            invoice_id=invoice.id,
            order_id=order.id,
            gateway_code=payload.gateway_code,
            error=exc,
        )
        raise GatewayUnavailable(
            "支付网关响应超时，订单已保留并将在后台核对，请稍后查看订单状态"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — unknown outcome is ambiguous
        logger.exception(
            "create_invoice raised unknown error for order %s; retaining order",
            order_no,
        )
        await _mark_gateway_creation_uncertain(
            db,
            invoice_id=invoice.id,
            order_id=order.id,
            gateway_code=payload.gateway_code,
            error=exc,
        )
        raise GatewayUnavailable(
            "支付网关响应异常，订单已保留并将在后台核对，请稍后查看订单状态"
        ) from exc

    # ── 6) Persist gateway fields on the invoice ──────────────────────────
    try:
        await db.execute(
            update(BillingInvoice)
            .where(BillingInvoice.id == invoice.id)
            .values(
                gateway_code=payload.gateway_code,
                gateway_prepay_id=gw_result.gateway_order_id,
                gateway_code_url=gw_result.code_url,
                gateway_payload=gw_result.raw,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await log_manager_activity(
        db,
        actor=user.username,
        category="billing",
        status="success",
        detail_key="billing.order.created",
        detail_params={
            "order_id": order.id,
            "order_no": order_no,
            "order_kind": payload.kind,
            "plan_code": plan.code,
            "amount_fen": payable_total_fen,
            "period_count": period["count"],
            "placeholder_server_id": placeholder_server_id,
        },
    )

    await db.refresh(order)
    return order


async def _mark_gateway_creation_uncertain(
    db: AsyncSession,
    *,
    invoice_id: int,
    order_id: int,
    gateway_code: str,
    error: Exception,
) -> None:
    """Retain an order when gateway invoice creation has an unknown outcome.

    The order transaction is committed before the external gateway call. A
    transport timeout (or an adapter exception whose outcome is unknown) may
    therefore mean that the gateway accepted the trade while we did not
    receive its response. Persist the gateway code and an operator-visible
    marker so the query/close jobs can reconcile by ``invoice_no`` instead of
    deleting a potentially payable/paid order.
    """
    error_text = str(error)[:500]
    try:
        await db.execute(
            update(BillingInvoice)
            .where(BillingInvoice.id == invoice_id)
            .values(
                gateway_code=gateway_code,
                gateway_payload={
                    "create_invoice_uncertain": True,
                    "error": error_text,
                },
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        # The order itself is deliberately kept even if this annotation
        # fails; the caller still returns a transient gateway error and the
        # existing pending row remains visible to operators.
        logger.exception(
            "failed to mark uncertain gateway creation for order %s",
            order_id,
        )
    await incidents.log_incident(
        "manual_review_required",
        order_id=order_id,
        invoice_id=invoice_id,
        payload={
            "subkind": "gateway_create_uncertain",
            "gateway_code": gateway_code,
            "error": error_text,
        },
    )


async def _runtime_str(db: AsyncSession, key: str) -> str:
    spec = BILLING_SPECS[key]
    value = await get_settings_store().get(db, key, spec.default_value())
    return str(value)


async def _runtime_site_url(db: AsyncSession) -> str:
    """Read the public site URL from system settings (SITE_URL).

    Used to derive notify_url / return_url for payment gateway requests.
    Raises InvalidOrderRequest when not configured.
    """
    from app.core.runtime_settings import SETTINGS_SPECS  # local import to avoid cycle
    spec = SETTINGS_SPECS["SITE_URL"]
    value = await get_settings_store().get(db, "SITE_URL", spec.default_value())
    url = str(value or "").strip()
    if not url:
        raise InvalidOrderRequest("系统地址 (SITE_URL) 未配置，请管理员在外观设置中填写")
    return url


async def _create_placeholder_server(
    db: AsyncSession,
    *,
    user: PteroUser,
    order: BillingOrder,
    plan: BillingPlan,
    snapshot: dict[str, Any],
) -> int:
    """Insert a panel.servers row that holds the allocation(s) until apply.

    See §5.2. Wings is NOT contacted here — the row sits at
    ``status='installing'`` with ``external_id='pending:order-N'`` until
    payment + apply rebadges it to ``order:N`` and pushes to Wings.
    """
    primary_alloc = await panel_db.find_available_allocation(
        db, plan.node_id, lock=True,
    )
    if primary_alloc is None:
        raise InvalidOrderRequest(
            "节点暂无可用端口，请稍后再试或联系管理员"
        )

    extra_allocs: list[int] = []
    extras_needed = max(0, int(plan.allocation_limit) - 1)
    for _ in range(extras_needed):
        extra = await panel_db.find_available_allocation(
            db, plan.node_id, lock=True,
        )
        if extra is None:
            raise InvalidOrderRequest(
                f"节点可用端口不足，套餐需要 {plan.allocation_limit} 个端口"
            )
        extra_allocs.append(extra)

    name = f"{user.username}-{order.order_no[-6:]}"

    created = await panel_db.create_server(
        db,
        owner_id=user.id,
        node_id=plan.node_id,
        allocation_id=primary_alloc,
        egg_id=plan.egg_id,
        nest_id=plan.nest_id,
        name=name,
        memory=snapshot["memory_mb"],
        swap=snapshot["swap_mb"],
        disk=snapshot["disk_mb"],
        io=snapshot["io"],
        cpu=snapshot["cpu"],
        image=snapshot["docker_image"],
        startup=snapshot["startup_command"],
        environment={k: str(v) for k, v in (snapshot.get("env_snapshot") or {}).items()},
        database_limit=snapshot["database_limit"],
        backup_limit=snapshot["backup_limit"],
        allocation_limit=snapshot["allocation_limit"],
        oom_disabled=snapshot["oom_disabled"],
        # description: 占位阶段保留中文订单号便于 admin 在 panel 一眼识别；
        # apply 成功后由 server_lifecycle.sync_server_expiration_description
        # 改写为“到期时间：YYYY/MM/DD”行（与老服务器对齐）。
        description=f"订单 {order.order_no}",
        external_id=f"pending:order-{order.id}",
        allocation_additional=extra_allocs or None,
    )

    order.reserved_allocation_id = primary_alloc
    order.reserved_additional_allocations = extra_allocs or None
    return created.id


async def _rollback_failed_order(
    db: AsyncSession,
    *,
    order_id: int,
    placeholder_server_id: int | None,
) -> None:
    """Best-effort cleanup after gateway create_invoice failed.

    The order/invoice/items rollback through FK CASCADE when the order row
    is deleted. Placeholder server rows are detached from the billing
    schema and need an explicit ``server_lifecycle.delete_server`` (which
    is Wings-404-idempotent — Wings has never seen this UUID).
    """
    if placeholder_server_id is not None:
        try:
            await server_lifecycle.delete_server(db, placeholder_server_id)
        except Exception:
            logger.exception(
                "rollback: placeholder server cleanup failed (server_id=%s)",
                placeholder_server_id,
            )
            # Carry on — incident below + monitor will catch it.
            await incidents.log_incident(
                "placeholder_cleanup_failed",
                order_id=order_id,
                server_id=placeholder_server_id,
                payload={"phase": "create_order_rollback"},
            )

    # Release any coupon that was reserved before order delete fires the
    # FK cascade — we want the coupon back to ``unused`` not orphaned.
    try:
        from app.services.billing import coupons as coupon_svc
        await coupon_svc.release_for_order(db, order_id=order_id)
    except Exception:
        await db.rollback()
        logger.exception("rollback: coupon release failed for order %s", order_id)

    try:
        await db.execute(delete(BillingOrder).where(BillingOrder.id == order_id))
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("rollback: failed to delete order %s", order_id)


# --------------------------------------------------------------------------- #
# Public: list / get
# --------------------------------------------------------------------------- #


async def list_orders(
    db: AsyncSession, user: PteroUser, *, limit: int = 50, offset: int = 0,
) -> list[BillingOrder]:
    rows = await db.execute(
        select(BillingOrder)
        .where(BillingOrder.user_id == user.id)
        .order_by(BillingOrder.created_at.desc(), BillingOrder.id.desc())
        .limit(min(max(limit, 1), 200))
        .offset(max(offset, 0))
    )
    return list(rows.scalars().all())


async def get_order(
    db: AsyncSession, user: PteroUser, order_id: int,
) -> BillingOrder:
    order = await db.get(BillingOrder, order_id)
    if order is None or order.user_id != user.id:
        raise OrderNotFound("订单不存在")
    return order


async def get_invoice_for_order(
    db: AsyncSession, order_id: int,
) -> BillingInvoice | None:
    return (
        await db.execute(
            select(BillingInvoice).where(BillingInvoice.order_id == order_id)
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Public: cancel_order  (§8.2)
# --------------------------------------------------------------------------- #


_CANCEL_LEASE = timedelta(minutes=2)


async def cancel_order(
    db: AsyncSession, user: PteroUser, order_id: int,
) -> BillingOrder:
    """User-initiated cancel of a pending order. Mirrors §8.2 exactly:

    1. Atomic ``claim`` of ``lock_token`` (only succeeds if order is
       pending + owned by user + lock free or expired).
    2. Outside-tx gateway query + close — local cancellation is allowed only
       after the gateway confirms that the trade can no longer be paid.
    3. Atomic ``transition to cancelled`` guarded by lock_token + status +
       absence of any succeeded/refunded transaction (the late-payment
       race tie-break).
    4. Best-effort placeholder cleanup outside the tx.
    5. Lock release in ``finally`` (so a crash between 3 and 5 just lets
       the lease expire naturally).

    Note: §8.2's "已付款 → _safe_add_payment" branch is wired in Module 2;
    here we surface :class:`OrderAlreadyPaid` so the user gets the right
    message and the late payment is still picked up by the order_query
    job (Module 2) on its next pass.
    """
    my_token = uuid.uuid4().hex
    now = utc_naive_now()

    # ── 1) Claim
    claim = await db.execute(
        update(BillingOrder)
        .where(
            BillingOrder.id == order_id,
            BillingOrder.user_id == user.id,
            BillingOrder.status == "pending",
            or_(
                BillingOrder.lock_token.is_(None),
                BillingOrder.locked_until.is_(None),
                BillingOrder.locked_until < now,
            ),
        )
        .values(lock_token=my_token, locked_until=now + _CANCEL_LEASE)
    )
    await db.commit()
    if claim.rowcount == 0:
        # Either not owner, not pending, or another worker holds the lock.
        existing = await db.get(BillingOrder, order_id)
        if existing is None or existing.user_id != user.id:
            raise OrderNotFound("订单不存在")
        raise CannotCancel("订单状态不可取消，请稍后刷新查看")

    target_server_id: int | None = None
    try:
        invoice = await get_invoice_for_order(db, order_id)
        if invoice is None:
            # Should never happen given §6 invariants, but guard anyway.
            raise CannotCancel("订单缺失账单数据，请联系管理员")

        # ── 2) Gateway 二次确认
        gateway_code = invoice.gateway_code or "hupijiao"
        await gateway_registry.ensure_loaded(db)
        try:
            gateway = gateway_registry.get(gateway_code)
        except KeyError:
            raise GatewayUnavailable(f"支付方式 {gateway_code!r} 未启用")

        try:
            result = await gateway.query_by_out_trade_no(invoice.invoice_no)
        except GatewayError as exc:
            raise GatewayUnavailable(str(exc)) from exc

        async def record_paid_and_raise(
            paid_result: QueryResult,
        ) -> NoReturn:
            # Money landed — release lock then hand off to add_payment so
            # the apply pipeline picks it up. The user-facing response
            # still surfaces OrderAlreadyPaid.
            await db.execute(
                update(BillingOrder)
                .where(
                    BillingOrder.id == order_id,
                    BillingOrder.lock_token == my_token,
                )
                .values(lock_token=None, locked_until=None)
            )
            await db.commit()
            from app.services.billing import payments  # late import: cycle

            amount_fen = (
                paid_result.amount_fen
                if paid_result.amount_fen is not None
                else invoice.total_fen
            )
            mismatch_expected = (
                invoice.total_fen
                if (
                    paid_result.amount_fen is not None
                    and paid_result.amount_fen != invoice.total_fen
                )
                else None
            )
            await payments.safe_add_payment(
                db,
                invoice,
                gateway_code=gateway_code,
                transaction_id=paid_result.transaction_id or "",
                amount_fen=amount_fen,
                raw_event_id=None,
                amount_mismatch_expected=mismatch_expected,
            )
            raise OrderAlreadyPaid(
                "订单已支付成功，无法取消；服务正在开通中"
            )

        if result.status == "SUCCESS":
            await record_paid_and_raise(result)

        # A successful local cancellation must mean that the old cashier can
        # no longer accept money. For page.pay, NOTFOUND is not sufficient:
        # Alipay may not have created the trade yet while the already-issued
        # signed URL remains usable until time_expire.
        if result.status != "CLOSED":
            try:
                close_outcome = await gateway.close_trade(invoice.invoice_no)
            except GatewayError as exc:
                raise GatewayUnavailable(str(exc)) from exc

            if close_outcome == "ALREADY_PAID":
                try:
                    result2 = await gateway.query_by_out_trade_no(
                        invoice.invoice_no
                    )
                except GatewayError as exc:
                    raise GatewayUnavailable(
                        "支付状态正在确认，当前无法取消，请稍后重试"
                    ) from exc
                if result2.status == "SUCCESS":
                    await record_paid_and_raise(result2)
                raise GatewayUnavailable(
                    "支付宝交易状态尚未稳定，当前无法取消，请稍后重试"
                )

            if close_outcome == "NOTFOUND":
                gateway_payload = invoice.gateway_payload
                has_absolute_expiry = (
                    isinstance(gateway_payload, dict)
                    and bool(gateway_payload.get("time_expire"))
                )
                deadline_elapsed = (
                    invoice.due_at is not None
                    and utc_naive_now() >= invoice.due_at
                )
                if not has_absolute_expiry or not deadline_elapsed:
                    raise CannotCancel(
                        "支付宝交易尚未创建，无法立即撤销已打开的收银台；"
                        "请关闭收银台并等待订单自动过期"
                    )

        # ── 3) Transition pending → cancelled
        no_payment_subq = ~exists().where(
            BillingInvoiceTransaction.invoice_id == invoice.id,
            BillingInvoiceTransaction.status.in_(["succeeded", "refunded"]),
        )
        cancel_now = utc_naive_now()
        rc2 = await db.execute(
            update(BillingOrder)
            .where(
                BillingOrder.id == order_id,
                BillingOrder.lock_token == my_token,
                BillingOrder.status == "pending",
                no_payment_subq,
            )
            .values(
                status="cancelled",
                cancelled_at=cancel_now,
                lock_token=None,
                locked_until=None,
            )
        )
        if rc2.rowcount == 0:
            await db.rollback()
            raise OrderAlreadyPaid("订单状态已变化，请刷新查看")

        await db.execute(
            update(BillingInvoice)
            .where(BillingInvoice.order_id == order_id)
            .values(status="void")
        )
        target_server_id = (
            await db.scalar(
                select(BillingOrder.target_server_id).where(BillingOrder.id == order_id)
            )
        )
        await db.commit()

        # Release coupon back to ``unused`` so the user can use it on
        # their next order. Idempotent w.r.t. reservation state.
        try:
            from app.services.billing import coupons as coupon_svc
            await coupon_svc.release_for_order(db, order_id=order_id)
        except Exception:
            await db.rollback()
            logger.exception(
                "cancel_order: coupon release failed for order %s", order_id
            )

        # ── 4) Cleanup placeholder (outside tx, Wings-404-idempotent)
        order_kind = await db.scalar(
            select(BillingOrder.kind).where(BillingOrder.id == order_id)
        )
        if order_kind == "new_purchase" and target_server_id is not None:
            try:
                await server_lifecycle.delete_server(db, target_server_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "placeholder cleanup failed for cancelled order %s: %s",
                    order_id, exc,
                )
                await incidents.log_incident(
                    "placeholder_cleanup_failed",
                    order_id=order_id,
                    server_id=target_server_id,
                    payload={"phase": "cancel_order", "error": str(exc)},
                )

        await log_manager_activity(
            db,
            actor=user.username,
            category="billing",
            status="success",
            detail_key="billing.order.cancelled",
            detail_params={"order_id": order_id},
        )
    finally:
        # ── 5) Release lock if still held by us (idempotent: empty rowcount
        # if the cancel branch already cleared it).
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
            logger.exception("cancel_order: failed to release lock for %s", order_id)

    refreshed = await db.get(BillingOrder, order_id)
    assert refreshed is not None  # we just updated it
    return refreshed
