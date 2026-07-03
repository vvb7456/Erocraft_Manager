"""Admin routes for issued coupons.

Allows admins to:

* List/search issued coupons (filter by user, status, template).
* Manually grant a coupon from a template to a user.
* Revoke an unused/reserved coupon.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §11.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.billing import Coupon, CouponTemplate
from app.db.models.pterodactyl import PteroUser
from app.schemas.coupons import (
    CouponListResponse,
    CouponOut,
    ManualGrantRequest,
    RevokeCouponRequest,
)
from app.services.audit import log_manager_activity
from app.services.billing import coupon_templates as tpl_svc
from app.services.billing import coupons as svc
from app.core.time import utc_naive_now

router = APIRouter(prefix="/admin/billing/coupons", tags=["billing"])


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
async def list_coupons(
    user_id: int | None = None,
    status_: str | None = Query(default=None, alias="status"),
    template_id: int | None = None,
    code: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponListResponse:
    stmt = select(Coupon)
    count_stmt = select(func.count(Coupon.id))
    filters = []
    if user_id is not None:
        filters.append(Coupon.user_id == user_id)
    if status_:
        if status_ == "expired":
            # "expired" is a derived view: unused coupons past their
            # expiry. There is no stored ``expired`` status anymore.
            filters.append(Coupon.status == "unused")
            filters.append(Coupon.expires_at <= utc_naive_now())
        else:
            filters.append(Coupon.status == status_)
    if template_id is not None:
        filters.append(Coupon.template_id == template_id)
    if code:
        filters.append(Coupon.code == code.strip().upper())
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(
            Coupon.code.ilike(like),
            cast(Coupon.user_id, String).ilike(like),
        ))
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)
    stmt = stmt.order_by(Coupon.id.desc()).limit(limit).offset(offset)
    rows = list((await db.execute(stmt)).scalars().all())
    total = int(await db.scalar(count_stmt) or 0)

    # Side lookup for template names — small N per page is fine.
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
        total=total,
    )


@router.post("/grant", response_model=CouponOut, status_code=201)
async def manual_grant(
    payload: ManualGrantRequest,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponOut:
    try:
        tpl = await tpl_svc.get_template(db, payload.template_id)
    except tpl_svc.CouponTemplateNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not tpl.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="coupon.template_inactive",
        )
    # Verify user exists in the panel.
    from app.db.models.pterodactyl import PteroUser as _PteroUser

    target = await db.get(_PteroUser, payload.user_id)
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="user.not_found"
        )
    coupon = await svc.issue_from_template(
        db, template=tpl, user_id=payload.user_id, source="admin_grant"
    )
    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        status="success",
        detail_key="billing.coupon.granted",
        detail_params={
            "coupon_id": coupon.id,
            "coupon_code": coupon.code,
            "user_id": payload.user_id,
            "user_username": target.username,
            "template_id": tpl.id,
            "template_name": tpl.name,
            "template_code": tpl.code,
        },
    )
    return _serialize(coupon, template_name=tpl.name)


@router.post("/{coupon_id}/revoke", response_model=CouponOut)
async def revoke(
    coupon_id: int,
    payload: RevokeCouponRequest,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponOut:
    try:
        coupon = await svc.revoke(
            db,
            coupon_id=coupon_id,
            actor_user_id=int(actor.id),
            reason=payload.reason,
        )
    except svc.CouponNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.CouponError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    tpl = await db.get(CouponTemplate, coupon.template_id)
    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        status="success",
        detail_key="billing.coupon.revoked",
        detail_params={
            "coupon_id": coupon_id,
            "coupon_code": coupon.code,
            "user_id": coupon.user_id,
            "template_name": tpl.name if tpl else "",
            "reason": payload.reason or "",
        },
    )
    return _serialize(coupon, template_name=tpl.name if tpl else None)
