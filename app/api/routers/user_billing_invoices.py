"""User-facing invoice endpoints — see ``BILLING_DESIGN.md`` §6.

* ``GET /api/user/invoices/{invoice_id}`` — single invoice detail with
  pay_url for the current user. Returns 404 (not 403) on cross-user
  access to avoid leaking invoice existence.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.api.routers.user_billing import _latest_transaction_id, serialize_invoice
from app.db.models.billing import BillingInvoice
from app.db.models.pterodactyl import PteroUser
from app.schemas.billing_orders import OrderInvoiceOut

router = APIRouter(prefix="/user/invoices", tags=["billing"])


@router.get("/{invoice_id}", response_model=OrderInvoiceOut)
async def get_invoice(
    invoice_id: int,
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderInvoiceOut:
    stmt = select(BillingInvoice).where(
        BillingInvoice.id == invoice_id,
        BillingInvoice.user_id == current_user.id,
    )
    invoice = (await db.execute(stmt)).scalar_one_or_none()
    if invoice is None:
        # Use 404 (not 403) to avoid leaking existence.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
    out = serialize_invoice(
        invoice, transaction_id=await _latest_transaction_id(db, invoice.id)
    )
    assert out is not None  # invoice was loaded above
    return out
