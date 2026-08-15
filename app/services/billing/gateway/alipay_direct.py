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
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

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
    GatewayPayloadError,
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
# wap.pay redirect URLs are valid for the order's biz timeout. The cashier
# timeout is now enforced via ``time_expire`` (absolute expiry) so Alipay
# itself refuses payment after the local order deadline.
_QR_VALID_MIN = 5
_CN_TZ = ZoneInfo("Asia/Shanghai")

# Alipay trade_status values (alipay.trade.query + notify)
_TS_SUCCESS = "TRADE_SUCCESS"
_TS_FINISHED = "TRADE_FINISHED"
_TS_WAIT = "WAIT_BUYER_PAY"
_TS_CLOSED = "TRADE_CLOSED"

# alipay.trade.close sub_codes meaning the trade already paid (or otherwise
# not closable because it left WAIT_BUYER_PAY) — caller must re-query.
_CLOSE_ALREADY_PAID_SUB_CODES = {
    "ACQ.TRADE_HAS_SUCCESS",
    "ACQ.TRADE_STATUS_ERROR",
    "ACQ.REASON_ILLEGAL_STATUS",
    "ACQ.REASON_TRADE_STATUS_INVALID",
}

# Alipay sub_code values meaning "no such trade on Alipay side" — the user
# never opened the cashier / the order expired on Alipay's end / an unpaid
# expired invoice is being reconciled. These surface as NOTFOUND; callers
# must not confuse that with revocation of an already-issued cashier URL.
_NOT_FOUND_SUB_CODES = {
    "ACQ.TRADE_NOT_EXIST",
    "ACQ.TRADE_HAS_CLOSE",
    "ACQ.PAYMENT_NOT_HAS_TRADE",
    "ACQ.REFUND_NOT_EXIST",
}


class _AlipayBusinessFailure(GatewayBusinessError):
    """Structured Alipay business failure returned by a signed response."""

    def __init__(
        self,
        *,
        method: str,
        code: str,
        sub_code: str,
        message: str,
    ) -> None:
        self.method = method
        self.code = code
        self.sub_code = sub_code
        self.sub_message = message
        super().__init__(
            f"alipay_direct {method} code={code} "
            f"sub_code={sub_code!r} sub_msg={message!r}"
        )


class _AlipayNotFound(_AlipayBusinessFailure):
    """Alipay reports that the referenced trade/refund does not exist."""


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


def _required_notify_text(value: Any, field: str) -> str:
    """Return a required scalar notify field, rejecting blank/malformed data."""

    if not isinstance(value, str):
        raise GatewayPayloadError(f"alipay_direct notify missing {field}")
    text = value.strip()
    if not text:
        raise GatewayPayloadError(f"alipay_direct notify missing {field}")
    return text


def _parse_notify_amount_fen(value: Any) -> int:
    """Parse Alipay's yuan amount without float rounding or non-finite values."""

    if value is None or isinstance(value, (dict, list, tuple, set, bool)):
        raise GatewayPayloadError("alipay_direct notify invalid total_amount")
    text = str(value).strip()
    if not text:
        raise GatewayPayloadError("alipay_direct notify invalid total_amount")
    try:
        yuan = Decimal(text)
    except (InvalidOperation, ValueError):
        raise GatewayPayloadError(
            "alipay_direct notify invalid total_amount"
        ) from None
    if not yuan.is_finite() or yuan <= 0:
        raise GatewayPayloadError("alipay_direct notify total_amount must be positive")
    fen = yuan * Decimal("100")
    if fen != fen.to_integral_value():
        raise GatewayPayloadError(
            "alipay_direct notify total_amount must have at most 2 decimals"
        )
    amount_fen = int(fen)
    if amount_fen <= 0:
        raise GatewayPayloadError("alipay_direct notify total_amount must be positive")
    return amount_fen


def _skip_json_whitespace(text: str, start: int) -> int:
    """Return the first non-whitespace index in a JSON string."""

    while start < len(text) and text[start] in " \t\n\r":
        start += 1
    return start


