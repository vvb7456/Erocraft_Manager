"""业务订单定价、资源预留与取消；付款请求由统一网关处理。"""

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import OperationResult
from app.core.runtime_settings import AUTOMATION_SPECS, BILLING_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import local_today, utc_naive_now
from app.db.models.billing import BillingInvoice, BillingInvoiceItem, BillingOrder, BillingOrderEffect, BillingPayment, BillingPlan
from app.db.models.manager import ServerMeta
from app.db.models.pterodactyl import Allocation, PteroServer, PteroUser
from app.schemas.billing_orders import CreateOrderRequest
from app.services import panel_db, server_lifecycle
from app.services.audit import log_manager_activity
from app.services.billing import coupons, incidents, payments
from app.services.billing._ids import gen_invoice_no, gen_order_no
from app.services.billing._pricing import remaining_billable_days, upgrade_diff_fen
from app.services.billing.gateway_client import GatewayClient, GatewayError

logger = logging.getLogger(__name__)


class OrderError(Exception):
    pass


class PlanNotPurchasable(OrderError):
    pass


class InvalidOrderRequest(OrderError):
    pass


class GatewayUnavailable(OrderError):
    pass


class CannotCancel(OrderError):
    pass


class OrderAlreadyPaid(OrderError):
    pass


class OrderNotFound(OrderError):
    pass


class PendingOrderExists(OrderError):
    pass


def _build_snapshot(plan: BillingPlan, period: dict, total_fen: int, total_days: int) -> dict:
    fields = (
        "price_fen", "days", "currency_code", "egg_id", "nest_id", "node_id", "docker_image",
        "startup_command", "cpu", "memory_mb", "disk_mb", "swap_mb", "io", "database_limit",
        "backup_limit", "allocation_limit", "oom_disabled", "plan_type", "linked_plan_id",
        "llm_enabled", "llm_quota_grant", "newapi_plan_id", "llm_group",
    )
    return {
        **{key: getattr(plan, key) for key in fields}, "schema_version": 2,
        "plan_id": plan.id, "plan_name": plan.display_name, "plan_code": plan.code,
        "env_snapshot": dict(plan.env_defaults),
        "selected_period": {**period, "total_fen": total_fen, "total_days": total_days},
    }


