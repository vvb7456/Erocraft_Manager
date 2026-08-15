"""Payment gateway Protocol and result/context dataclasses.

Adapters live in this package and implement :class:`PaymentGateway`.

Design note
-----------
Each adapter declares what it *needs* from the calling service through
small ``*Context`` dataclasses (e.g. :class:`InvoicePaymentContext`). The
calling service populates the context once from its ORM models; adapters
pull only the fields they care about. Adding a new gateway therefore
touches **only the adapter**, never the calling service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol


# --------------------------------------------------------------------------- #
# Result / event DTOs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CreateInvoiceResult:
    """Result of placing an order at the gateway."""

    gateway_order_id: str
    """Gateway-side internal order id (e.g. Hupijiao ``open_order_id``)."""

    code_url: str | None
    """PC QR-code image URL (Hupijiao ``url_qrcode``). 5-min validity."""

    pay_url: str | None
    """Mobile / H5 redirect URL (Hupijiao ``url``)."""

    expires_at: datetime
    """Local timestamp at which the QR code is considered expired."""

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Normalized status from gateway-side order query."""

    status: Literal["SUCCESS", "PROCESSING", "CLOSED", "NOTFOUND"]
    transaction_id: str | None
    amount_fen: int | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NotifyEvent:
    """Parsed + verified webhook payload.

    ``status`` semantics:

    * ``SUCCESS`` — funds settled (TRADE_SUCCESS / TRADE_FINISHED).
    * ``CLOSED`` — trade closed WITHOUT payment (merchant-initiated
      ``alipay.trade.close`` or timeout). Never produces a fund fact; the
      webhook handler reconciles against existing transactions only.
    * ``REFUNDED`` / ``REFUND_PROCESSING`` / ``REFUND_FAIL`` — refund-class
      notifications (audit only; refund truth comes from §10.3 polling).
    """

    out_trade_no: str
    transaction_id: str
    amount_fen: int
    status: Literal[
        "SUCCESS", "CLOSED", "REFUNDED", "REFUND_PROCESSING", "REFUND_FAIL"
    ]
    raw_form: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CreateRefundResult:
    """Result of placing a refund at the gateway.

    ``status`` reflects the gateway's *synchronous* refund state at the
    moment of acceptance. Adapters MUST normalize the gateway's native
    status code into one of the four values below so the caller does
    not need to know per-gateway semantics:

    * ``SUCCEEDED`` — refund already settled (e.g. Hupijiao ``refund_status=CD``).
      Caller may finalize immediately without waiting for a webhook.
    * ``PROCESSING`` — refund accepted but still in flight
      (e.g. Hupijiao ``refund_status=RD``).
    * ``FAILED`` — gateway-side immediate failure
      (e.g. Hupijiao ``refund_status=UD``).
    * ``UNKNOWN`` — gateway response did not include a status; treat as
      pending and poll/wait for webhook.
    """

    gateway_refund_id: str
    status: Literal["SUCCEEDED", "PROCESSING", "FAILED", "UNKNOWN"] = "UNKNOWN"
    raw: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Request context DTOs (caller -> adapter)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CreateInvoiceRequest:
    """All info an adapter may need to place an order at the gateway."""

    invoice_no: str
    amount_fen: int
    title: str
    notify_url: str
    return_url: str
    due_at: datetime | None = None
    """Local invoice deadline (UTC naive). Adapters with absolute-expiry
    support (e.g. Alipay ``time_expire``) must map it onto the gateway-side
    trade lifetime so that a locally-closed order can no longer be paid.
    ``None`` means "no local deadline known" — adapters fall back to their
    own defaults."""

    # Note: ``code_url`` is intentionally NOT part of this request — it is
    # a gateway response field. Hupijiao returns ``url_qrcode``; Alipay
    # page.pay has no pre-rendered QR.


