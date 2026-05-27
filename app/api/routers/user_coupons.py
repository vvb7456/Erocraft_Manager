"""User-facing coupon endpoints.

* ``GET  /api/user/coupons`` — list my coupons (optional filter for the
  checkout-modal ``<select>``).
* ``GET  /api/user/coupons/preview`` — discount preview for a code in the
  context of an in-progress order (so the modal can show ✓/✗ + amount).

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §10.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.time import utc_naive_now
from app.db.models.billing import Coupon, CouponTemplate
from app.db.models.pterodactyl import PteroUser
from app.schemas.coupons import (
    CouponListResponse,
    CouponOut,
    CouponPreviewResponse,
)
from app.services.billing import coupons as svc

router = APIRouter(prefix="/user/coupons", tags=["billing"])


def _iso(dt) -> str | None:
    return (dt.isoformat() + "Z") if dt is not None else None


def _serialize(c: Coupon, *, template_name: str | None = None) -> CouponOut:
    return CouponOut(
        id=c.id,
        code=c.code,
        template_id=c.template_id,
        template_name=template_name,
        user_id=c.user_id,
        status=c.status,
        source=c.source,
        discount_fen=c.discount_fen,
        min_order_fen=c.min_order_fen,
        applicable_plan_ids=c.applicable_plan_ids,
        applicable_order_kinds=c.applicable_order_kinds,
        issued_at=_iso(c.issued_at) or "",
        expires_at=_iso(c.expires_at) or "",
        used_at=_iso(c.used_at),
        used_order_id=c.used_order_id,
        actual_discount_fen=c.actual_discount_fen,
        reserved_order_id=c.reserved_order_id,
        reserved_at=_iso(c.reserved_at),
        revoked_at=_iso(c.revoked_at),
        revoke_reason=c.revoke_reason,
    )


@router.get("", response_model=CouponListResponse)
async def list_my_coupons(
    status_: str | None = Query(default=None, alias="status"),
    # If provided, the response is filtered to coupons usable for an
    # order with this context — the checkout-modal feed.
    order_kind: str | None = Query(default=None),
    plan_id: int | None = Query(default=None),
    subtotal_fen: int | None = Query(default=None, ge=0),
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CouponListResponse:
    # Checkout-modal mode — narrow filter.
    if order_kind and subtotal_fen is not None:
        rows = await svc.list_usable_for_order(
            db,
            int(user.id),
            order_kind=order_kind,
            plan_id=plan_id,
            subtotal_fen=int(subtotal_fen),
        )
    else:
        rows = await svc.list_for_user(
            db, int(user.id),
            statuses=([status_] if status_ else None),
        )
    tpl_ids = {c.template_id for c in rows}
    tpl_map: dict[int, str] = {}
    if tpl_ids:
        for t in (
            await db.execute(
                select(CouponTemplate).where(CouponTemplate.id.in_(tpl_ids))
            )
        ).scalars():
            tpl_map[t.id] = t.name
    return CouponListResponse(
        items=[_serialize(c, template_name=tpl_map.get(c.template_id)) for c in rows],
        total=len(rows),
    )


@router.get("/preview", response_model=CouponPreviewResponse)
async def preview(
    code: str,
    order_kind: str,
    subtotal_fen: int = Query(ge=0),
    plan_id: int | None = Query(default=None),
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CouponPreviewResponse:
    coupon = await svc.get_by_code_for_user(db, int(user.id), code)
    if coupon is None:
        return CouponPreviewResponse(applicable=False, reason="not_found")
    ok, reason = svc._is_applicable(
        coupon,
        order_kind=order_kind,
        plan_id=plan_id,
        subtotal_fen=int(subtotal_fen),
        now=utc_naive_now(),
    )
    if not ok:
        return CouponPreviewResponse(
            applicable=False, reason=svc._reason_to_msg(reason)
        )
    # Mirror the C4 floor (discount can never exceed subtotal).
    discount = min(coupon.discount_fen, int(subtotal_fen))
    return CouponPreviewResponse(applicable=True, discount_fen=discount)