def _response_value_span(text: str, response_key: str) -> tuple[int, int] | None:
    """Locate the top-level ``response_key`` JSON value in ``text``.

    ``str.find``/brace matching is tempting here, but it can select a key
    embedded in an unrelated string (or a nested object).  Parsing only the
    outer object with :class:`json.JSONDecoder` keeps the original text and
    therefore the exact whitespace/escaping needed for signature checks.
    The final matching key wins, mirroring ``json.loads`` for duplicate keys.
    """

    decoder = json.JSONDecoder()
    index = _skip_json_whitespace(text, 0)
    if index >= len(text) or text[index] != "{":
        return None
    index += 1
    found: tuple[int, int] | None = None
    while True:
        index = _skip_json_whitespace(text, index)
        if index >= len(text):
            return None
        if text[index] == "}":
            return found
        try:
            key, key_end = decoder.raw_decode(text, index)
        except ValueError:
            return None
        if not isinstance(key, str):
            return None
        index = _skip_json_whitespace(text, key_end)
        if index >= len(text) or text[index] != ":":
            return None
        value_start = _skip_json_whitespace(text, index + 1)
        if value_start >= len(text):
            return None
        try:
            _value, value_end = decoder.raw_decode(text, value_start)
        except ValueError:
            return None
        if key == response_key and text[value_start] == "{":
            found = (value_start, value_end)
        index = _skip_json_whitespace(text, value_end)
        if index >= len(text):
            return None
        if text[index] == ",":
            index += 1
            continue
        if text[index] == "}":
            return found
        return None


def _extract_raw_response_bytes(
    raw: bytes, response_key: str, *, encoding: str
) -> bytes | None:
    """Extract the exact response-value bytes signed by Alipay.

    The outer JSON is decoded solely to locate the top-level value; the return
    value is sliced directly from ``raw``.  This preserves GBK/UTF-8 bytes,
    JSON escapes, key order and whitespace exactly as sent by Alipay.
    ``encoding`` must be the codec used to decode the body; a round-trip check
    guards against accidentally slicing offsets derived from a wrong charset.
    """

    try:
        text = raw.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return None
    try:
        # A valid JSON body should round-trip byte-for-byte.  Besides making
        # the offsets below safe, this rejects a declared GBK charset on an
        # actually UTF-8 body (and lets the caller try its fallback charset).
        if text.encode(encoding) != raw:
            return None
        span = _response_value_span(text, response_key)
        if span is None:
            return None
        # Re-encoding each prefix is only for offset calculation.  The bytes
        # returned to the verifier are always the original ``raw`` slice.
        start, end = span
        byte_start = len(text[:start].encode(encoding))
        byte_end = len(text[:end].encode(encoding))
    except (LookupError, UnicodeEncodeError):
        return None
    return raw[byte_start:byte_end]


