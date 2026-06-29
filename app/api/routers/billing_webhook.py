"""Public payment-gateway webhooks — see ``docs/BILLING_DESIGN.md`` §7.

Endpoints are public (no session cookie / no admin guard) — security is
provided by per-gateway signature verification inside ``parse_notify``.

Hupijiao posts ``application/x-www-form-urlencoded`` bodies, and demands
the literal string ``success`` in the response body to stop retries —
returning anything else (including JSON ``{"ok": true}``) makes them
re-deliver up to 5 times over 6 hours.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.core.time import utc_naive_now
from app.db.models.billing import BillingInvoice, BillingPaymentEvent
from app.services.billing import incidents, payments
from app.services.billing.gateway import registry as gateway_registry
from app.services.billing.gateway.base import GatewaySignatureError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing-webhook"])

_SUCCESS_BODY = "success"
"""Literal hupijiao expects in the HTTP body to mark a notify as ack'd."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _record_event(
    db: AsyncSession,
    *,
    gateway_code: str,
    event_type: str,
    signature_ok: bool,
    invoice_id: int | None,
    transaction_id: str | None,
    raw_headers: dict[str, str],
    raw_body: str,
    received_at: datetime,
) -> int:
    """Insert a payment_events row and return its id."""
    evt = BillingPaymentEvent(
        gateway_code=gateway_code,
        event_type=event_type,
        signature_ok=signature_ok,
        invoice_id=invoice_id,
        transaction_id=transaction_id,
        raw_headers=raw_headers,
        raw_body=raw_body,
        received_at=received_at,
    )
    db.add(evt)
    await db.flush()
    evt_id = evt.id
    await db.commit()
    return evt_id


