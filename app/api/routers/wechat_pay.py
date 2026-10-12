"""Website cashier, official-account OAuth and payment-only mini program APIs."""

from __future__ import annotations

import secrets
from datetime import timezone
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.rate_limit import limiter
from app.core.runtime_settings import BILLING_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import to_iso_z, utc_naive_now
from app.db.models.billing import BillingInvoice, BillingOrder
from app.db.models.pterodactyl import PteroUser
from app.db.models.wechat import WechatPaymentSession
from app.services import wechat_client
from app.services.billing import wechat_pay as service
from app.services.billing.gateway.base import GatewayError
from app.services.billing.orders import _runtime_site_url

router = APIRouter(prefix="/payments/wechat", tags=["billing"])


class PrepareInput(BaseModel):
    scene: Literal["native", "jsapi", "miniprogram"]


class MiniInput(BaseModel):
    ticket: str = Field(min_length=40, max_length=64)


class MiniPayInput(MiniInput):
    code: str = Field(min_length=1, max_length=256)


async def _settings(db: AsyncSession) -> dict:
    return await get_settings_store().get_many(db, defaults_for(BILLING_SPECS))


async def _owned_invoice(db: AsyncSession, oid: int, user: PteroUser) -> BillingInvoice:
    invoice = await db.scalar(select(BillingInvoice).where(BillingInvoice.order_id == oid, BillingInvoice.user_id == user.id, BillingInvoice.gateway_code == "wechat_pay"))
    if invoice is None:
        raise HTTPException(404, "微信订单不存在")
    return invoice


def _payable(invoice: BillingInvoice) -> None:
    if invoice.status != "pending" or not invoice.due_at or invoice.due_at <= utc_naive_now():
        raise HTTPException(409, "订单已支付或已过期，请刷新订单")


