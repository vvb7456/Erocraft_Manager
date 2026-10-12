"""WeChat payment orchestration; immutable requests and the existing order lease."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import BillingInvoice, BillingOrder
from app.db.models.wechat import WechatPaymentSession
from app.services.billing import incidents, payments
from app.services.billing.gateway import registry
from app.services.billing.gateway.base import CreateInvoiceRequest, GatewayBusinessError, GatewayPayloadError, GatewayTransientError, PaymentGateway, QueryResult
from app.services.billing.gateway.wechat_pay import WechatPayGateway
from app.services.billing.orders import _runtime_site_url


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def gateway(db: AsyncSession) -> WechatPayGateway:
    await registry.ensure_loaded(db)
    try:
        result = registry.get("wechat_pay")
    except KeyError as exc:
        raise GatewayBusinessError("微信支付尚未启用") from exc
    assert isinstance(result, WechatPayGateway)
    return result


def verify_invoice(invoice: BillingInvoice, data: dict[str, Any]) -> None:
    saved = (invoice.gateway_payload or {}).get("request", {})
    if invoice.gateway_code != "wechat_pay" or not saved or any(
        data.get(key) != saved.get(key) for key in ("mchid", "appid", "out_trade_no")
    ):
        raise GatewayPayloadError("wechat_pay payment does not match the invoice request")


async def query_invoice(db: AsyncSession, invoice: BillingInvoice, adapter: PaymentGateway) -> QueryResult:
    saved = invoice.gateway_payload or {}
    if invoice.gateway_code == "wechat_pay":
        if not saved.get("request"):
            return QueryResult("CLOSED", None, None)
        if not isinstance(adapter, WechatPayGateway) or saved["request"]["mchid"] != adapter.mchid:
            raise GatewayBusinessError("原订单的微信商户号已变更，请先恢复配置")
    result = await adapter.query_by_out_trade_no(invoice.invoice_no)
    if invoice.gateway_code == "wechat_pay" and result.status != "NOTFOUND":
        verify_invoice(invoice, result.raw)
    if result.status == "REFUNDED":
        await db.execute(update(BillingOrder).where(BillingOrder.id == invoice.order_id, BillingOrder.status == "pending").values(status="manual_review"))
        await db.commit()
        await incidents.log_incident("manual_review_required", invoice_id=invoice.id, order_id=invoice.order_id,
                                     payload={"subkind": "wechat_refunded_outside_manager", "transaction_id": result.transaction_id})
        raise GatewayBusinessError("微信订单已转入退款，需要核对商户平台退款记录")
    return result


async def new_session(db: AsyncSession, invoice: BillingInvoice, scene: str, appid: str) -> tuple[WechatPaymentSession, str]:
    assert invoice.due_at is not None
    token = secrets.token_urlsafe(32)
    session = WechatPaymentSession(
        invoice_id=invoice.id, token_hash=token_hash(token), scene=scene, appid=appid,
        # Allow a short result-checking window after the payment deadline.
        expires_at=invoice.due_at + timedelta(minutes=15),
    )
    db.add(session)
    await db.commit()
    return session, token


async def prepare_payment(db: AsyncSession, invoice: BillingInvoice, scene: str, *, appid: str, openid: str | None = None) -> dict[str, Any]:
    adapter = await gateway(db)
    oid, iid = invoice.order_id, invoice.id
    lease = secrets.token_hex(16)
    now = utc_naive_now()
    result = await db.execute(update(BillingOrder).where(
        BillingOrder.id == oid, BillingOrder.status == "pending",
        or_(BillingOrder.lock_token.is_(None), BillingOrder.locked_until < now),
    ).values(lock_token=lease, locked_until=now + timedelta(minutes=2)))
    await db.commit()
    if not result.rowcount:
        raise GatewayBusinessError("订单正在处理，请刷新后重试")
    try:
        await db.refresh(invoice)
        if invoice.status != "pending" or invoice.due_at is None or invoice.due_at <= utc_naive_now():
            raise GatewayBusinessError("订单已支付或已过期，请刷新订单")
        if invoice.currency_code != "CNY":
            raise GatewayBusinessError("微信支付仅支持人民币")
        saved = invoice.gateway_payload or {}
        if saved.get("request"):
            original = saved["request"]
            if saved["scene"] != scene or original["appid"] != appid or original.get("payer", {}).get("openid") != openid:
                raise GatewayBusinessError("这笔订单已使用其他付款入口或微信账号，请继续原付款流程，或取消后重新下单")
            if original["mchid"] != adapter.mchid:
                raise GatewayBusinessError("原订单的微信商户号已变更，请联系管理员")
        else:
            order = await db.get(BillingOrder, oid)
            assert order is not None
            site = (await _runtime_site_url(db)).rstrip("/")
            original = adapter.invoice_payload(CreateInvoiceRequest(
                invoice_no=invoice.invoice_no, amount_fen=invoice.total_fen,
                title=str(order.plan_snapshot.get("plan_name", "Erocraft")),
                notify_url=f"{site}/api/webhook/wechat_pay", return_url="", due_at=invoice.due_at,
                payment_appid=appid, payer_openid=openid,
            ))
            saved = {"scene": scene, "request": original, "time_expire": original["time_expire"]}
        if not invoice.gateway_prepay_id and not invoice.gateway_code_url:
            # WeChat silently extends deadlines shorter than one minute.
            # Leave 30 seconds for transport; retries use the same deadline.
            if invoice.due_at - utc_naive_now() < timedelta(seconds=90):
                raise GatewayBusinessError("剩余付款时间不足，请取消订单后重新下单")
            invoice.gateway_payload = saved
            await db.commit()
            try:
                async with asyncio.timeout(20):
                    created = await adapter.create_payment(original)
            except TimeoutError as exc:
                raise GatewayTransientError("微信下单响应超时，订单已保留，请稍后重试") from exc
            await db.execute(update(BillingInvoice).where(BillingInvoice.id == iid).values(
                gateway_prepay_id=created.gateway_order_id, gateway_code_url=created.code_url,
            ))
            await db.commit()
            await db.refresh(invoice)
        if scene == "native":
            return {"scene": scene, "code_url": invoice.gateway_code_url}
        assert invoice.gateway_prepay_id
        return {"scene": scene, "parameters": adapter.payment_parameters(appid, invoice.gateway_prepay_id)}
    finally:
        await db.execute(update(BillingOrder).where(BillingOrder.id == oid, BillingOrder.lock_token == lease).values(lock_token=None, locked_until=None))
        await db.commit()


async def refresh_payment(db: AsyncSession, invoice: BillingInvoice) -> None:
    oid = invoice.order_id
    now = utc_naive_now()
    lease = secrets.token_hex(16)
    # The timestamp is a DB cursor, so multiple browser tabs/workers share the throttle.
    acquired = await db.execute(update(BillingOrder).where(
        BillingOrder.id == oid, BillingOrder.status == "pending",
        or_(BillingOrder.lock_token.is_(None), BillingOrder.locked_until < now),
    ).values(lock_token=lease, locked_until=now + timedelta(seconds=20)))
    await db.commit()
    if not acquired.rowcount:
        return
    try:
        adapter = await gateway(db)
        await db.refresh(invoice)
        saved = dict(invoice.gateway_payload or {})
        if not saved.get("request") or float(saved.get("last_query_at", 0)) > time.time() - 5:
            return
        saved["last_query_at"] = time.time()
        invoice.gateway_payload = saved
        await db.commit()
        result = await query_invoice(db, invoice, adapter)
        if result.status == "SUCCESS":
            assert result.transaction_id is not None and result.amount_fen is not None
            await payments.safe_add_payment(
                db, invoice, gateway_code="wechat_pay", transaction_id=result.transaction_id,
                amount_fen=result.amount_fen, raw_event_id=None, defer_apply=True,
                amount_mismatch_expected=invoice.total_fen if result.amount_fen != invoice.total_fen else None,
            )
    finally:
        await db.execute(update(BillingOrder).where(BillingOrder.id == oid, BillingOrder.lock_token == lease).values(lock_token=None, locked_until=None))
        await db.commit()