async def _mark_event_processed(
    db: AsyncSession, evt_id: int, result_tag: str
) -> None:
    await db.execute(
        update(BillingPaymentEvent)
        .where(BillingPaymentEvent.id == evt_id)
        .values(processed_at=utc_naive_now(), process_result=result_tag)
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Generic notify dispatch — shared by all gateway webhook endpoints.
# --------------------------------------------------------------------------- #
# Both 虎皮椒 and Alipay expect the literal ``success`` body to ack; a non-200
# resp makes the gateway retry (give us another inspection shot). The handler
# logic is gateway-agnostic after ``parse_notify`` (§7.2) — only the signature
# verification inside the adapter differs.


async def _handle_notify(
    gateway_code: str, request: Request, db: AsyncSession
) -> PlainTextResponse:
    received_at = utc_naive_now()
    form = await request.form()
    raw_form: dict[str, Any] = {k: v for k, v in form.items()}
    raw_headers = {k: v for k, v in request.headers.items()}
    raw_body = json.dumps(raw_form, ensure_ascii=False)

    # ── 1) Verify signature
    await gateway_registry.ensure_loaded(db)
    try:
        gateway = gateway_registry.get(gateway_code)
    except KeyError:
        logger.error("%s webhook arrived but gateway not registered", gateway_code)
        return PlainTextResponse("gateway not configured", status_code=503)

    try:
        event = gateway.parse_notify(raw_form)
    except GatewaySignatureError as exc:
        try:
            await _record_event(
                db,
                gateway_code=gateway_code,
                event_type=f"{gateway_code}.payment.invalid",
                signature_ok=False,
                invoice_id=None,
                transaction_id=None,
                raw_headers=raw_headers,
                raw_body=raw_body,
                received_at=received_at,
            )
        except Exception:
            logger.exception("failed to audit invalid %s notify", gateway_code)
        logger.warning("%s webhook signature failure: %s", gateway_code, exc)
        # Non-200 so the gateway retries (give us another inspection shot).
        return PlainTextResponse("invalid sign", status_code=400)

    # ── 2) Audit row
    evt_id = await _record_event(
        db,
        gateway_code=gateway_code,
        event_type=f"{gateway_code}.payment.{event.status.lower()}",
        signature_ok=True,
        invoice_id=None,
        transaction_id=event.transaction_id or None,
        raw_headers=raw_headers,
        raw_body=raw_body,
        received_at=received_at,
    )

    # ── 3) Look up invoice by out_trade_no (== invoice_no)
    invoice = await db.scalar(
        select(BillingInvoice).where(
            BillingInvoice.invoice_no == event.out_trade_no
        )
    )
    if invoice is None:
        # Cross-environment / merchant misconfig — money charged but no
        # local invoice. Per §7.2, log manual_review_required and ACK.
        await incidents.log_incident(
            "manual_review_required",
            payload={
                "subkind": "unknown_invoice_payment",
                "out_trade_no": event.out_trade_no,
                "gateway_transaction_id": event.transaction_id,
                "amount_fen": event.amount_fen,
                "event_id": evt_id,
            },
        )
        await _mark_event_processed(db, evt_id, "invoice_not_found")
        return PlainTextResponse(_SUCCESS_BODY)

    await db.execute(
        update(BillingPaymentEvent)
        .where(BillingPaymentEvent.id == evt_id)
        .values(invoice_id=invoice.id)
    )
    await db.commit()

    # ── 4) Amount mismatch detection (manual_review branch in add_payment)
    mismatch_expected = (
        invoice.total_fen if event.amount_fen != invoice.total_fen else None
    )

    # ── 5) Dispatch by status
    if event.status == "SUCCESS":
        result_tag: str
        try:
            await payments.add_payment(
                db,
                invoice.id,
                gateway_code=gateway_code,
                transaction_id=event.transaction_id,
                amount_fen=event.amount_fen,
                raw_event_id=evt_id,
                amount_mismatch_expected=mismatch_expected,
            )
            result_tag = (
                "amount_mismatch_recorded"
                if mismatch_expected is not None
                else "ok"
            )
        except payments.CrossInvoiceTransactionError as exc:
            await incidents.log_incident(
                "manual_review_required",
                invoice_id=invoice.id,
                order_id=invoice.order_id,
                payload={
                    "subkind": "cross_invoice_transaction",
                    **exc.detail,
                },
            )
            result_tag = "cross_invoice_transaction"
    else:
        # REFUNDED / REFUND_PROCESSING / REFUND_FAIL — audit only.
        # Refund truth is established by §10.3 polling, not by webhook.
        result_tag = f"audit_only_{event.status.lower()}"

    await _mark_event_processed(db, evt_id, result_tag)
    return PlainTextResponse(_SUCCESS_BODY)


# --------------------------------------------------------------------------- #
# POST /webhook/hupijiao
# --------------------------------------------------------------------------- #


@router.post("/webhook/hupijiao", response_class=PlainTextResponse)
async def hupijiao_notify(
    request: Request, db: AsyncSession = Depends(get_db)
) -> PlainTextResponse:
    """Hupijiao payment-success webhook.

    Implements §7.2 step-by-step. Always returns ``success`` (HTTP 200)
    on signature-valid notifies even if internal processing detects a
    manual-review situation — the incident captures the anomaly and a
    human resolves it without hupijiao re-delivering the same payload.
    """
    return await _handle_notify("hupijiao", request, db)


# --------------------------------------------------------------------------- #
# POST /webhook/alipay_direct
# --------------------------------------------------------------------------- #


@router.post("/webhook/alipay_direct", response_class=PlainTextResponse)
async def alipay_direct_notify(
    request: Request, db: AsyncSession = Depends(get_db)
) -> PlainTextResponse:
    """Alipay open-platform payment-success webhook.

    Alipay posts ``application/x-www-form-urlencoded`` and expects the literal
    ``success`` body to stop retries — identical ack convention to 虎皮椒.
    Signature is RSA2-verified inside the adapter against the Alipay public key.
    """
    return await _handle_notify("alipay_direct", request, db)