@router.post("/orders/{oid}/prepare")
@limiter.limit("15/minute")
async def prepare(oid: int, payload: PrepareInput, request: Request, response: Response, user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    invoice = await _owned_invoice(db, oid, user)
    _payable(invoice)
    try:
        adapter = await service.gateway(db)
        saved_scene = (invoice.gateway_payload or {}).get("scene")
        if saved_scene and saved_scene != payload.scene:
            raise HTTPException(409, "这笔订单已选择其他付款入口，请继续原付款流程，或取消后重新下单")
        if payload.scene == "native":
            return await service.prepare_payment(db, invoice, "native", appid=adapter.appid)
        values = await _settings(db)
        if payload.scene == "jsapi":
            previous = await db.get(WechatPaymentSession, request.session.get("wechat_payment_id", 0))
            if previous and previous.invoice_id == invoice.id and previous.appid == adapter.appid and previous.openid and previous.expires_at > utc_naive_now():
                return await service.prepare_payment(db, invoice, "jsapi", appid=previous.appid, openid=previous.openid)
            if not values.get("WECHAT_PAY_APP_SECRET"):
                raise HTTPException(409, "服务号网页授权尚未配置")
            session, _ = await service.new_session(db, invoice, "jsapi", adapter.appid)
            state = secrets.token_urlsafe(24)
            session.oauth_state_hash = service.token_hash(state)
            await db.commit()
            request.session["wechat_payment_id"] = session.id
            site = (await _runtime_site_url(db)).rstrip("/")
            query = urlencode({"appid": adapter.appid, "redirect_uri": f"{site}/api/payments/wechat/oauth/callback", "response_type": "code", "scope": "snsapi_base", "state": state})
            return {"scene": "jsapi", "authorize_url": f"https://open.weixin.qq.com/connect/oauth2/authorize?{query}#wechat_redirect"}
        if not adapter.miniprogram_appid or not values.get("WECHAT_PAY_MINIPROGRAM_APP_SECRET"):
            raise HTTPException(409, "付款小程序尚未配置，请联系管理员")
        session, ticket = await service.new_session(db, invoice, "miniprogram", adapter.miniprogram_appid)
        data = await wechat_client.account_request("mini", adapter.miniprogram_appid, values["WECHAT_PAY_MINIPROGRAM_APP_SECRET"], "/wxa/generate_urllink", {
            "path": "pages/pay/index", "query": urlencode({"ticket": ticket}), "env_version": "release",
            "expire_type": 0, "expire_time": int(session.expires_at.replace(tzinfo=timezone.utc).timestamp()),
        })
        return {"scene": "miniprogram", "url_link": data["url_link"]}
    except GatewayError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = Query("", max_length=256), state: str = Query("", max_length=128), db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    session = await db.get(WechatPaymentSession, request.session.get("wechat_payment_id", 0))
    if not session or session.scene != "jsapi" or session.expires_at <= utc_naive_now() or not state:
        raise HTTPException(400, "授权已失效，请回到订单页面重新付款")
    invoice = await db.get(BillingInvoice, session.invoice_id)
    assert invoice is not None
    site = (await _runtime_site_url(db)).rstrip("/")
    target = f"{site}/#/pay/{invoice.order_id}"
    claimed = await db.execute(update(WechatPaymentSession).where(
        WechatPaymentSession.id == session.id,
        WechatPaymentSession.oauth_state_hash == service.token_hash(state),
    ).values(oauth_state_hash=None))
    await db.commit()
    if not claimed.rowcount:
        raise HTTPException(400, "授权已使用或不匹配，请重新发起付款")
    try:
        _payable(invoice)
        if not code:
            raise HTTPException(400, "微信授权已取消")
        values = await _settings(db)
        if session.appid != values["WECHAT_PAY_APPID"]:
            raise HTTPException(409, "微信AppID配置已变更，请重新授权")
        session.openid = await wechat_client.openid(session.appid, values["WECHAT_PAY_APP_SECRET"], code, mini=False)
        await db.commit()
    except (GatewayError, HTTPException):
        target += "?wechat=auth_failed"
    return RedirectResponse(target, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/orders/{oid}/refresh")
@limiter.limit("20/minute")
async def refresh(oid: int, request: Request, user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    invoice = await _owned_invoice(db, oid, user)
    try:
        await service.refresh_payment(db, invoice)
    except GatewayError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}


async def _mini_session(db: AsyncSession, ticket: str) -> tuple[WechatPaymentSession, BillingInvoice]:
    session = await db.scalar(select(WechatPaymentSession).where(
        WechatPaymentSession.token_hash == service.token_hash(ticket),
        WechatPaymentSession.scene == "miniprogram", WechatPaymentSession.expires_at > utc_naive_now(),
    ))
    if session is None:
        raise HTTPException(404, "付款链接已失效，请回到网站查看订单")
    invoice = await db.get(BillingInvoice, session.invoice_id)
    assert invoice is not None
    return session, invoice


@router.post("/mini/order")
@limiter.limit("60/minute")
async def mini_order(payload: MiniInput, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    _, invoice = await _mini_session(db, payload.ticket)
    order = await db.get(BillingOrder, invoice.order_id)
    assert order is not None
    return {"title": str(order.plan_snapshot.get("plan_name", "Erocraft")), "amount_fen": invoice.total_fen,
            "status": order.status, "paid": invoice.status == "paid", "due_at": to_iso_z(invoice.due_at),
            "server_time": to_iso_z(utc_naive_now())}


@router.post("/mini/pay")
@limiter.limit("15/minute")
async def mini_pay(payload: MiniPayInput, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    session, invoice = await _mini_session(db, payload.ticket)
    _payable(invoice)
    values = await _settings(db)
    if session.appid != values["WECHAT_PAY_MINIPROGRAM_APPID"]:
        raise HTTPException(409, "小程序配置已变更，请回网站重新发起付款")
    try:
        openid = await wechat_client.openid(session.appid, values["WECHAT_PAY_MINIPROGRAM_APP_SECRET"], payload.code, mini=True)
        result = await service.prepare_payment(db, invoice, "miniprogram", appid=session.appid, openid=openid)
        session.openid = openid
        await db.commit()
        return result
    except GatewayError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/mini/refresh")
@limiter.limit("20/minute")
async def mini_refresh(payload: MiniInput, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    _, invoice = await _mini_session(db, payload.ticket)
    try:
        await service.refresh_payment(db, invoice)
    except GatewayError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}
