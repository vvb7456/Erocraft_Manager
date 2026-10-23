"""账单关单、付款同步、交付及退款结果的后台推进。"""

import logging
from datetime import timedelta

from sqlalchemy import exists, or_, select

from app.core.time import utc_naive_now
from app.db.models.billing import BillingInvoice, BillingOrder, BillingPayment, BillingOrderEffect, BillingIncident
from app.db.models.pterodactyl import PteroServer
from app.db.session import get_session_factory
from app.services.billing import orders, payments, refunds, incidents
from app.services.billing.apply_engine import apply_paid_order
from app.services.billing.gateway_client import GatewayClient

logger = logging.getLogger(__name__)
ORDER_CLOSE_JOB_ID = "billing_order_close"
ORDER_QUERY_JOB_ID = "billing_order_query"
APPLY_RETRY_JOB_ID = "billing_apply_retry"
REFUND_RETRY_JOB_ID = "billing_refund_retry"
PLACEHOLDER_LEAK_JOB_ID = "billing_placeholder_leak_monitor"


async def run_order_close() -> None:
    factory = get_session_factory()
    async with factory() as db:
        ids = (await db.scalars(select(BillingOrder.id).join(BillingInvoice).where(
            BillingOrder.status == "pending",
            exists().where(BillingPayment.order_id == BillingOrder.id),
            or_(BillingInvoice.due_at <= utc_naive_now(), BillingOrder.close_reason.is_not(None)),
        ).limit(100))).all()
    for order_id in ids:
        async with factory() as db:
            try:
                await orders.close_order(db, order_id, reason="closed")
            except orders.OrderAlreadyPaid:
                pass
            except Exception:
                logger.exception("关单待重试，order=%s", order_id)
    async with factory() as db:
        ids = (await db.scalars(select(BillingPayment.id).where(
            BillingPayment.close_requested.is_(True), BillingPayment.status.in_(("pending", "review")),
        ).limit(100))).all()
    for payment_id in ids:
        async with factory() as db:
            try:
                payment = (await db.scalars(select(BillingPayment).where(BillingPayment.id == payment_id))).one()
                await payments.close_payment(db, payment, await GatewayClient.load(db))
            except Exception:
                logger.exception("旧付款请求关单待重试，payment=%s", payment_id)


async def run_order_query() -> None:
    factory = get_session_factory()
    async with factory() as db:
        ids = (await db.scalars(select(BillingPayment.id).where(or_(
            BillingPayment.status.in_(("pending", "review")),
            BillingPayment.created_at >= utc_naive_now() - timedelta(days=1),
        )).order_by(BillingPayment.synced_at).limit(100))).all()
    for payment_id in ids:
        async with factory() as db:
            try:
                payment = (await db.scalars(select(BillingPayment).where(BillingPayment.id == payment_id))).one()
                await payments.sync_payment(db, payment, await GatewayClient.load(db))
            except Exception:
                logger.exception("付款同步待重试，payment=%s", payment_id)


async def run_apply_retry() -> None:
    factory = get_session_factory()
    async with factory() as db:
        now = utc_naive_now()
        ids = (await db.scalars(select(BillingOrder.id).where(
            BillingOrder.status == "processing",
            or_(BillingOrder.lock_token.is_(None), BillingOrder.locked_until < now),
            or_(BillingOrder.next_apply_at.is_(None), BillingOrder.next_apply_at <= now),
        ).limit(100))).all()
    for order_id in ids:
        async with factory() as db:
            try:
                await apply_paid_order(db, order_id, source="retry")
            except Exception:
                logger.exception("业务交付待重试，order=%s", order_id)
    from app.services.billing.delivery import report_deliveries
    await report_deliveries()


async def run_refund_retry() -> None:
    factory = get_session_factory()
    async with factory() as db:
        ids = [row.id for row in await refunds.list_pending_refunds(db)]
    for refund_id in ids:
        async with factory() as db:
            try:
                await refunds.reconcile_refund_once(db, refund_id)
            except Exception:
                logger.exception("退款同步待重试，refund=%s", refund_id)


async def run_placeholder_leak_monitor() -> None:
    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(select(BillingOrder.id, BillingOrder.target_server_id).join(
            PteroServer, PteroServer.id == BillingOrder.target_server_id,
        ).where(
            BillingOrder.kind == "new_purchase", BillingOrder.status.in_(("closed", "cancelled", "refunded")),
            PteroServer.external_id.like("pending:%"),
            ~exists().where(BillingOrderEffect.order_id == BillingOrder.id),
            ~exists().where((BillingIncident.order_id == BillingOrder.id) & (BillingIncident.kind == "placeholder_leak") & (BillingIncident.status == "open")),
        ).limit(100))).all()
    for order_id, server_id in rows:
        await incidents.log_incident("placeholder_leak", order_id=order_id, server_id=server_id,
                                     payload={"reason": "未交付的已结束订单仍有占位服务器"})
