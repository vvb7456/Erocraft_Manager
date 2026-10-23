"""按具体支付单申请全额退款；明确失败后由管理员重新申请。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import BillingInvoiceTransaction, BillingPayment, BillingRefund
from app.services.billing import payments
from app.services.billing._ids import gen_refund_no
from app.services.billing.gateway_client import GatewayClient, GatewayError


class CannotRefund(Exception):
    pass


async def initiate_refund(db: AsyncSession, *, order_id: int, transaction_id: int, reason: str, admin_id: int | None) -> BillingRefund:
    client = await GatewayClient.load(db)
    order = await payments.locked_order(db, order_id)
    tx = (await db.scalars(select(BillingInvoiceTransaction).where(BillingInvoiceTransaction.id == transaction_id))).one()
    if tx.payment_id is None:
        raise CannotRefund("旧交易请在原商户平台人工处理退款")
    payment = (await db.scalars(select(BillingPayment).where(BillingPayment.id == tx.payment_id))).one()
    existing = await db.scalar(select(BillingRefund).where(
        BillingRefund.payment_id == payment.id, BillingRefund.status.in_((*payments.ACTIVE_REFUNDS, "succeeded")),
    ))
    if existing is not None:
        await db.commit()
        return existing
    refund = BillingRefund(
        refund_no=gen_refund_no(), request_id=uuid.uuid4().hex, payment_id=payment.id,
        transaction_id=tx.id, order_id=order_id, amount_fen=tx.amount_fen, status="pending",
        reason=reason, initiated_by=admin_id, automatic=False,
    )
    db.add(refund)
    await db.flush()
    await payments.update_order_state(db, order)
    await db.commit()
    await reconcile_refund_once(db, refund.id, client=client)
    await db.refresh(refund)
    return refund


async def list_pending_refunds(db: AsyncSession, *, limit: int = 100) -> list[BillingRefund]:
    return list((await db.scalars(select(BillingRefund).where(
        BillingRefund.payment_id.is_not(None), BillingRefund.status.in_(payments.ACTIVE_REFUNDS),
    ).order_by(BillingRefund.updated_at).limit(limit))).all())


async def reconcile_refund_once(db: AsyncSession, refund_id: int, *, client: GatewayClient | None = None, query_channel: bool = False) -> str:
    refund = (await db.scalars(select(BillingRefund).where(BillingRefund.id == refund_id))).one()
    if refund.payment_id is None:
        raise CannotRefund("旧退款请在原商户平台人工核对")
    payment = (await db.scalars(select(BillingPayment).where(BillingPayment.id == refund.payment_id))).one()
    client = client or await GatewayClient.load(db)
    gateway_id, request_id, reason = payment.gateway_id, refund.request_id, refund.reason
    remote_id = refund.gateway_refund_id
    if remote_id is None and refund.status == "failed":
        return refund.status
    await db.commit()
    try:
        if remote_id is None:
            data = await client.request("POST", f"/api/v1/payments/{gateway_id}/refunds", {"request_id": request_id, "reason": reason})
        else:
            method = "POST" if query_channel else "GET"
            data = await client.request(method, f"/api/v1/refunds/{remote_id}" + ("/retry" if query_channel else ""))
    except GatewayError as exc:
        await payments.locked_order(db, refund.order_id)
        await db.refresh(refund)
        refund.last_error = str(exc)[:500]
        refund.updated_at = utc_naive_now()
        if remote_id is None and exc.code in ("not_paid", "refund_exists", "external_refund"):
            refund.status = "failed"
        await db.commit()
        if refund.status == "failed":
            await payments.sync_payment(db, payment, client)
        raise
    await payments.sync_payment(db, payment, client, refund=data)
    await db.refresh(refund)
    return refund.status