@dataclass(frozen=True, slots=True)
class InvoicePaymentRef:
    """Identifiers of an already-paid invoice that adapters may use to
    locate the source transaction (for refund / query).

    Fields are best-effort; adapters that need a particular one should
    raise :class:`GatewayBusinessError` when it is missing.
    """

    invoice_no: str
    """Our invoice number (Hupijiao ``trade_order_id``, WeChat
    ``out_trade_no``, Alipay ``out_trade_no``)."""

    gateway_prepay_id: str | None
    """Gateway-internal order id from create_invoice (Hupijiao
    ``open_order_id``, WeChat ``prepay_id``, Stripe ``pi_*``)."""

    transaction_id: str | None
    """External pay-channel transaction id from the success webhook
    (Alipay ``trade_no``, WeChat ``transaction_id``, etc.)."""

    amount_fen: int


@dataclass(frozen=True, slots=True)
class CreateRefundRequest:
    """All info an adapter may need to issue a refund.

    This system only supports **full refunds** (the remaining refundable
    amount on the source transaction). Partial refunds are intentionally
    unsupported — see ``docs/BILLING_AUDIT_2026-05.md`` B-002.
    """

    invoice: InvoicePaymentRef
    out_refund_no: str
    reason: str


@dataclass(frozen=True, slots=True)
class QueryRefundRequest:
    """All info an adapter may need to look up a refund's status.

    Different gateways have different refund-query semantics:

    * **WeChat / Alipay**: dedicated refund query endpoint, keyed by
      ``out_refund_no`` or ``gateway_refund_id``.
    * **Hupijiao**: NO refund-query endpoint — refund status must be
      inferred from the order-query endpoint keyed by ``invoice_no``
      (status ``CD`` ⇒ refunded). Adapters that need the original
      invoice number read it from this DTO.
    """

    out_refund_no: str
    gateway_refund_id: str | None
    invoice_no: str | None = None


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #


class PaymentGateway(Protocol):
    """Common abstraction for payment back-ends.

    Adapter MUST be stateless apart from configuration loaded at construction.
    """

    code: str
    """Stable lowercase identifier persisted to ``invoice.gateway_code``."""

    display_name: str

    async def create_invoice(
        self, request: CreateInvoiceRequest
    ) -> CreateInvoiceResult: ...

    async def query_by_out_trade_no(self, out_trade_no: str) -> QueryResult: ...

    async def close_trade(self, out_trade_no: str) -> Literal[
        "CLOSED", "NOTFOUND", "ALREADY_PAID"
    ]:
        """Close an unpaid gateway-side trade.

        * ``CLOSED`` — gateway accepted and closed the trade (buyer can no
          longer pay against this ``out_trade_no``).
        * ``NOTFOUND`` — no trade has been created on the gateway side. This
          does not prove that a previously issued cashier URL is revoked.
        * ``ALREADY_PAID`` — trade already paid; caller should re-query and
          route through the last-second payment branch.

        Gateway errors bubble as :class:`GatewayError`; each caller decides
        whether its deadline and business semantics permit a local close.
        """
        ...

    def parse_notify(self, raw_form: dict[str, Any]) -> NotifyEvent:
        """Synchronous: verify signature + map to NotifyEvent. No I/O."""

    async def create_refund(
        self, request: CreateRefundRequest
    ) -> CreateRefundResult: ...

    async def query_refund(
        self, request: QueryRefundRequest
    ) -> Literal["SUCCEEDED", "PROCESSING", "FAILED", "NOTFOUND"]: ...


class GatewayError(Exception):
    """Base class for gateway-layer errors."""


class GatewaySignatureError(GatewayError):
    """Webhook or response failed signature verification."""


class GatewayPayloadError(GatewayError):
    """A signature-valid gateway payload is structurally invalid.

    This is deliberately separate from :class:`GatewaySignatureError`: a
    validly signed request with missing/invalid business fields is not an
    authentication failure, but it must still be rejected before it reaches
    payment bookkeeping (where a database constraint could otherwise turn it
    into a 500 response).
    """


class GatewayBusinessError(GatewayError):
    """Gateway returned a 4xx-style business failure (no retry)."""


class GatewayTransientError(GatewayError):
    """Network / 5xx / timeout — caller may retry / fall back."""
