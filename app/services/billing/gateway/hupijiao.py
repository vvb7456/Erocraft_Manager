"""Hupijiao (虎皮椒) Alipay-channel payment adapter.

Implements :class:`app.services.billing.gateway.base.PaymentGateway`.

Behavior is modelled directly on the official Hupijiao v3 Python SDK
(see ``hupijiao-v3-python.py``). Key differences vs. the SDK:

* uses ``httpx`` (async) instead of ``requests``
* no ``qrcode`` dependency — the front-end renders QR codes itself
* ``payment`` field is **hard-coded** to ``"alipay"`` since this deployment
  only signed Hupijiao's Alipay ISV channel
* iterates an endpoint pool (``HUPIJIAO_GATEWAY_ENDPOINTS``) with primary +
  fallback domains; transient failures (timeout / 5xx / DNS) trigger the next
  endpoint, business 4xx errors stop immediately
* ``Referer`` HTTP header is mandatory (Hupijiao server-side checks it)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import timedelta
from typing import Any, Literal
from urllib.parse import unquote_plus, urlencode

import httpx

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


# Hupijiao gateway-side status codes (per official docs)
# Pay/query status (see /doc/api/search.html): OD=paid, WP=waiting, CD=closed
#   NOTE: query.html uses CD for "closed/cancelled". The webhook (pay.html) and
#   refund.html reuse the same letter set with DIFFERENT meanings:
# Webhook + refund_status (see /doc/api/pay.html, /doc/api/refund.html):
#   OD=paid, CD=refunded, RD=refunding, UD=refund-failed
# Therefore the same letter "CD" means different things depending on the API.
_HPJ_STATUS_PAID = "OD"
_HPJ_STATUS_WAITING = "WP"
_HPJ_QUERY_STATUS_CLOSED = "CD"  # query.html only
_HPJ_REFUND_STATUS_REFUNDED = "CD"  # webhook / refund.html only
_HPJ_REFUND_STATUS_PROCESSING = "RD"
_HPJ_REFUND_STATUS_FAILED = "UD"


def _ksort_pairs(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Sort by key, drop ``hash`` and empty values, stringify values.

    Mirrors the official SDK's ``ksort`` helper.
    """
    return sorted(
        (k, str(v))
        for k, v in payload.items()
        if k != "hash" and v is not None and v != ""
    )


def sign(payload: dict[str, Any], app_secret: str) -> str:
    """MD5 signature, identical to Hupijiao official SDK.

    Equivalent to ``md5(unquote_plus(urlencode(ksort(p))) + app_secret)``.
    Returns 32-char lowercase hex.
    """
    items = _ksort_pairs(payload)
    string_a = unquote_plus(urlencode(items))
    return hashlib.md5((string_a + app_secret).encode("utf-8")).hexdigest()


def verify(payload: dict[str, Any], app_secret: str) -> bool:
    given = payload.get("hash") or ""
    if not given:
        return False
    return given.lower() == sign(payload, app_secret)


