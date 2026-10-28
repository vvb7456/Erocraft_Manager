"""付款请求、收退款事实与本地业务状态同步。"""

from datetime import datetime, timezone
import json
import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import to_iso_z, utc_naive_now
from app.db.models.billing import (
    BillingInvoice, BillingInvoiceTransaction, BillingOrder, BillingPayment,
    BillingPaymentEvent, BillingRefund,
)
from app.services.billing._ids import gen_refund_no
from app.services.billing.gateway_client import GatewayClient, GatewayError

ACTIVE_REFUNDS = ("pending", "unknown", "processing", "action_required")
PAYMENT_CHANNELS = {
    "alipay_page": "alipay",
    "alipay_wap": "alipay",
    "wechat_native": "wechat",
    "wechat_jsapi": "wechat",
    "wechat_mini": "wechat",
    "alipay": "alipay",
    "wechat": "wechat",
    # 历史账目保存旧适配器名称；虎皮椒当时只接入支付宝。
    "alipay_direct": "alipay",
    "alipay_mock": "alipay",
    "hupijiao": "alipay",
    "wechat_pay": "wechat",
}


async def locked_order(db: AsyncSession, order_id: int) -> BillingOrder:
    return (await db.scalars(select(BillingOrder).where(BillingOrder.id == order_id)
                            .with_for_update().execution_options(populate_existing=True))).one()


def new_payment(db: AsyncSession, order: BillingOrder, invoice: BillingInvoice) -> BillingPayment:
    request_id = uuid.uuid4().hex
    payment = BillingPayment(
        order_id=order.id, invoice_id=invoice.id, request_id=request_id,
        request_body={
            "request_id": request_id, "business_order_id": order.order_no,
            "amount": invoice.total_fen, "currency": invoice.currency_code,
            "title": order.plan_snapshot["plan_name"][:120],
            "expires_at": to_iso_z(invoice.due_at),
        },
        status="pending", close_requested=False, channel_refunding=False,
    )
    db.add(payment)
    return payment


async def current_payment(db: AsyncSession, order_id: int) -> BillingPayment | None:
    return await db.scalar(select(BillingPayment).where(BillingPayment.order_id == order_id)
                           .order_by(BillingPayment.id.desc()).limit(1))


async def ensure_created(db: AsyncSession, payment: BillingPayment, client: GatewayClient) -> None:
    if payment.gateway_id is not None or payment.status == "closed":
        return
    body = payment.request_body
    await db.commit()
    try:
        result = await client.request("POST", "/api/v1/payments", body)
    except GatewayError as exc:
        order = await locked_order(db, payment.order_id)
        await db.refresh(payment)
        # 原请求到期后重放：网关会返回已有单；invalid_expiry 明确表示从未建单。
        if exc.code == "invalid_expiry":
            payment.status = "closed"
            await db.flush()
            await update_order_state(db, order)
        payment.last_error = str(exc)[:500]
        await db.commit()
        if exc.code != "invalid_expiry":
            raise
        if order.status in ("closed", "cancelled"):
            from app.services.billing.orders import cleanup_unapplied_order
            await cleanup_unapplied_order(order.id)
        return
    await locked_order(db, payment.order_id)
    await db.refresh(payment)
    payment.gateway_id = result["id"]
    payment.checkout_url = result["checkout_url"]
    payment.last_error = None
    await db.commit()


async def checkout(db: AsyncSession, order_id: int, *, replace: bool = False) -> BillingPayment:
    client = await GatewayClient.load(db)
    order = await locked_order(db, order_id)
    invoice = (await db.scalars(select(BillingInvoice).where(BillingInvoice.order_id == order_id))).one()
    payment = await current_payment(db, order_id)
    if payment is None:
        raise GatewayError("legacy_payment", "旧订单不再生成付款链接，请联系管理员核对并关闭", 409)
    if order.status != "pending" or order.close_reason or cast(datetime, invoice.due_at) <= utc_naive_now():
        raise GatewayError("not_payable", "订单当前无法付款，请查看最新结果", 409)
    if replace:
        old = (await db.scalars(select(BillingPayment).where(
            BillingPayment.order_id == order_id, BillingPayment.status != "closed",
        ))).all()
        for row in old:
            row.close_requested = True
        payment = new_payment(db, order, invoice)
    await db.commit()
    await ensure_created(db, payment, client)
    if payment.status == "closed":
        raise GatewayError("not_payable", "订单已到期，请重新下单", 409)
    if replace:
        # 新付款已建好；旧付款的关单意图已保存，网络失败由后台继续。
        already_paid = False
        for row in old:
            try:
                if not await close_payment(db, row, client):
                    already_paid = True
            except GatewayError:
                pass
        if already_paid:
            payment.close_requested = True
            await db.commit()
            await close_payment(db, payment, client)
            raise GatewayError("payment_already_paid", "订单已付款，请查看付款结果", 409)
    return payment