async def create_order(db: AsyncSession, user: PteroUser, payload: CreateOrderRequest) -> BillingOrder:
    existing = await db.scalar(select(BillingOrder).where(
        BillingOrder.user_id == user.id,
        BillingOrder.status == "pending",
    ).limit(1))
    if existing is not None:
        raise PendingOrderExists(f"您有待付款的订单，请先支付或取消（订单号：{existing.order_no}）")
    try:
        await GatewayClient.load(db)
    except GatewayError as exc:
        raise GatewayUnavailable(str(exc)) from exc

    old_plan = None
    if payload.kind == "new_purchase":
        plan = await db.scalar(select(BillingPlan).where(BillingPlan.code == payload.plan_code, BillingPlan.is_active.is_(True)))
        if plan is None:
            raise PlanNotPurchasable("套餐不存在或已下架")
        if plan.plan_type == "trial" and user.has_owned_server:
            raise InvalidOrderRequest("试用套餐仅限从未拥有过服务器的用户购买")
    else:
        server = await db.get(PteroServer, payload.target_server_id)
        if server is None or server.owner_id != user.id:
            raise InvalidOrderRequest("服务器不存在或无权操作")
        meta = await db.get(ServerMeta, server.id)
        if meta is None or meta.plan_id is None:
            raise PlanNotPurchasable("此服务器未绑定套餐")
        old_plan = await db.get(BillingPlan, meta.plan_id)
        if old_plan is None:
            raise PlanNotPurchasable("此服务器关联的套餐已被删除，请联系管理员")
        if payload.kind == "convert":
            if not meta.is_trial:
                raise InvalidOrderRequest("仅试用套餐可转换为标准套餐")
            plan = await db.get(BillingPlan, old_plan.linked_plan_id) if old_plan.linked_plan_id else None
            if plan is None:
                raise PlanNotPurchasable("关联的标准套餐已被删除，请联系管理员")
        else:
            if meta.is_trial:
                raise InvalidOrderRequest("试用套餐需先转换为标准套餐")
            plan = old_plan
            if payload.kind == "upgrade":
                tz = await get_settings_store().get(db, "TIMEZONE", AUTOMATION_SPECS["TIMEZONE"].default_value())
                today = local_today(tz)
                if server.is_suspended or (server.expiration_date is not None and server.expiration_date < today):
                    raise InvalidOrderRequest("服务器不可用，无法升级")
                plan = await db.scalar(select(BillingPlan).where(
                    BillingPlan.code == payload.plan_code, BillingPlan.is_active.is_(True), BillingPlan.egg_id == server.egg_id,
                ))
                if plan is None or plan.price_fen <= old_plan.price_fen:
                    raise PlanNotPurchasable("请选择价格更高且兼容的升级套餐")

    if payload.kind == "upgrade":
        old_plan = cast(BillingPlan, old_plan)
        server = cast(PteroServer, server)
        period: dict[str, Any] = {"count": 1, "discount_pct": 0}
        total_fen = upgrade_diff_fen(old_plan, plan, remaining_billable_days(server.expiration_date, today))
        total_days = 0
        if total_fen <= 0:
            raise InvalidOrderRequest("无效的升级目标")
    else:
        selected = next((opt for opt in plan.period_options if opt["count"] == payload.period_count), None)
        if selected is None:
            raise InvalidOrderRequest("所选周期不在套餐的可选周期内")
        period = selected
        total_fen = int((Decimal(str(plan.price_fen * period["count"] * (100 - period["discount_pct"]))) / 100).quantize(Decimal("1")))
        total_days = plan.days * period["count"]
    snapshot = _build_snapshot(plan, period, total_fen, total_days)
    if payload.kind == "upgrade":
        old_plan = cast(BillingPlan, old_plan)
        snapshot["previous_plan"] = {"plan_id": old_plan.id, "plan_code": old_plan.code, "plan_name": old_plan.display_name,
                                     "price_fen": old_plan.price_fen, "days": old_plan.days}

    coupon_code = payload.coupon_code.strip().upper() if payload.coupon_code else None
    timeout = await get_settings_store().get(db, "BILLING_ORDER_PAY_TIMEOUT_MIN", BILLING_SPECS["BILLING_ORDER_PAY_TIMEOUT_MIN"].default_value())
    order = BillingOrder(order_no=gen_order_no(), user_id=user.id, plan_id=plan.id, plan_snapshot=snapshot,
                         kind=payload.kind, channel="", period_count=period["count"],
                         discount_pct=Decimal(str(period["discount_pct"])), total_fen=total_fen, total_days=total_days,
                         target_server_id=payload.target_server_id, status="pending", received_fen=0, refunded_fen=0)
    try:
        db.add(order)
        await db.flush()
        if coupon_code:
            coupon = await coupons.reserve_for_order(db, user_id=user.id, coupon_code=coupon_code, order_id=order.id,
                                                      order_kind=payload.kind, plan_id=plan.id, subtotal_fen=total_fen)
            discount = min(coupon.discount_fen, total_fen)
            order.coupon_id, order.coupon_discount_fen = coupon.id, discount
            order.total_fen -= discount
            order.plan_snapshot = {**snapshot, "coupon": {"id": coupon.id, "code": coupon.code, "template_id": coupon.template_id,
                                                         "discount_fen": coupon.discount_fen, "applied_fen": discount}}
        if order.total_fen <= 0:
            raise InvalidOrderRequest("优惠券抵扣后订单金额必须大于0")
        if payload.kind == "new_purchase":
            order.target_server_id = await _create_placeholder_server(db, user=user, order=order, plan=plan, snapshot=snapshot)
            order.reserved_node_id = plan.node_id
        invoice = BillingInvoice(invoice_no=gen_invoice_no(), order_id=order.id, user_id=user.id, status="pending",
                                 total_fen=order.total_fen, currency_code="CNY", due_at=utc_naive_now().replace(microsecond=0) + timedelta(minutes=timeout),
                                 gateway_code=None)
        db.add(invoice)
        await db.flush()
        db.add(BillingInvoiceItem(invoice_id=invoice.id, ref_type="order", ref_id=order.id,
                                  description=f"{plan.display_name}（{total_days}天）", price_fen=order.total_fen, quantity=1,
                                  meta={"plan_code": plan.code, "days_per_period": plan.days,
                                        "period_count": period["count"], "discount_pct": period["discount_pct"],
                                        **({"coupon_code": coupon_code, "coupon_discount_fen": order.coupon_discount_fen,
                                            "subtotal_fen_before_coupon": total_fen} if coupon_code else {})}))
        payments.new_payment(db, order, invoice)
        await db.commit()
    except coupons.CouponError as exc:
        await db.rollback()
        raise InvalidOrderRequest(str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        if "uk_billing_orders_active_user" in str(exc.orig):
            raise PendingOrderExists("您有待付款的订单，请先支付或取消") from exc
        raise
    except Exception:
        await db.rollback()
        raise
    await log_manager_activity(db, actor=user.username, category="billing",
                               operation=OperationResult(action="billing.order.create", phase="execution", outcome="success", target={"order_id": order.id}),
                               detail_key="billing.order.created", detail_params={"order_id": order.id, "order_no": order.order_no,
                               "order_kind": order.kind, "plan_code": plan.code, "amount_fen": order.total_fen, "period_count": order.period_count,
                               "placeholder_server_id": order.target_server_id if order.kind == "new_purchase" else None})
    return order


async def _create_placeholder_server(db: AsyncSession, *, user: PteroUser, order: BillingOrder, plan: BillingPlan, snapshot: dict) -> int:
    count = max(1, plan.allocation_limit)
    allocations = (await db.scalars(select(Allocation.id).where(
        Allocation.node_id == plan.node_id, Allocation.server_id.is_(None),
    ).order_by(Allocation.id).limit(count).with_for_update(skip_locked=True))).all()
    if len(allocations) < count:
        raise InvalidOrderRequest(f"节点可用端口不足，套餐需要 {count} 个端口")
    primary, *extras = allocations
    server = await panel_db.create_server(
        db, owner_id=user.id, node_id=plan.node_id, allocation_id=primary, egg_id=plan.egg_id, nest_id=plan.nest_id,
        name=f"{user.username}-{order.order_no[-6:]}", memory=snapshot["memory_mb"], swap=snapshot["swap_mb"], disk=snapshot["disk_mb"],
        io=snapshot["io"], cpu=snapshot["cpu"], image=snapshot["docker_image"], startup=snapshot["startup_command"],
        environment={key: str(value) for key, value in snapshot["env_snapshot"].items()},
        database_limit=snapshot["database_limit"], backup_limit=snapshot["backup_limit"], allocation_limit=snapshot["allocation_limit"],
        oom_disabled=snapshot["oom_disabled"], description=f"订单 {order.order_no}", external_id=f"pending:order-{order.id}",
        allocation_additional=extras or None,
    )
    order.reserved_allocation_id, order.reserved_additional_allocations = primary, extras or None
    return server.id


async def list_orders(db: AsyncSession, user: PteroUser, *, limit: int = 50, offset: int = 0) -> list[BillingOrder]:
    return list((await db.scalars(select(BillingOrder).where(BillingOrder.user_id == user.id)
                                 .order_by(BillingOrder.id.desc()).limit(limit).offset(offset))).all())


async def get_order(db: AsyncSession, user: PteroUser, order_id: int) -> BillingOrder:
    order = await db.get(BillingOrder, order_id)
    if order is None or order.user_id != user.id:
        raise OrderNotFound("订单不存在")
    return order


async def get_invoice_for_order(db: AsyncSession, order_id: int) -> BillingInvoice | None:
    return await db.scalar(select(BillingInvoice).where(BillingInvoice.order_id == order_id))


async def cleanup_unapplied_order(order_id: int) -> None:
    from app.db.session import get_session_factory

    # 关单已经提交；资源清理失败的回滚不能使调用方正在同步的付款对象失效。
    async with get_session_factory()() as db:
        order = (await db.scalars(select(BillingOrder).where(BillingOrder.id == order_id))).one()
        if order.kind != "new_purchase" or order.target_server_id is None or (await db.get(BillingOrderEffect, order.id)) is not None:
            return
        server_id = order.target_server_id
        if (await db.get(PteroServer, server_id)) is None:
            return
        try:
            await server_lifecycle.delete_server(db, server_id)
        except Exception as exc:
            await db.rollback()
            logger.exception("占位资源清理失败，订单 %s", order_id)
            await incidents.log_incident("placeholder_cleanup_failed", order_id=order_id, server_id=server_id,
                                          payload={"phase": "close_order", "error": str(exc)[:500]})


async def close_order(db: AsyncSession, order_id: int, *, reason: str) -> BillingOrder:
    order = await payments.locked_order(db, order_id)
    if order.status in ("cancelled", "closed"):
        return order
    if order.status != "pending":
        raise CannotCancel("订单当前不可取消，请查看付款和交付结果")
    rows = (await db.scalars(select(BillingPayment).where(BillingPayment.order_id == order_id))).all()
    if not rows:
        raise CannotCancel("旧订单请联系管理员核对并关闭")
    order.close_reason = order.close_reason or reason
    for payment in rows:
        payment.close_requested = True
    await db.commit()
    try:
        client = await GatewayClient.load(db)
        paid = False
        for payment in rows:
            if not await payments.close_payment(db, payment, client):
                paid = True
        if paid:
            order = await payments.locked_order(db, order_id)
            order.close_reason = None
            await db.commit()
            raise OrderAlreadyPaid("关闭失败：订单已付款，请查看付款或退款结果")
    except GatewayError as exc:
        raise GatewayUnavailable(str(exc)) from exc
    await db.refresh(order)
    return order


async def cancel_order(db: AsyncSession, user: PteroUser, order_id: int) -> BillingOrder:
    await get_order(db, user, order_id)
    order = await close_order(db, order_id, reason="cancelled")
    await log_manager_activity(db, actor=user.username, category="billing",
                               operation=OperationResult(action="billing.order.cancel", phase="execution", outcome="success", target={"order_id": order_id}),
                               detail_key="billing.order.cancelled", detail_params={"order_id": order_id})
    return order