def _decode_response_json(
    raw: bytes, declared_encoding: str | None
) -> tuple[str, dict[str, Any], str] | None:
    """Decode a JSON response using its charset, with UTF-8/GBK fallbacks."""

    candidates: list[str] = []
    for candidate in (declared_encoding, "utf-8", "gb18030", "gbk"):
        if candidate and candidate.lower() not in {item.lower() for item in candidates}:
            candidates.append(candidate)
    for encoding in candidates:
        try:
            text = raw.decode(encoding)
            if text.encode(encoding) != raw:
                continue
            parsed = json.loads(text)
        except (LookupError, UnicodeDecodeError, UnicodeEncodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return text, parsed, encoding
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
    _METHOD_CLOSE = "alipay.trade.close"
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
        params["biz_content"] = json.dumps(biz, separators=(",", ":"))
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
                f"alipay_direct gateway HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise GatewayBusinessError(
                f"alipay_direct HTTP {response.status_code}"
            )
        # Sandbox server sets charset=GBK. Decode using that declaration (with
        # UTF-8/GBK fallbacks), but retain ``response.content`` for signature
        # verification: Alipay signs the exact bytes of ``xxx_response``.
        decoded = _decode_response_json(response.content, response.encoding)
        if decoded is None:
            raise GatewayBusinessError(
                "alipay_direct gateway returned invalid JSON"
            )
        _response_text, body, response_encoding = decoded
        response_key = method.replace(".", "_") + "_response"
        inner = body.get(response_key)
        if not isinstance(inner, dict):
            raise GatewayBusinessError(f"alipay_direct missing {response_key}")
        # Verify response signature against the RAW inner JSON substring.
        # Alipay signs the exact bytes of ``xxx_response``'s value as it
        # appears in the HTTP body (with \uXXXX escapes, original key
        # order, etc). Re-serialising a parsed dict would break verification.
        sign_value = body.get("sign")
        if not isinstance(sign_value, str) or not sign_value.strip():
            # Alipay signs both successful and business-error responses. A
            # response without a signature is never safe to interpret, even
            # when its inner ``code`` looks like a harmless NOT_FOUND.
            raise GatewaySignatureError("alipay_direct response missing sign")
        sign = sign_value
        code = str(inner.get("code") or "")
        sub_code = str(inner.get("sub_code") or "")
        raw_inner = _extract_raw_response_bytes(
            response.content,
            response_key,
            encoding=response_encoding,
        )
        if raw_inner is None:
            raise GatewaySignatureError(
                f"alipay_direct: unable to extract raw {response_key} for verification"
            )
        try:
            sig_bytes = base64.b64decode(sign, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise GatewaySignatureError(
                "alipay_direct response: bad sign encoding"
            ) from exc
        if not sig_bytes:
            raise GatewaySignatureError("alipay_direct response: empty sign")
        try:
            self._public_key.verify(
                sig_bytes,
                raw_inner,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature as exc:
            raise GatewaySignatureError(
                "alipay_direct response signature mismatch"
            ) from exc
        if code != "10000":
            error_type = (
                _AlipayNotFound
                if sub_code in _NOT_FOUND_SUB_CODES
                else _AlipayBusinessFailure
            )
            raise error_type(
                method=method,
                code=code,
                sub_code=sub_code,
                message=str(inner.get("sub_msg") or inner.get("msg") or ""),
            )
        return inner

    # ------------------------------------------------------------------
    # PaymentGateway Protocol
    # ------------------------------------------------------------------

    async def create_invoice(
        self, request: CreateInvoiceRequest
    ) -> CreateInvoiceResult:
        seller_id = await self._resolve_seller_id()

        # Absolute expiry: Alipay refuses both cashier re-entry and payment
        # after this instant (per official docs: "接口请求和用户支付都不可
        # 超过 time_expire 时间"). Value = local invoice due_at converted to
        # Beijing time (Alipay system clock). Without it the default trade
        # lifetime is 15 DAYS, which let users pay long after local close.
        time_expire: str | None = None
        if request.due_at is not None:
            due_cn = request.due_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(_CN_TZ)
            time_expire = due_cn.strftime("%Y-%m-%d %H:%M:%S")

        # PC: alipay.trade.page.pay — desktop cashier
        biz_pc: dict[str, Any] = {
            "out_trade_no": request.invoice_no,
            "total_amount": f"{request.amount_fen / 100:.2f}",
            "subject": request.title,
            "product_code": "FAST_INSTANT_TRADE_PAY",
        }
        if time_expire:
            biz_pc["time_expire"] = time_expire
        if seller_id:
            biz_pc["seller_id"] = seller_id
        params_pc = self._common_params(
            self._METHOD_PAGE_PAY,
            notify_url=request.notify_url,
            return_url=request.return_url,
        )
        params_pc["biz_content"] = json.dumps(
            biz_pc, separators=(",", ":")
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
        if time_expire:
            biz_wap["time_expire"] = time_expire
        if seller_id:
            biz_wap["seller_id"] = seller_id
        params_wap = self._common_params(
            self._METHOD_WAP_PAY,
            notify_url=request.notify_url,
            return_url=request.return_url,
        )
        params_wap["biz_content"] = json.dumps(
            biz_wap, separators=(",", ":")
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
                "time_expire": time_expire,
            },
        )

    async def close_trade(
        self, out_trade_no: str
    ) -> Literal["CLOSED", "NOTFOUND", "ALREADY_PAID"]:
        """Close an unpaid Alipay trade (``alipay.trade.close``).

        Only trades in ``WAIT_BUYER_PAY`` can be closed. A cashier that was
        never opened (no trade yet) surfaces as ``ACQ.TRADE_NOT_EXIST`` and
        is normalized to ``NOTFOUND``. Before ``time_expire``, that result
        does not revoke a previously issued ``page.pay`` URL.
        """
        try:
            await self._post(self._METHOD_CLOSE, {"out_trade_no": out_trade_no})
        except _AlipayNotFound as exc:
            # Already closed is as strong as a successful close. A genuinely
            # absent trade is different: a previously issued page.pay URL can
            # still create it later, up to time_expire.
            if exc.sub_code == "ACQ.TRADE_HAS_CLOSE":
                return "CLOSED"
            return "NOTFOUND"
        except _AlipayBusinessFailure as exc:
            if exc.sub_code in _CLOSE_ALREADY_PAID_SUB_CODES:
                return "ALREADY_PAID"
            raise
        return "CLOSED"

    async def query_by_out_trade_no(self, out_trade_no: str) -> QueryResult:
        try:
            inner = await self._post(
                self._METHOD_QUERY, {"out_trade_no": out_trade_no}
            )
        except _AlipayNotFound:
            # 用户没开过收银台 / 超时 / 已被支付宝侧关闭。查询接口
            # 不能在这些子状态中继续细分，需由 close_trade 确认。
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
        transaction_id = str(inner.get("trade_no") or "").strip() or None
        total = inner.get("total_amount")
        amount_fen: int | None = None
        if total not in (None, ""):
            try:
                yuan = Decimal(str(total))
                fen = yuan * Decimal("100")
                if yuan.is_finite() and yuan > 0 and fen == fen.to_integral_value():
                    amount_fen = int(fen)
            except (InvalidOperation, TypeError, ValueError):
                amount_fen = None
        if status == "SUCCESS" and (transaction_id is None or amount_fen is None):
            # A paid query result without a stable gateway transaction id or
            # exact positive amount cannot be recorded safely.  Deferring it
            # lets a later query/webhook reconcile instead of inserting an
            # empty transaction id or silently substituting the invoice sum.
            raise GatewayPayloadError(
                "alipay_direct query SUCCESS missing valid trade_no/total_amount"
            )
        return QueryResult(
            status=status,
            transaction_id=transaction_id,
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

        out_trade_no = _required_notify_text(
            raw_form.get("out_trade_no"), "out_trade_no"
        )
        # A payment fact must always carry the gateway transaction id. Keeping
        # an empty id would violate the local unique/non-null constraints and
        # could turn an otherwise rejectable callback into a 500.
        trade_no = _required_notify_text(raw_form.get("trade_no"), "trade_no")
        amount_fen = _parse_notify_amount_fen(raw_form.get("total_amount"))

        trade_status = str(raw_form.get("trade_status") or "").upper()
        status: Literal[
            "SUCCESS", "CLOSED", "REFUNDED", "REFUND_PROCESSING", "REFUND_FAIL"
        ]
        if trade_status in (_TS_SUCCESS, _TS_FINISHED):
            status = "SUCCESS"
        elif trade_status == _TS_CLOSED:
            # Trade closed WITHOUT settlement — either merchant-initiated
            # ``alipay.trade.close`` or gateway-side timeout. Never a fund
            # fact; the webhook handler only reconciles this against any
            # existing succeeded transaction. (Refund truth stays with
            # refund.notify + §10.3 polling.)
            status = "CLOSED"
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
