"""User-facing billing endpoints — order creation / list / cancel.

Routes (mounted under ``/api`` in :mod:`app.api.routers`):

* ``POST   /user/orders``      — create order (renew or new_purchase)
* ``GET    /user/orders``      — list current user's orders
* ``GET    /user/orders/{id}`` — fetch one order with its invoice
* ``DELETE /user/orders/{id}`` — user-initiated cancel (§8.2)
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.time import to_iso_z
from app.db.models.billing import BillingInvoice, BillingOrder, BillingPayment
from sqlalchemy import select
from app.services.billing import payments
from app.services.billing.gateway_client import GatewayError
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.schemas.billing_orders import (
    CreateOrderRequest,
    CreateOrderResponse,
    OrderInvoiceOut,
    OrderOut,
    CheckoutOut,
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


def serialize_invoice(invoice: BillingInvoice) -> OrderInvoiceOut:
    return OrderInvoiceOut(
        id=invoice.id,
        invoice_no=invoice.invoice_no,
        status=invoice.status,
        total_fen=invoice.total_fen,
        currency_code=invoice.currency_code,
        due_at=to_iso_z(invoice.due_at) if invoice.due_at else None,
        paid_at=to_iso_z(invoice.paid_at) if invoice.paid_at else None,
        gateway_code=payments.PAYMENT_CHANNELS[invoice.gateway_code] if invoice.gateway_code is not None else None,
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
    target_server_name: str | None = None,
    coupon_code: str | None = None,
) -> OrderOut:
    snap = order.plan_snapshot
    return OrderOut(
        id=order.id,
        order_no=order.order_no,
        user_id=order.user_id,
        plan_id=order.plan_id,
        plan_code=snap["plan_code"],
        plan_name=snap["plan_name"],
        kind=order.kind,
        period_count=order.period_count,
        discount_pct=float(order.discount_pct),
        total_fen=order.total_fen,
        total_days=order.total_days,
        currency_code=snap["currency_code"],
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
        invoice=serialize_invoice(invoice) if invoice is not None else None,
        coupon_id=order.coupon_id,
        coupon_code=coupon_code,
        coupon_discount_fen=(
            order.coupon_discount_fen if order.coupon_id else None
        ),
    )


async def _resolve_coupon_code(db: AsyncSession, coupon_id: int | None) -> str | None:
    """Look up the public-facing ``EC-XXXX`` coupon code for one order.

    Returns ``None`` when the order never had a coupon, when the coupon
    was hard-deleted (ON DELETE SET NULL on ``orders.coupon_id``), or
    when the lookup fails for any reason — the order view degrades
    gracefully without the coupon row.
    """
    if not coupon_id:
        return None
    from app.db.models.billing import Coupon  # local import: avoid cycle

    row = await db.get(Coupon, coupon_id)
    return row.code if row else None


async def _bulk_resolve_coupon_codes(
    db: AsyncSession, coupon_ids: list[int]
) -> dict[int, str]:
    """Bulk variant of :func:`_resolve_coupon_code` for the list view."""
    if not coupon_ids:
        return {}
    from sqlalchemy import select

    from app.db.models.billing import Coupon

    rows = await db.execute(
        select(Coupon.id, Coupon.code).where(Coupon.id.in_(set(coupon_ids)))
    )
    return {cid: code for cid, code in rows.all()}


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
    coupon_code = await _resolve_coupon_code(db, order.coupon_id)
    return CreateOrderResponse(
        order=_serialize_order(order, invoice, coupon_code=coupon_code)
    )


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
    coupon_codes = await _bulk_resolve_coupon_codes(
        db, [o.coupon_id for o in rows if o.coupon_id]
    )
    return [
        _serialize_order(
            o,
            invoices_by_order.get(o.id),
            coupon_code=coupon_codes.get(o.coupon_id) if o.coupon_id else None,
        )
        for o in rows
    ]


@router.get("/resolve", response_model=dict[str, int])
async def resolve_order_endpoint(
    business_order_id: str | None = None, payment_id: str | None = None,
    user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    query = select(BillingOrder).where(BillingOrder.user_id == user.id)
    if business_order_id:
        query = query.where(BillingOrder.order_no == business_order_id)
    elif payment_id:
        query = query.join(BillingPayment).where(BillingPayment.gateway_id == payment_id)
    else:
        raise HTTPException(400, "请提供订单编号")
    order = await db.scalar(query)
    if order is None:
        raise HTTPException(404, "订单不存在")
    return {"id": order.id}


@router.post("/{order_id}/payments", response_model=CheckoutOut)
async def checkout_endpoint(
    order_id: int, replace: bool = False,
    user: PteroUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CheckoutOut:
    try:
        await orders_service.get_order(db, user, order_id)
        payment = await payments.checkout(db, order_id, replace=replace)
    except OrderError as exc:
        raise _http_for(exc) from exc
    except GatewayError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return CheckoutOut(checkout_url=cast(str, payment.checkout_url))


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
    server_name = await _resolve_target_server_name(db, order.target_server_id)
    coupon_code = await _resolve_coupon_code(db, order.coupon_id)
    return _serialize_order(
        order, invoice,
        target_server_name=server_name, coupon_code=coupon_code,
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
    coupon_code = await _resolve_coupon_code(db, order.coupon_id)
    return _serialize_order(
        order, invoice, coupon_code=coupon_code
    )