async def update_order_state(db: AsyncSession, order: BillingOrder) -> None:
    txs = (await db.scalars(select(BillingInvoiceTransaction).join(BillingInvoice).where(
        BillingInvoice.order_id == order.id,
        BillingInvoiceTransaction.status.in_(("succeeded", "refunded")),
    ).order_by(BillingInvoiceTransaction.id).execution_options(populate_existing=True))).all()
    refunds = (await db.scalars(select(BillingRefund).where(
        BillingRefund.order_id == order.id, BillingRefund.automatic.is_(False),
    ).execution_options(populate_existing=True))).all()
    blocked = {row.transaction_id for row in refunds if row.status in ACTIVE_REFUNDS}
    order.received_fen = sum(tx.amount_fen for tx in txs)
    order.refunded_fen = sum(tx.refunded_fen for tx in txs)
    attempts = (await db.scalars(select(BillingPayment).where(
        BillingPayment.order_id == order.id,
    ).order_by(BillingPayment.id))).all()
    review_payments = {row.id for row in attempts if row.status == "review" or row.channel_refunding}
    usable = sum(tx.amount_fen - tx.refunded_fen for tx in txs if tx.id not in blocked and tx.payment_id not in review_payments)
    invoice = (await db.scalars(select(BillingInvoice).where(BillingInvoice.order_id == order.id))).one()
    if attempts:
        method = txs[0].gateway_code if txs else attempts[-1].method
        order.channel = PAYMENT_CHANNELS[method] if method is not None else ""
        invoice.gateway_code = order.channel or None
        if txs:
            paid_payment = next(row for row in attempts if row.id == txs[0].payment_id)
            invoice.paid_at = paid_payment.paid_at
    if order.received_fen:
        invoice.status = "paid"
    if order.status in ("closed", "cancelled"):
        return
    if not order.received_fen and attempts and all(row.status == "closed" for row in attempts):
        from app.services.billing.coupons import release_for_order
        order.status = order.close_reason or "closed"
        if order.status == "cancelled":
            order.cancelled_at = utc_naive_now()
        else:
            order.closed_at = utc_naive_now()
        order.close_reason = None
        invoice.status = "void"
        await release_for_order(db, order_id=order.id, commit=False)
        return
    if any(row.status == "review" for row in attempts) and order.status == "pending":
        order.status = "manual_review"
    if usable >= order.total_fen:
        order.close_reason = None
        if order.applied_at is not None:
            order.status = "applied"
        elif order.status not in ("processing", "apply_failed"):
            order.status = "processing"
            order.next_apply_at = utc_naive_now()
    elif order.received_fen:
        order.status = "refunded" if order.refunded_fen == order.received_fen else "refunding" if blocked else "manual_review"
        order.next_apply_at = None
        order.close_reason = None
        if order.applied_at is None and order.status == "refunded" and not order.lock_token:
            from app.services.billing.coupons import release_for_order
            await release_for_order(db, order_id=order.id, commit=False)


async def record_refund(db: AsyncSession, order: BillingOrder, payment: BillingPayment, data: dict) -> tuple[BillingRefund, bool]:
    row = await db.scalar(select(BillingRefund).where(BillingRefund.request_id == data["request_id"]).execution_options(populate_existing=True))
    tx = await db.scalar(select(BillingInvoiceTransaction).where(BillingInvoiceTransaction.payment_id == payment.id).execution_options(populate_existing=True))
    if row is None:
        row = BillingRefund(
            refund_no=gen_refund_no(), order_id=order.id, payment_id=payment.id,
            transaction_id=tx.id if tx is not None else None,
            request_id=data["request_id"], amount_fen=payment.request_body["amount"],
            reason=data["reason"], automatic=data["automatic"],
        )
        db.add(row)
    row.gateway_refund_id = data["id"]
    row.updated_at = utc_naive_now()
    completed = row.status != "succeeded" and data["status"] == "succeeded" and not row.automatic and tx is not None
    if row.status not in ("succeeded", "failed") or data["status"] == "succeeded":
        row.status = data["status"]
        row.last_error = data["last_error"]
    if row.status == "succeeded" and not row.automatic and tx is not None:
        tx.status = "refunded"
        tx.refunded_fen = tx.amount_fen
        row.transaction_id = tx.id
    await db.flush()
    return row, completed


