"""WeChat Pay APIv3 direct merchant adapter, using the public-key mode.

Canonical messages follow wechatpay-apiv3/wechatpay-go core/auth and core/notify.
OAuth, payment sessions and order leases belong to the billing service.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote, urlencode

import httpx
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field, ValidationError

from app.services.billing.gateway.base import (
    CreateInvoiceRequest, CreateInvoiceResult, CreateRefundRequest, CreateRefundResult,
    GatewayBusinessError, GatewayPayloadError, GatewayRefundAbnormalError,
    GatewaySignatureError, GatewayTransientError, NotifyEvent, QueryRefundRequest, QueryResult,
)

_HOST = "https://api.mch.weixin.qq.com"


class _WechatBusinessFailure(GatewayBusinessError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"wechat_pay {code}: {message}")


class _Amount(BaseModel):
    total: int = Field(strict=True, gt=0)
    currency: Literal["CNY"]


class _PaidTransaction(BaseModel):
    appid: str = Field(min_length=1)
    mchid: str = Field(min_length=1)
    out_trade_no: str = Field(min_length=1, max_length=32)
    transaction_id: str = Field(min_length=1, max_length=32)
    trade_state: Literal["SUCCESS", "REFUND"]
    amount: _Amount


class _RefundAmount(_Amount):
    refund: int = Field(strict=True, gt=0)


class WechatPayGateway:
    code = "wechat_pay"
    display_name = "微信支付"
    logo_url: str | None = "/payment-logos/wechat-pay.svg"

    def __init__(
        self, *, mchid: str, appid: str, merchant_serial_no: str,
        merchant_private_key: str, api_v3_key: str, public_key_id: str,
        public_key: str, miniprogram_appid: str = "",
    ) -> None:
        private = serialization.load_pem_private_key(merchant_private_key.encode(), password=None)
        public = serialization.load_pem_public_key(public_key.encode())
        if not isinstance(private, rsa.RSAPrivateKey) or private.key_size != 2048:
            raise ValueError("微信商户私钥必须是2048位 RSA PEM")
        if not isinstance(public, rsa.RSAPublicKey) or public.key_size != 2048:
            raise ValueError("微信支付公钥必须是2048位 RSA PEM")
        if len(api_v3_key.encode()) != 32:
            raise ValueError("APIv3密钥必须为32字节")
        if not mchid or not appid or not merchant_serial_no or not public_key_id.startswith("PUB_KEY_ID_"):
            raise ValueError("请填写商户号、服务号AppID、商户证书序列号和微信支付公钥ID")
        self.mchid, self.appid, self.miniprogram_appid = mchid, appid, miniprogram_appid
        self._serial = merchant_serial_no
        self._private, self._public = private, public
        self._public_key_id = public_key_id
        self._aes = AESGCM(api_v3_key.encode())

    @classmethod
    def from_settings(cls, values: dict[str, Any]) -> WechatPayGateway:
        return cls(**{key: str(values.get(f"WECHAT_PAY_{key.upper()}") or "").strip() for key in (
            "mchid", "appid", "merchant_serial_no", "merchant_private_key", "api_v3_key",
            "public_key_id", "public_key", "miniprogram_appid",
        )})

    def _sign(self, message: bytes) -> str:
        return base64.b64encode(self._private.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode()

    def verify(self, headers: Mapping[str, str], body: bytes) -> None:
        headers = {k.lower(): v for k, v in headers.items()}
        try:
            timestamp = headers["wechatpay-timestamp"]
            nonce = headers["wechatpay-nonce"]
            if abs(time.time() - int(timestamp)) >= 300 or not nonce:
                raise ValueError("expired timestamp or empty nonce")
            if headers["wechatpay-serial"] != self._public_key_id:
                raise ValueError("unexpected public key ID")
            if headers.get("wechatpay-signature-type", "WECHATPAY2-SHA256-RSA2048") != "WECHATPAY2-SHA256-RSA2048":
                raise ValueError("unsupported signature type")
            signature = base64.b64decode(headers["wechatpay-signature"], validate=True)
            self._public.verify(signature, f"{timestamp}\n{nonce}\n".encode() + body + b"\n", padding.PKCS1v15(), hashes.SHA256())
        except (KeyError, ValueError, InvalidSignature) as exc:
            raise GatewaySignatureError("wechat_pay signature verification failed") from exc

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        signature = self._sign(f"{method}\n{path}\n{timestamp}\n{nonce}\n".encode() + body + b"\n")
        headers = {
            "Authorization": f'WECHATPAY2-SHA256-RSA2048 mchid="{self.mchid}",nonce_str="{nonce}",timestamp="{timestamp}",serial_no="{self._serial}",signature="{signature}"',
            "Accept": "application/json", "Content-Type": "application/json",
            "Wechatpay-Serial": self._public_key_id,
            "User-Agent": "Erocraft-Manager/WechatPay-v3",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            try:
                response = await client.request(method, _HOST + path, content=body, headers=headers)
            except httpx.TransportError as exc:
                raise GatewayTransientError("wechat_pay network request failed") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise GatewayTransientError(f"wechat_pay HTTP {response.status_code}")
        # Official SDK validates successful responses, including empty 204s.
        # Error responses need not carry Wechatpay-* signature headers.
        if 200 <= response.status_code < 300:
            self.verify(response.headers, response.content)
        try:
            result = response.json() if response.content else {}
            if not isinstance(result, dict):
                raise ValueError()
        except ValueError as exc:
            raise GatewayPayloadError("wechat_pay invalid JSON response") from exc
        if not 200 <= response.status_code < 300:
            raise _WechatBusinessFailure(str(result.get("code", response.status_code)), str(result.get("message", "request failed")))
        return result

    def invoice_payload(self, request: CreateInvoiceRequest) -> dict[str, Any]:
        if request.due_at is None:
            raise GatewayBusinessError("wechat_pay requires a payment deadline")
        appid = request.payment_appid or self.appid
        if appid not in {self.appid, self.miniprogram_appid}:
            raise GatewayBusinessError("wechat_pay unknown AppID")
        payload: dict[str, Any] = {
            "appid": appid, "mchid": self.mchid, "description": request.title[:127],
            "out_trade_no": request.invoice_no, "notify_url": request.notify_url,
            "time_expire": request.due_at.replace(tzinfo=timezone.utc).isoformat(timespec="seconds"),
            "amount": {"total": request.amount_fen, "currency": "CNY"},
        }
        if request.payer_openid:
            payload["payer"] = {"openid": request.payer_openid}
        return payload

    async def create_payment(self, payload: dict[str, Any]) -> CreateInvoiceResult:
        if payload["mchid"] != self.mchid:
            raise GatewayBusinessError("wechat_pay merchant changed for an existing order")
        method = "jsapi" if "payer" in payload else "native"
        result = await self._request("POST", f"/v3/pay/transactions/{method}", payload)
        field = "prepay_id" if method == "jsapi" else "code_url"
        if not isinstance(result.get(field), str) or not result[field]:
            raise GatewayPayloadError(f"wechat_pay missing {field}")
        return CreateInvoiceResult(
            gateway_order_id=result.get("prepay_id"), code_url=result.get("code_url"), pay_url=None,
            expires_at=datetime.fromisoformat(payload["time_expire"]).astimezone(timezone.utc).replace(tzinfo=None), raw=result,
        )

    async def create_invoice(self, request: CreateInvoiceRequest) -> CreateInvoiceResult:
        return await self.create_payment(self.invoice_payload(request))

    def payment_parameters(self, appid: str, prepay_id: str) -> dict[str, str]:
        timestamp, nonce, package = str(int(time.time())), secrets.token_hex(16), f"prepay_id={prepay_id}"
        return {"appId": appid, "timeStamp": timestamp, "nonceStr": nonce, "package": package,
                "signType": "RSA", "paySign": self._sign(f"{appid}\n{timestamp}\n{nonce}\n{package}\n".encode())}

    def _paid_transaction(self, data: dict[str, Any]) -> _PaidTransaction:
        try:
            paid = _PaidTransaction.model_validate(data)
        except ValidationError as exc:
            raise GatewayPayloadError("wechat_pay invalid paid transaction") from exc
        if paid.mchid != self.mchid or paid.appid not in {self.appid, self.miniprogram_appid}:
            raise GatewayPayloadError("wechat_pay merchant/AppID mismatch")
        return paid

    async def query_by_out_trade_no(self, out_trade_no: str) -> QueryResult:
        try:
            data = await self._request("GET", f"/v3/pay/transactions/out-trade-no/{quote(out_trade_no, safe='')}?{urlencode({'mchid': self.mchid})}")
        except _WechatBusinessFailure as exc:
            if exc.code == "ORDER_NOT_EXIST":
                return QueryResult("NOTFOUND", None, None)
            raise
        if data.get("out_trade_no") != out_trade_no or data.get("mchid") != self.mchid:
            raise GatewayPayloadError("wechat_pay query order mismatch")
        state = data.get("trade_state")
        if state in {"SUCCESS", "REFUND"}:
            paid = self._paid_transaction(data)
            return QueryResult("SUCCESS" if state == "SUCCESS" else "REFUNDED", paid.transaction_id, paid.amount.total, data)
        if state in {"CLOSED", "REVOKED", "PAYERROR"}:
            return QueryResult("CLOSED", None, None, data)
        if state in {"NOTPAY", "USERPAYING"}:
            return QueryResult("PROCESSING", None, None, data)
        raise GatewayPayloadError("wechat_pay unknown trade state")

    async def close_trade(self, out_trade_no: str) -> Literal["CLOSED", "NOTFOUND", "ALREADY_PAID"]:
        try:
            await self._request("POST", f"/v3/pay/transactions/out-trade-no/{quote(out_trade_no, safe='')}/close", {"mchid": self.mchid})
        except _WechatBusinessFailure as exc:
            if exc.code == "ORDER_NOT_EXIST":
                return "NOTFOUND"
            if exc.code == "ORDER_CLOSED":
                return "CLOSED"
            if exc.code == "ORDERPAID":
                return "ALREADY_PAID"
            if exc.code in {"TRADE_ERROR", "INVALID_REQUEST"}:
                state = await self.query_by_out_trade_no(out_trade_no)
                if state.status in {"SUCCESS", "REFUNDED"}:
                    return "ALREADY_PAID"
                if state.status in {"CLOSED", "NOTFOUND"}:
                    return state.status
            raise
        return "CLOSED"

    def parse_notify(self, raw_form: dict[str, Any], *, headers: Mapping[str, str] | None = None, body: bytes | None = None) -> NotifyEvent:
        if headers is None or body is None:
            raise GatewaySignatureError("wechat_pay requires raw body and headers")
        self.verify(headers, body)
        try:
            envelope = json.loads(body)
            resource = envelope["resource"]
            if envelope["event_type"] != "TRANSACTION.SUCCESS" or resource["algorithm"] != "AEAD_AES_256_GCM":
                raise ValueError()
            plaintext = self._aes.decrypt(resource["nonce"].encode(), base64.b64decode(resource["ciphertext"], validate=True), resource.get("associated_data", "").encode())
            data = json.loads(plaintext)
        except (KeyError, ValueError, TypeError, AttributeError, InvalidTag) as exc:
            raise GatewayPayloadError("wechat_pay invalid encrypted notification") from exc
        paid = self._paid_transaction(data)
        if paid.trade_state != "SUCCESS":
            raise GatewayPayloadError("wechat_pay notification is not a successful payment")
        return NotifyEvent(paid.out_trade_no, paid.transaction_id, paid.amount.total, "SUCCESS", data)

    @staticmethod
    def _verify_refund(data: dict[str, Any], refund_no: str, invoice_no: str | None, amount_fen: int | None) -> None:
        if data.get("out_refund_no") != refund_no or (invoice_no and data.get("out_trade_no") != invoice_no) or not data.get("refund_id"):
            raise GatewayPayloadError("wechat_pay refund identity mismatch")
        try:
            amount = _RefundAmount.model_validate(data.get("amount"))
        except ValidationError as exc:
            raise GatewayPayloadError("wechat_pay invalid refund amount") from exc
        if amount_fen is not None and (amount.refund != amount_fen or amount.total != amount_fen):
            raise GatewayPayloadError("wechat_pay full refund amount mismatch")

    @staticmethod
    def _refund_status(data: dict[str, Any]) -> Literal["SUCCEEDED", "PROCESSING", "FAILED"]:
        state = data.get("status")
        if state == "SUCCESS":
            return "SUCCEEDED"
        if state == "PROCESSING":
            return "PROCESSING"
        if state in {"ABNORMAL", "CLOSED"}:
            raise GatewayRefundAbnormalError(f"wechat_pay refund {state}; 请在商户平台处理异常退款")
        raise GatewayPayloadError("wechat_pay unknown refund state")

    async def create_refund(self, request: CreateRefundRequest) -> CreateRefundResult:
        data = await self._request("POST", "/v3/refund/domestic/refunds", {
            "out_trade_no": request.invoice.invoice_no, "out_refund_no": request.out_refund_no,
            "reason": request.reason[:80],
            "amount": {"refund": request.invoice.amount_fen, "total": request.invoice.amount_fen, "currency": "CNY"},
        })
        self._verify_refund(data, request.out_refund_no, request.invoice.invoice_no, request.invoice.amount_fen)
        return CreateRefundResult(data["refund_id"], self._refund_status(data), data)

    async def query_refund(self, request: QueryRefundRequest) -> Literal["SUCCEEDED", "PROCESSING", "FAILED", "NOTFOUND"]:
        try:
            data = await self._request("GET", f"/v3/refund/domestic/refunds/{quote(request.out_refund_no, safe='')}")
        except _WechatBusinessFailure as exc:
            if exc.code == "RESOURCE_NOT_EXISTS":
                return "NOTFOUND"
            raise
        self._verify_refund(data, request.out_refund_no, request.invoice_no, request.amount_fen)
        return self._refund_status(data)
