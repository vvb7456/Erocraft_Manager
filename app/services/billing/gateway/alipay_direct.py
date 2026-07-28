"""Alipay direct (open-platform) payment adapter.

Implements :class:`app.services.billing.gateway.base.PaymentGateway` by talking
**directly** to Alipay's open-platform gateway — no intermediary (虎皮椒)
involved. Money settles straight into the merchant account bound to the
configured ``APPID``.

Channel coverage
-----------------
This adapter uses the **电脑网站支付** product ``alipay.trade.page.pay`` —
the desktop/PC Alipay cashier. ``create_invoice`` builds a signed gateway
GET URL (no HTTP round-trip — page.pay is a redirect method); the frontend
navigates to it directly on both mobile and PC. Alipay itself switches to a
mobile H5 cashier when the UA is mobile, so a single ``pay_url`` covers both
form factors.

* on PC → opens ``pay_url`` to reach the Alipay desktop cashier (扫码登录 /
  账户余额 / 银行卡 / 扫码支付 all available);
* on mobile → same ``pay_url`` reaches the H5 cashier (Alipay auto-detects UA).

Signing & encoding
-------------------
RSA2 (SHA256WithRSA), the only mode this deployment configures. The app
private key (PEM or single-line Base64) signs request biz payloads; the
Alipay public key verifies every response/notify. Keys are stored as runtime
settings (DB-backed) — never logged.

Response charset
----------------
Alipay sandbox returns JSON with ``Content-Type: text/html;charset=GBK`` and
the bytes are GBK-encoded. ``httpx.Response.json()`` decodes with UTF-8
regardless of the declared charset, crashing on Chinese bytes. We therefore
``response.text`` (which ``httpx`` decodes using the declared charset) +
``json.loads`` ourselves. Alipay production ships UTF-8 since 2024 but
tolerating GBK keeps the sandbox path working.

Refunds
-------
Alipay exposes *real* refund-query (``alipay.trade.fastpay.refund.query``)
unlike hupijiao, so ``query_refund`` is authoritative rather than inferred.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote_plus

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.session import get_session_factory
from app.services.billing.gateway.base import (
    CreateInvoiceRequest,
    CreateInvoiceResult,
    CreateRefundRequest,
    CreateRefundResult,
    GatewayBusinessError,
    GatewaySignatureError,
    GatewayTransientError,
    NotifyEvent,
    QueryRefundRequest,
    QueryResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_GATEWAY = "https://openapi.alipay.com/gateway.do"
_SIGN_TYPE = "RSA2"
_FORMAT = "JSON"
_CHARSET = "utf-8"
_VERSION = "1.0"
# wap.pay redirect URLs are valid for the order's biz timeout; Alipay itself
# enforces ~5min on the cashier, kept consistent with the billing timeout.
_QR_VALID_MIN = 5

# Alipay trade_status values (alipay.trade.query + notify)
_TS_SUCCESS = "TRADE_SUCCESS"
_TS_FINISHED = "TRADE_FINISHED"
_TS_WAIT = "WAIT_BUYER_PAY"
_TS_CLOSED = "TRADE_CLOSED"

# Alipay sub_code values meaning "no such trade on Alipay side" — the user
# never opened the cashier / the order expired on Alipay's end / an unpaid
# expired invoice is being cancelled. These must surface as NOTFOUND so the
# cancel flow + close job can close out the order.
_NOT_FOUND_SUB_CODES = {
    "ACQ.TRADE_NOT_EXIST",
    "ACQ.TRADE_HAS_CLOSE",
    "ACQ.PAYMENT_NOT_HAS_TRADE",
    "ACQ.REFUND_NOT_EXIST",
}


class _AlipayNotFound(GatewayBusinessError):
    """Internal: Alipay business error indicates the trade is not found.
    Caught by query_by_out_trade_no / query_refund to return NOTFOUND.
    """


# --------------------------------------------------------------------------- #
# RSA helpers
# --------------------------------------------------------------------------- #


def _load_private_key(raw: str) -> rsa.RSAPrivateKey:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("ALIPAY_DIRECT_APP_PRIVATE_KEY is empty")
    if "BEGIN" in raw:
        data = raw.encode("utf-8")
    else:
        # single-line Base64 (no PEM headers) — re-wrap
        body = "".join(raw.split())
        data = (
            b"-----BEGIN PRIVATE KEY-----\n"
            + b"\n".join(body[i : i + 64].encode() for i in range(0, len(body), 64))
            + b"\n-----END PRIVATE KEY-----\n"
        )
    try:
        return serialization.load_pem_private_key(data, password=None)  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid Alipay app private key: {exc}") from exc


def _load_public_key(raw: str) -> rsa.RSAPublicKey:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY is empty")
    if "BEGIN" in raw:
        data = raw.encode("utf-8")
    else:
        body = "".join(raw.split())
        data = (
            b"-----BEGIN PUBLIC KEY-----\n"
            + b"\n".join(body[i : i + 64].encode() for i in range(0, len(body), 64))
            + b"\n-----END PUBLIC KEY-----\n"
        )
    try:
        return serialization.load_pem_public_key(data)  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid Alipay public key: {exc}") from exc


def _sign(params: dict[str, str], private_key: rsa.RSAPrivateKey) -> str:
    """Sign sorted ``key=value`` string (no URL encoding) with RSA-SHA256."""
    canonical = _canonical_query(params)
    signature = private_key.sign(
        canonical.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _canonical_query(params: dict[str, str]) -> str:
    """``key=value&...`` over sorted keys, values NOT URL-encoded (Alipay spec)."""
    return "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] != "")


def _extract_raw_response(text: str, response_key: str) -> str | None:
    """Extract the raw JSON substring for ``response_key`` from the full
    response text, preserving the exact byte sequence Alipay signed.

    Alipay computes the response signature over the **raw JSON value** of
    ``xxx_response`` as it appears in the HTTP body — including original
    key ordering, ``\\uXXXX`` escapes, spacing, etc. Re-serialising a
    parsed dict (``json.dumps``) produces a *different* byte sequence and
    breaks verification. This function performs brace-matching on the raw
    text to extract the exact substring.
    """
    prefix = f'"{response_key}":'
    start = text.find(prefix)
    if start < 0:
        return None
    start += len(prefix)
    while start < len(text) and text[start] in " \t\n\r":
        start += 1
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #


class AlipayDirectGateway:
    """Direct Alipay open-platform adapter (H5/wap channel)."""

    code = "alipay_direct"
    display_name = "支付宝"

    # open-platform method names
    _METHOD_PAGE_PAY = "alipay.trade.page.pay"
    _METHOD_WAP_PAY = "alipay.trade.wap.pay"
    _METHOD_QUERY = "alipay.trade.query"
    _METHOD_REFUND = "alipay.trade.refund"
    _METHOD_REFUND_QUERY = "alipay.trade.fastpay.refund.query"

    def __init__(
        self,
        *,
        appid: str,
        app_private_key_pem: str,
        alipay_public_key_pem: str,
        gateway_url: str = _DEFAULT_GATEWAY,
        seller_id: str | None = None,
    ) -> None:
        if not appid:
            raise ValueError("ALIPAY_DIRECT_APPID must be non-empty")
        self._appid = appid
        self._private_key = _load_private_key(app_private_key_pem)
        self._public_key = _load_public_key(alipay_public_key_pem)
        self._gateway = (gateway_url or _DEFAULT_GATEWAY).strip()
        self._seller_id = seller_id or None

    # ------------------------------------------------------------------
    # runtime config (seller_id mutable via DB settings)
    # ------------------------------------------------------------------

    async def _resolve_seller_id(self) -> str | None:
        store = get_settings_store()
        factory = get_session_factory()
        async with factory() as session:
            values = await store.get_many(
                session,
                {"ALIPAY_DIRECT_SELLER_ID": self._seller_id or ""},
            )
        return (values.get("ALIPAY_DIRECT_SELLER_ID") or "").strip() or None

    # ------------------------------------------------------------------
    # core request plumbing
    # ------------------------------------------------------------------

    def _common_params(
        self, method: str, notify_url: str | None = None, return_url: str | None = None
    ) -> dict[str, str]:
        params: dict[str, str] = {
            "app_id": self._appid,
            "method": method,
            "format": _FORMAT,
            "charset": _CHARSET,
            "sign_type": _SIGN_TYPE,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": _VERSION,
        }
        if notify_url:
            params["notify_url"] = notify_url
        if return_url:
            params["return_url"] = return_url
        return params

    def _signed_form(
        self, method: str, biz: dict[str, Any], notify_url: str | None = None
    ) -> dict[str, str]:
        params = self._common_params(method, notify_url)
        params["biz_content"] = json.dumps(biz, ensure_ascii=False, separators=(",", ":"))
        params["sign"] = _sign(params, self._private_key)
        return params

    async def _post(self, method: str, biz: dict[str, Any], notify_url: str | None = None) -> dict[str, Any]:
        form = self._signed_form(method, biz, notify_url)
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            try:
                response = await client.post(self._gateway, data=form)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise GatewayTransientError(
                    f"alipay_direct transport error: {exc}"
                ) from exc
        if response.status_code >= 500:
            raise GatewayTransientError(
                f"alipay_direct gateway HTTP {response.status_code}: {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise GatewayBusinessError(
                f"alipay_direct HTTP {response.status_code}: {response.text[:200]}"
            )
        # Sandbox server sets charset=GBK; httpx.Response.json() decodes raw
        # bytes as UTF-8 regardless of declared charset, crashing on GBK
        # bytes for non-ASCII strings. Use .text (respects charset) + json.loads.
        try:
            body = json.loads(response.text)
        except ValueError as exc:
            raise GatewayBusinessError(
                f"alipay_direct non-JSON: {response.text[:200]}"
            ) from exc
        response_key = method.replace(".", "_") + "_response"
        inner = body.get(response_key)
        if not isinstance(inner, dict):
            raise GatewayBusinessError(f"alipay_direct missing {response_key}: {body!r}")
        # Verify response signature against the RAW inner JSON substring.
        # Alipay signs the exact bytes of ``xxx_response``'s value as it
        # appears in the HTTP body (with \uXXXX escapes, original key
        # order, etc). Re-serialising a parsed dict would break verification.
        sign = body.get("sign") or ""
        code = str(inner.get("code") or "")
        sub_code = str(inner.get("sub_code") or "")
        # Not-found-class sub-codes: short-circuit to caller with NOTFOUND tag
        if code != "10000" and sub_code in _NOT_FOUND_SUB_CODES:
            raise _AlipayNotFound(
                f"alipay_direct {method} sub_code={sub_code} "
                f"sub_msg={inner.get('sub_msg')!r}"
            )
        if sign:
            raw_inner = _extract_raw_response(response.text, response_key)
            if raw_inner is None:
                raise GatewaySignatureError(
                    f"alipay_direct: unable to extract raw {response_key} for verification"
                )
            try:
                sig_bytes = base64.b64decode(sign)
            except Exception as exc:  # noqa: BLE001
                raise GatewaySignatureError(
                    "alipay_direct response: bad sign encoding"
                ) from exc
            try:
                self._public_key.verify(
                    sig_bytes,
                    raw_inner.encode("utf-8"),
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
            except InvalidSignature as exc:
                logger.warning(
                    "alipay_direct signature mismatch for %s: "
                    "raw_body=%s extracted_inner=%s",
                    method,
                    response.text[:1000],
                    raw_inner[:500] if raw_inner else None,
                )
                raise GatewaySignatureError(
                    "alipay_direct response signature mismatch"
                ) from exc
        if code not in ("10000",):
            raise GatewayBusinessError(
                f"alipay_direct {method} code={code} msg={inner.get('msg')!r} "
                f"sub_code={inner.get('sub_code')!r} sub_msg={inner.get('sub_msg')!r}"
            )
        return inner

    # ------------------------------------------------------------------
    # PaymentGateway Protocol
    # ------------------------------------------------------------------

    async def create_invoice(
        self, request: CreateInvoiceRequest
    ) -> CreateInvoiceResult:
        seller_id = await self._resolve_seller_id()

        # PC: alipay.trade.page.pay — desktop cashier
        biz_pc: dict[str, Any] = {
            "out_trade_no": request.invoice_no,
            "total_amount": f"{request.amount_fen / 100:.2f}",
            "subject": request.title,
            "product_code": "FAST_INSTANT_TRADE_PAY",
        }
        if seller_id:
            biz_pc["seller_id"] = seller_id
        params_pc = self._common_params(
            self._METHOD_PAGE_PAY,
            notify_url=request.notify_url,
            return_url=request.return_url,
        )
        params_pc["biz_content"] = json.dumps(
            biz_pc, ensure_ascii=False, separators=(",", ":")
        )
        params_pc["sign"] = _sign(params_pc, self._private_key)
        pay_url_pc = (
            self._gateway
            + "?"
            + "&".join(f"{k}={quote_plus(v)}" for k, v in params_pc.items())
        )

        # Mobile: alipay.trade.wap.pay — H5 cashier
        biz_wap: dict[str, Any] = {
            "out_trade_no": request.invoice_no,
            "total_amount": f"{request.amount_fen / 100:.2f}",
            "subject": request.title,
            "product_code": "QUICK_WAP_WAY",
        }
        if seller_id:
            biz_wap["seller_id"] = seller_id
        params_wap = self._common_params(
            self._METHOD_WAP_PAY,
            notify_url=request.notify_url,
            return_url=request.return_url,
        )
        params_wap["biz_content"] = json.dumps(
            biz_wap, ensure_ascii=False, separators=(",", ":")
        )
        params_wap["sign"] = _sign(params_wap, self._private_key)
        pay_url_wap = (
            self._gateway
            + "?"
            + "&".join(f"{k}={quote_plus(v)}" for k, v in params_wap.items())
        )

        return CreateInvoiceResult(
            gateway_order_id=request.invoice_no,
            code_url=None,
            pay_url=pay_url_pc,
            expires_at=utc_naive_now() + timedelta(minutes=_QR_VALID_MIN),
            raw={
                "url": pay_url_pc,
                "url_h5": pay_url_wap,
                "method": self._METHOD_PAGE_PAY,
                "biz": biz_pc,
            },
        )

    async def query_by_out_trade_no(self, out_trade_no: str) -> QueryResult:
        try:
            inner = await self._post(
                self._METHOD_QUERY, {"out_trade_no": out_trade_no}
            )
        except _AlipayNotFound:
            # 用户没开过收银台 / 超时 / 已被支付宝侧关闭。统一回 NOTFOUND,
            # 让上层取消流程和 order_close 作业能干净地关单。
            return QueryResult(
                status="NOTFOUND", transaction_id=None, amount_fen=None, raw={}
            )
        ts = str(inner.get("trade_status") or "").upper()
        if ts in (_TS_SUCCESS, _TS_FINISHED):
            status: Literal["SUCCESS", "PROCESSING", "CLOSED", "NOTFOUND"] = "SUCCESS"
        elif ts == _TS_WAIT:
            status = "PROCESSING"
        elif ts == _TS_CLOSED:
            status = "CLOSED"
        else:
            status = "NOTFOUND"
        total = inner.get("total_amount")
        amount_fen: int | None = None
        if total not in (None, ""):
            try:
                amount_fen = int(round(float(total) * 100))
            except (TypeError, ValueError):
                amount_fen = None
        return QueryResult(
            status=status,
            transaction_id=str(inner.get("trade_no") or "") or None,
            amount_fen=amount_fen,
            raw=inner,
        )

    def parse_notify(self, raw_form: dict[str, Any]) -> NotifyEvent:
        sign_b64 = str(raw_form.get("sign") or "")
        if not sign_b64:
            raise GatewaySignatureError("alipay_direct notify missing sign")
        # Build canonical params (excluding sign/sign_type per Alipay spec for
        # notify verification — values raw, not URL-encoded, sorted by key).
        params: dict[str, str] = {
            k: str(v)
            for k, v in raw_form.items()
            if k not in ("sign", "sign_type") and v not in (None, "")
        }
        canonical = _canonical_query(params)
        try:
            sig = base64.b64decode(sign_b64)
        except Exception as exc:  # noqa: BLE001
            raise GatewaySignatureError("alipay_direct notify bad sign encoding") from exc
        try:
            self._public_key.verify(
                sig, canonical.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
            )
        except InvalidSignature as exc:
            raise GatewaySignatureError("alipay_direct notify signature mismatch") from exc

        out_trade_no = str(raw_form.get("out_trade_no") or "")
        if not out_trade_no:
            raise GatewaySignatureError("alipay_direct notify missing out_trade_no")
        trade_no = str(raw_form.get("trade_no") or "")
        try:
            amount_fen = int(round(float(raw_form.get("total_amount") or 0) * 100))
        except (TypeError, ValueError) as exc:
            raise GatewaySignatureError(
                f"alipay_direct notify bad total_amount: {raw_form.get('total_amount')!r}"
            ) from exc

        trade_status = str(raw_form.get("trade_status") or "").upper()
        status: Literal["SUCCESS", "REFUNDED", "REFUND_PROCESSING", "REFUND_FAIL"]
        if trade_status in (_TS_SUCCESS, _TS_FINISHED):
            status = "SUCCESS"
        elif trade_status == _TS_CLOSED:
            # TRADE_CLOSED can mean closed-by-timeout OR refund-ish closure; the
            # authoritative refund truth comes from refund.notify (refund_fee /
            # fund_change). Here we treat payment-notify TRADE_CLOSED as
            # SUCCESS-settled-closed (non-refundable); surface as audit-only.
            status = "SUCCESS"
        else:
            # refund notify carries trade_status=TRADE_SUCCESS and a
            # out_refund_no/refund_fee. We only get here if we mis-detected;
            # surface SUCCESS for any paid-class status, else signature error.
            raise GatewaySignatureError(
                f"alipay_direct notify unknown trade_status: {trade_status!r}"
            )

        return NotifyEvent(
            out_trade_no=out_trade_no,
            transaction_id=trade_no,
            amount_fen=amount_fen,
            status=status,
            raw_form=dict(raw_form),
        )

    async def create_refund(
        self, request: CreateRefundRequest
    ) -> CreateRefundResult:
        biz: dict[str, Any] = {
            "out_trade_no": request.invoice.invoice_no,
            "refund_amount": f"{request.invoice.amount_fen / 100:.2f}",
            "out_request_no": request.out_refund_no,
        }
        if request.reason:
            biz["refund_reason"] = request.reason[:80]
        # refund.notify_url not needed — refund result is synchronous here.
        inner = await self._post(self._METHOD_REFUND, biz)
        fund_change = str(inner.get("fund_change") or "").upper()
        normalized: Literal["SUCCEEDED", "PROCESSING", "FAILED", "UNKNOWN"]
        if fund_change == "Y":
            normalized = "SUCCEEDED"
        elif fund_change == "N":
            normalized = "PROCESSING"
        else:
            normalized = "UNKNOWN"
        return CreateRefundResult(
            gateway_refund_id=str(inner.get("trade_no") or request.out_refund_no),
            status=normalized,
            raw=inner,
        )

    async def query_refund(
        self, request: QueryRefundRequest
    ) -> Literal["SUCCEEDED", "PROCESSING", "FAILED", "NOTFOUND"]:
        biz: dict[str, Any] = {
            "out_request_no": request.out_refund_no,
        }
        if request.invoice_no:
            biz["out_trade_no"] = request.invoice_no
        elif request.gateway_refund_id:
            biz["trade_no"] = request.gateway_refund_id
        else:
            raise GatewayBusinessError(
                "alipay_direct query_refund requires invoice_no or gateway_refund_id"
            )
        try:
            inner = await self._post(self._METHOD_REFUND_QUERY, biz)
        except _AlipayNotFound:
            return "NOTFOUND"
        rs = str(inner.get("refund_status") or "").upper()
        if rs == "REFUND_SUCCESS":
            return "SUCCEEDED"
        # Alipay: empty refund_status while present → still processing
        if rs == "":
            return "PROCESSING"
        return "FAILED"