async def record_snapshot(db: AsyncSession, payment_id: int, data: dict, *, event: dict | None = None, refund: dict | None = None) -> None:
    payment = (await db.scalars(select(BillingPayment).where(BillingPayment.id == payment_id))).one()
    order = await locked_order(db, payment.order_id)
    previous_status = order.status
    await db.refresh(payment)
    if event is not None and await db.scalar(select(BillingPaymentEvent.id).where(BillingPaymentEvent.gateway_event_id == event["id"])):
        await db.commit()
        return
    payment.gateway_id = data["id"]
    # 页面查单和通知会重叠；早先未选渠道、未收款的快照不能清除后来确认的事实。
    if payment.status == "pending" or data["status"] != "pending":
        if payment.status != "closed":
            payment.status = data["status"]
        if data["method"] is not None:
            payment.method = data["method"]
        payment.channel_refunding = payment.channel_refunding or data["channel_refunding"]
        if data["transaction_id"] is not None:
            payment.transaction_id = data["transaction_id"]
            payment.paid_at = (datetime.fromisoformat(data["paid_at"]).astimezone(timezone.utc).replace(tzinfo=None)
                               if data["paid_at"] is not None else None)
        payment.last_error = data["last_error"]
    payment.synced_at = utc_naive_now()
    if payment.status == "paid":
        tx = await db.scalar(select(BillingInvoiceTransaction).where(BillingInvoiceTransaction.payment_id == payment.id))
        if tx is None:
            tx = BillingInvoiceTransaction(
                invoice_id=payment.invoice_id, payment_id=payment.id, gateway_code=PAYMENT_CHANNELS[cast(str, payment.method)],
                transaction_id=payment.transaction_id, amount_fen=data["amount"],
                status="succeeded", refunded_fen=0,
            )
            db.add(tx)
            await db.flush()
    completed_refunds = []
    if data["refund"] is not None:
        row, completed = await record_refund(db, order, payment, data["refund"])
        if completed:
            completed_refunds.append(row.id)
    if refund is not None and (data["refund"] is None or refund["id"] != data["refund"]["id"]):
        row, completed = await record_refund(db, order, payment, refund)
        if completed:
            completed_refunds.append(row.id)
    if event is not None:
        db.add(BillingPaymentEvent(
            gateway_code="gateway", gateway_event_id=event["id"], event_type=event["type"],
            signature_ok=True, invoice_id=payment.invoice_id, transaction_id=payment.transaction_id,
            raw_body=json.dumps(event, ensure_ascii=False), received_at=utc_naive_now(),
            processed_at=utc_naive_now(), process_result="ok",
        ))
    await db.flush()
    await update_order_state(db, order)
    await db.commit()
    from app.services.billing.notify import notify_order_refunded
    for refund_id in completed_refunds:
        await notify_order_refunded(order.id, refund_id)
    if order.status != previous_status and order.status in ("closed", "cancelled", "refunded") and order.applied_at is None and not order.lock_token:
        from app.services.billing.orders import cleanup_unapplied_order
        await cleanup_unapplied_order(order.id)


async def sync_payment(db: AsyncSession, payment: BillingPayment, client: GatewayClient, *, refund: dict | None = None) -> None:
    await ensure_created(db, payment, client)
    if payment.gateway_id is None:
        return
    payment_id, gateway_id = payment.id, payment.gateway_id
    await db.commit()
    data = await client.request("GET", f"/api/v1/payments/{gateway_id}")
    await record_snapshot(db, payment_id, data, refund=refund)


async def close_payment(db: AsyncSession, payment: BillingPayment, client: GatewayClient) -> bool:
    await ensure_created(db, payment, client)
    if payment.status == "closed":
        return True
    gateway_id = payment.gateway_id
    await db.commit()
    try:
        result = await client.request("POST", f"/api/v1/payments/{gateway_id}/close")
    except GatewayError as exc:
        if exc.code != "payment_already_paid":
            raise
        await sync_payment(db, payment, client)
        return False
    await record_snapshot(db, payment.id, {**result["payment"], "refund": None})
    return True


async def receive_event(db: AsyncSession, event: dict, client: GatewayClient) -> None:
    if await db.scalar(select(BillingPaymentEvent.id).where(BillingPaymentEvent.gateway_event_id == event["id"])):
        return
    gateway_id = event["data"]["id"] if event["type"] == "payment.paid" else event["data"]["payment_id"]
    await db.commit()
    data = await client.request("GET", f"/api/v1/payments/{gateway_id}")
    payment = (await db.scalars(select(BillingPayment).where(BillingPayment.request_id == data["request_id"]))).one()
    await record_snapshot(db, payment.id, data, event=event,
                          refund=event["data"] if event["type"].startswith("refund.") else None)


async def record_legacy_payment(db: AsyncSession, invoice: BillingInvoice, *, transaction_id: str,
                                amount_fen: int, paid_at: datetime | None) -> BillingInvoiceTransaction:
    """切换期旧通知：只按旧账落账，晚到收款仍由管理员处理。"""
    order = await locked_order(db, invoice.order_id)
    tx = await db.scalar(select(BillingInvoiceTransaction).where(
        BillingInvoiceTransaction.gateway_code == "alipay_direct",
        BillingInvoiceTransaction.transaction_id == transaction_id,
    ))
    if tx is not None:
        await db.commit()
        return tx
    tx = BillingInvoiceTransaction(invoice_id=invoice.id, gateway_code="alipay_direct", transaction_id=transaction_id,
                                   amount_fen=amount_fen, status="succeeded", refunded_fen=0)
    db.add(tx)
    order.received_fen += amount_fen
    if order.status in ("closed", "cancelled"):
        order.status = "manual_review"
    elif order.status == "pending":
        invoice.status = "paid"
        invoice.paid_at = paid_at
        order.status = "processing"
        order.next_apply_at = utc_naive_now()
    await db.commit()
    return tx
