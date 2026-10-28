"""公开通知入口验签后，按网关的当前收退款事实处理。"""

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.settings_store import get_settings_store
from app.db.models.billing import BillingInvoice
from app.services.billing import payments
from app.services.billing.gateway_client import GatewayClient

router = APIRouter(tags=["billing-webhook"])


@router.post("/webhook/payment-gateway", status_code=204)
async def gateway_notify(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    client = await GatewayClient.load(db)
    raw = await request.body()
    path = request.url.path + ("?" + request.url.query if request.url.query else "")
    if not client.verify(request.headers, request.method, path, raw):
        raise HTTPException(401, "支付通知签名无效")
    await payments.receive_event(db, json.loads(raw), client)


@router.post("/webhook/alipay_direct", response_class=PlainTextResponse)
async def legacy_alipay_notify(request: Request, db: AsyncSession = Depends(get_db)) -> str:
    # 生产切换后仍可能重投旧通知；只读取旧账，不创建网关付款。
    config = await get_settings_store().get_many(db, {"LEGACY_ALIPAY_APPID": "", "LEGACY_ALIPAY_PUBLIC_KEY": ""})
    pem = config["LEGACY_ALIPAY_PUBLIC_KEY"]
    if "BEGIN" not in pem:
        pem = f"-----BEGIN PUBLIC KEY-----\n{pem}\n-----END PUBLIC KEY-----\n"
    public = cast(rsa.RSAPublicKey, serialization.load_pem_public_key(pem.encode()))
    form = {key: str(value) for key, value in (await request.form()).items()}
    canonical = "&".join(f"{key}={form[key]}" for key in sorted(form) if key not in ("sign", "sign_type") and form[key] != "")
    try:
        public.verify(base64.b64decode(form["sign"], validate=True), canonical.encode(), padding.PKCS1v15(), hashes.SHA256())
        if form["app_id"] != config["LEGACY_ALIPAY_APPID"]:
            raise ValueError("通知不属于本应用")
    except (KeyError, ValueError, InvalidSignature) as exc:
        raise HTTPException(401, "支付宝通知签名或应用身份无效") from exc
    invoice = await db.scalar(select(BillingInvoice).where(BillingInvoice.invoice_no == form["out_trade_no"]))
    if invoice is None:
        raise HTTPException(404, "旧账单不存在")
    if form["trade_status"] in ("TRADE_SUCCESS", "TRADE_FINISHED") and not form.get("refund_fee"):
        paid_at = form.get("gmt_payment")
        await payments.record_legacy_payment(db, invoice, transaction_id=form["trade_no"],
                                             amount_fen=int(Decimal(form["total_amount"]) * 100),
                                             paid_at=(datetime.strptime(paid_at, "%Y-%m-%d %H:%M:%S")
                                                      .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                                                      .astimezone(timezone.utc).replace(tzinfo=None)) if paid_at else None)
    return "success"