class HupijiaoGateway:
    """Hupijiao adapter (Alipay channel only)."""

    code = "hupijiao"
    display_name = "虎皮椒-支付宝"

    # Hupijiao API paths (relative to endpoint root)
    _PATH_PAY = "/payment/do.html"
    _PATH_QUERY = "/payment/query.html"
    _PATH_REFUND = "/payment/refund.html"
    # Note: hupijiao has NO refund-query endpoint. Refund completion is
    # observed via webhook re-fire (status=CD) or order-query (status=CD).

    def __init__(self, *, appid: str, app_secret: str) -> None:
        if not appid or not app_secret:
            raise ValueError("HUPIJIAO_APPID / HUPIJIAO_APPSECRET must be non-empty")
        self._appid = appid
        self._app_secret = app_secret

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _DEFAULT_ENDPOINTS = "https://api.xunhupay.com,https://api.dpweixin.com"
    _DEFAULT_REFERER = "https://app.erocraft.com/"

    async def _load_runtime_config(self) -> tuple[list[str], str]:
        """Read endpoint pool + Referer from settings store (DB-backed, cached).

        Falls back to compiled-in defaults when DB has no row yet (which is the
        case before Step 4 wires :data:`BILLING_SPECS` into ``runtime_settings``).
        """
        store = get_settings_store()
        session_factory = get_session_factory()
        async with session_factory() as session:
            values = await store.get_many(
                session,
                {
                    "HUPIJIAO_GATEWAY_ENDPOINTS": self._DEFAULT_ENDPOINTS,
                    "HUPIJIAO_REFERER": self._DEFAULT_REFERER,
                },
            )
        raw_endpoints = str(values.get("HUPIJIAO_GATEWAY_ENDPOINTS") or "")
        endpoints = [e.strip().rstrip("/") for e in raw_endpoints.split(",") if e.strip()]
        if not endpoints:
            raise GatewayBusinessError("HUPIJIAO_GATEWAY_ENDPOINTS is empty")
        referer = str(values.get("HUPIJIAO_REFERER") or "").strip()
        if not referer:
            raise GatewayBusinessError("HUPIJIAO_REFERER is not configured")
        return endpoints, referer

    def _build_payload(self, base: dict[str, Any]) -> dict[str, Any]:
        """Add common fields + signature."""
        payload = dict(base)
        payload.setdefault("appid", self._appid)
        payload.setdefault("time", str(int(time.time())))
        payload.setdefault("nonce_str", secrets.token_hex(16))
        payload["hash"] = sign(payload, self._app_secret)
        return payload

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the gateway with endpoint-pool fallback.

        - 5xx / timeout / connect error -> try next endpoint
        - 4xx -> ``GatewayBusinessError`` (no retry, same on every endpoint)
        - response with non-zero ``errcode`` -> ``GatewayBusinessError``
        - all endpoints exhausted -> ``GatewayTransientError``
        """
        endpoints, referer = await self._load_runtime_config()
        headers = {"Referer": referer}
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0)
        ) as client:
            for endpoint in endpoints:
                url = f"{endpoint}{path}"
                try:
                    response = await client.post(url, data=payload, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    logger.warning(
                        "hupijiao endpoint failed (transport): %s -> %s",
                        endpoint,
                        exc,
                    )
                    last_error = exc
                    continue
                if 500 <= response.status_code < 600:
                    logger.warning(
                        "hupijiao endpoint returned %s: %s",
                        response.status_code,
                        endpoint,
                    )
                    last_error = GatewayTransientError(
                        f"{endpoint} returned HTTP {response.status_code}"
                    )
                    continue
                if response.status_code >= 400:
                    raise GatewayBusinessError(
                        f"hupijiao HTTP {response.status_code}: {response.text[:200]}"
                    )
                try:
                    body = response.json()
                except ValueError as exc:
                    raise GatewayBusinessError(
                        f"hupijiao returned non-JSON: {response.text[:200]}"
                    ) from exc
                # Hupijiao response convention: errcode==0 means success
                errcode = body.get("errcode")
                if errcode not in (0, "0", None):
                    raise GatewayBusinessError(
                        f"hupijiao errcode={errcode} errmsg={body.get('errmsg')!r}"
                    )
                return body
        raise GatewayTransientError(
            f"all hupijiao endpoints failed; last_error={last_error!r}"
        )

    # ------------------------------------------------------------------
    # PaymentGateway Protocol
    # ------------------------------------------------------------------

    async def create_invoice(
        self, request: CreateInvoiceRequest
    ) -> CreateInvoiceResult:
        # Hupijiao expects yuan as decimal string with 2 places
        total_fee = f"{request.amount_fen / 100:.2f}"
        payload = self._build_payload(
            {
                "version": "1.1",
                "lang": "zh-cn",
                "plugins": "erocraft-manager",
                "trade_order_id": request.invoice_no,
                "payment": "alipay",  # hard-coded: Alipay channel only
                "is_app": "Y",  # let Hupijiao auto-detect mobile vs PC by UA
                "total_fee": total_fee,
                "title": request.title[:60] or request.invoice_no,
                "description": request.title[:120] or "-",
                "notify_url": request.notify_url,
                "return_url": request.return_url,
                "callback_url": request.return_url,  # H5 failure fallback
            }
        )
        body = await self._post(self._PATH_PAY, payload)
        # Hupijiao Alipay channel returns the gateway order id as ``openid``.
        gateway_order_id = str(body.get("openid") or "")
        if not gateway_order_id:
            raise GatewayBusinessError(
                f"hupijiao create_invoice missing openid: {body!r}"
            )
        # QR code is valid for 5 minutes per Hupijiao docs
        expires_at = utc_naive_now() + timedelta(minutes=5)
        return CreateInvoiceResult(
            gateway_order_id=gateway_order_id,
            code_url=body.get("url_qrcode") or None,
            pay_url=body.get("url") or None,
            expires_at=expires_at,
            raw=body,
        )

    async def query_by_out_trade_no(self, out_trade_no: str) -> QueryResult:
        payload = self._build_payload(
            {
                "appid": self._appid,
                "out_trade_order": out_trade_no,
            }
        )
        try:
            body = await self._post(self._PATH_QUERY, payload)
        except GatewayBusinessError as exc:
            # Hupijiao returns errcode for "order not found" — surface as NOTFOUND
            if "not" in str(exc).lower() and "found" in str(exc).lower():
                return QueryResult(
                    status="NOTFOUND", transaction_id=None, amount_fen=None, raw={}
                )
            raise
        # Per docs, payload sits inside body["data"]; tolerate both shapes.
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        hpj_status = str(data.get("status") or "").upper()
        normalized: Literal["SUCCESS", "PROCESSING", "CLOSED", "NOTFOUND"]
        if hpj_status == _HPJ_STATUS_PAID:
            normalized = "SUCCESS"
        elif hpj_status == _HPJ_STATUS_WAITING:
            normalized = "PROCESSING"
        elif hpj_status == _HPJ_QUERY_STATUS_CLOSED:
            normalized = "CLOSED"
        else:
            normalized = "NOTFOUND"
        amount_fen: int | None = None
        total_fee = data.get("total_fee")
        if total_fee not in (None, ""):
            try:
                amount_fen = int(round(float(total_fee) * 100))
            except (TypeError, ValueError):
                amount_fen = None
        transaction_id_raw = data.get("transaction_id")
        return QueryResult(
            status=normalized,
            transaction_id=str(transaction_id_raw) if transaction_id_raw else None,
            amount_fen=amount_fen,
            raw=body,
        )

    def parse_notify(self, raw_form: dict[str, Any]) -> NotifyEvent:
        if not verify(raw_form, self._app_secret):
            raise GatewaySignatureError("hupijiao webhook signature mismatch")
        out_trade_no = str(raw_form.get("trade_order_id") or "")
        if not out_trade_no:
            raise GatewaySignatureError("hupijiao webhook missing trade_order_id")
        transaction_id = str(raw_form.get("transaction_id") or "")
        try:
            amount_fen = int(round(float(raw_form.get("total_fee") or 0) * 100))
        except (TypeError, ValueError) as exc:
            raise GatewaySignatureError(
                f"hupijiao webhook bad total_fee: {raw_form.get('total_fee')!r}"
            ) from exc
        hpj_status = str(raw_form.get("status") or "").upper()
        status: Literal["SUCCESS", "REFUNDED", "REFUND_PROCESSING", "REFUND_FAIL"]
        if hpj_status == _HPJ_STATUS_PAID:
            status = "SUCCESS"
        elif hpj_status == _HPJ_REFUND_STATUS_REFUNDED:
            status = "REFUNDED"
        elif hpj_status == _HPJ_REFUND_STATUS_PROCESSING:
            status = "REFUND_PROCESSING"
        elif hpj_status == _HPJ_REFUND_STATUS_FAILED:
            status = "REFUND_FAIL"
        else:
            raise GatewaySignatureError(
                f"hupijiao webhook unknown status: {hpj_status!r}"
            )
        return NotifyEvent(
            out_trade_no=out_trade_no,
            transaction_id=transaction_id,
            amount_fen=amount_fen,
            status=status,
            raw_form=dict(raw_form),
        )

    async def create_refund(
        self, request: CreateRefundRequest
    ) -> CreateRefundResult:
        # Hupijiao refund identifies the original payment by either
        # ``trade_order_id`` (our invoice_no) or ``open_order_id`` (their
        # gateway_prepay_id). Per docs (refund.html) the refund body has NO
        # amount and NO refund-number field.
        params: dict[str, str] = {"appid": self._appid}
        if request.invoice.gateway_prepay_id:
            params["open_order_id"] = request.invoice.gateway_prepay_id
        elif request.invoice.invoice_no:
            params["trade_order_id"] = request.invoice.invoice_no
        else:
            raise GatewayBusinessError(
                "hupijiao refund requires invoice_no or gateway_prepay_id"
            )
        if request.reason:
            params["reason"] = request.reason[:80]
        payload = self._build_payload(params)
        body = await self._post(self._PATH_REFUND, payload)
        gateway_refund_id = str(
            body.get("out_refund_no") or request.out_refund_no
        )
        # Per refund.html the synchronous response includes ``refund_status``
        # already reflecting the refund's settled state most of the time
        # (commonly ``CD`` for Alipay personal channel which refunds
        # instantly). Surface it so the caller can finalize without waiting
        # for the webhook.
        hpj_status = str(body.get("refund_status") or "").upper()
        if hpj_status == _HPJ_REFUND_STATUS_REFUNDED:
            normalized: Literal[
                "SUCCEEDED", "PROCESSING", "FAILED", "UNKNOWN"
            ] = "SUCCEEDED"
        elif hpj_status == _HPJ_REFUND_STATUS_PROCESSING:
            normalized = "PROCESSING"
        elif hpj_status == _HPJ_REFUND_STATUS_FAILED:
            normalized = "FAILED"
        else:
            normalized = "UNKNOWN"
        return CreateRefundResult(
            gateway_refund_id=gateway_refund_id,
            status=normalized,
            raw=body,
        )

    async def query_refund(
        self, request: QueryRefundRequest
    ) -> Literal["SUCCEEDED", "PROCESSING", "FAILED", "NOTFOUND"]:
        # Hupijiao has no dedicated refund-query endpoint (see
        # https://www.xunhupay.com/doc/api/refund.html — only "发起退款" exists).
        # Refund completion is observed two ways:
        #   1) The async webhook re-fires with status=CD (parse_notify maps
        #      CD → REFUNDED).
        #   2) The order-query endpoint reports status=CD for the original
        #      trade_order_id once the refund settles.
        # We reuse path (2) for the polling fallback.
        if not request.invoice_no:
            # No way to query without the original invoice_no.
            raise GatewayBusinessError(
                "hupijiao query_refund requires invoice_no"
            )
        try:
            qr = await self.query_by_out_trade_no(request.invoice_no)
        except GatewayBusinessError as exc:
            if "not" in str(exc).lower() and "found" in str(exc).lower():
                return "NOTFOUND"
            raise
        # Map order-query status → refund-query status.
        if qr.status == "CLOSED":  # CD on order = refunded
            return "SUCCEEDED"
        if qr.status == "SUCCESS":  # OD = paid, refund still pending
            return "PROCESSING"
        if qr.status == "NOTFOUND":
            return "NOTFOUND"
        return "PROCESSING"
