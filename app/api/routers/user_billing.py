"""User-facing billing endpoints — order creation / list / cancel.

Routes (mounted under ``/api`` in :mod:`app.api.routers`):

* ``POST   /user/orders``      — create order (renew or new_purchase)
* ``GET    /user/orders``      — list current user's orders
* ``GET    /user/orders/{id}`` — fetch one order with its invoice
* ``DELETE /user/orders/{id}`` — user-initiated cancel (§8.2)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.time import to_iso_z
from app.db.models.billing import BillingInvoice, BillingInvoiceTransaction, BillingOrder, BillingPlan
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.schemas.billing_orders import (
    CreateOrderRequest,
    CreateOrderResponse,
    OrderInvoiceOut,
    OrderOut,
)
from app.services.billing import orders as orders_service
from app.services.billing.orders import (
    CannotCancel,
    GatewayUnavailable,
    InvalidOrderRequest,
    OrderAlreadyPaid,
    OrderError,
    OrderNotFound,
    PendingOrderExists,
    PlanNotPurchasable,
)

router = APIRouter(prefix="/user/orders", tags=["billing"])


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


def serialize_invoice(
    invoice: BillingInvoice | None,
    *,
    transaction_id: str | None = None,
) -> OrderInvoiceOut | None:
    if invoice is None:
        return None
    payload = invoice.gateway_payload or {}
    pay_url = payload.get("url") if isinstance(payload, dict) else None
    return OrderInvoiceOut(
        id=invoice.id,
        invoice_no=invoice.invoice_no,
        status=invoice.status,
        total_fen=invoice.total_fen,
        currency_code=invoice.currency_code,
        due_at=to_iso_z(invoice.due_at) if invoice.due_at else None,
        paid_at=to_iso_z(invoice.paid_at) if invoice.paid_at else None,
        gateway_code=invoice.gateway_code,
        gateway_prepay_id=invoice.gateway_prepay_id,
        transaction_id=transaction_id,
        code_url=invoice.gateway_code_url,
        pay_url=pay_url,
    )


async def _latest_transaction_id(
    db: AsyncSession, invoice_id: int
) -> str | None:
    from sqlalchemy import select

    return await db.scalar(
        select(BillingInvoiceTransaction.transaction_id)
        .where(BillingInvoiceTransaction.invoice_id == invoice_id)
        .order_by(BillingInvoiceTransaction.id.desc())
        .limit(1)
    )


async def _resolve_target_server_name(
    db: AsyncSession, target_server_id: int | None
) -> str | None:
    """Return server name only when the server exists and is not a placeholder.

    Placeholder occupier rows have ``external_id LIKE 'pending:%'`` and should
    be hidden from the user-facing detail view.
    """
    if not target_server_id:
        return None
    from sqlalchemy import select

    row = await db.execute(
        select(PteroServer.name, PteroServer.external_id).where(
            PteroServer.id == target_server_id
        )
    )
    record = row.first()
    if record is None:
        return None
    name, external_id = record
    if external_id and external_id.startswith("pending:"):
        return None
    return name


def _serialize_order(
    order: BillingOrder,
    invoice: BillingInvoice | None,
    *,
    transaction_id: str | None = None,
    target_server_name: str | None = None,
) -> OrderOut:
    snap = order.plan_snapshot or {}
    return OrderOut(
        id=order.id,
        order_no=order.order_no,
        user_id=order.user_id,
        plan_id=order.plan_id,
        plan_code=str(snap.get("plan_code", "")),
        plan_name=str(snap.get("plan_name", "")),
        kind=order.kind,
        period_count=order.period_count,
        discount_pct=float(order.discount_pct),
        total_fen=order.total_fen,
        total_days=order.total_days,
        currency_code=str(snap.get("currency_code", "CNY")),
        target_server_id=order.target_server_id,
        target_server_name=target_server_name,
        status=order.status,
        received_fen=order.received_fen,
        refunded_fen=order.refunded_fen,
        created_at=to_iso_z(order.created_at),
        updated_at=to_iso_z(order.updated_at),
        applied_at=to_iso_z(order.applied_at) if order.applied_at else None,
        closed_at=to_iso_z(order.closed_at) if order.closed_at else None,
        cancelled_at=to_iso_z(order.cancelled_at) if order.cancelled_at else None,
        invoice=serialize_invoice(invoice, transaction_id=transaction_id),
    )


# --------------------------------------------------------------------------- #
# Error mapping
# --------------------------------------------------------------------------- #


def _http_for(exc: OrderError) -> HTTPException:
    if isinstance(exc, OrderNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, GatewayUnavailable):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, OrderAlreadyPaid):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, CannotCancel):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, PendingOrderExists):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (PlanNotPurchasable, InvalidOrderRequest)):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.post("", response_model=CreateOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order_endpoint(
    payload: CreateOrderRequest,
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateOrderResponse:
    try:
        order = await orders_service.create_order(db, user, payload)
    except OrderError as exc:
        raise _http_for(exc) from exc
    invoice = await orders_service.get_invoice_for_order(db, order.id)
    return CreateOrderResponse(order=_serialize_order(order, invoice))


@router.get("", response_model=list[OrderOut])
async def list_orders_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrderOut]:
    rows = await orders_service.list_orders(db, user, limit=limit, offset=offset)
    if not rows:
        return []
    # Bulk fetch invoices to avoid N+1.
    from sqlalchemy import select

    invoice_rows = await db.execute(
        select(BillingInvoice).where(
            BillingInvoice.order_id.in_([o.id for o in rows])
        )
    )
    invoices_by_order: dict[int, BillingInvoice] = {
        inv.order_id: inv for inv in invoice_rows.scalars().all()
    }
    # Bulk fetch latest transaction_id per invoice.
    invoice_ids = [inv.id for inv in invoices_by_order.values()]
    tx_by_invoice: dict[int, str] = {}
    if invoice_ids:
        tx_rows = await db.execute(
            select(
                BillingInvoiceTransaction.invoice_id,
                BillingInvoiceTransaction.transaction_id,
            )
            .where(BillingInvoiceTransaction.invoice_id.in_(invoice_ids))
            .order_by(BillingInvoiceTransaction.id.desc())
        )
        for inv_id, tx_id in tx_rows.all():
            tx_by_invoice.setdefault(inv_id, tx_id)
    return [
        _serialize_order(
            o,
            invoices_by_order.get(o.id),
            transaction_id=(
                tx_by_invoice.get(invoices_by_order[o.id].id)
                if o.id in invoices_by_order
                else None
            ),
        )
        for o in rows
    ]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order_endpoint(
    order_id: int,
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    try:
        order = await orders_service.get_order(db, user, order_id)
    except OrderError as exc:
        raise _http_for(exc) from exc
    invoice = await orders_service.get_invoice_for_order(db, order.id)
    tx_id = await _latest_transaction_id(db, invoice.id) if invoice else None
    server_name = await _resolve_target_server_name(db, order.target_server_id)
    return _serialize_order(
        order, invoice, transaction_id=tx_id, target_server_name=server_name
    )


@router.delete("/{order_id}", response_model=OrderOut)
async def cancel_order_endpoint(
    order_id: int,
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    try:
        order = await orders_service.cancel_order(db, user, order_id)
    except OrderError as exc:
        raise _http_for(exc) from exc
    invoice = await orders_service.get_invoice_for_order(db, order.id)
    tx_id = await _latest_transaction_id(db, invoice.id) if invoice else None
    return _serialize_order(order, invoice, transaction_id=tx_id)
