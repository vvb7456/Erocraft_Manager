"""Admin routes for coupon template CRUD.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §11.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.billing import CouponTemplate
from app.db.models.pterodactyl import PteroUser
from app.schemas.coupons import (
    CouponTemplateIn,
    CouponTemplateOut,
    CouponTemplateUpdate,
)
from app.services.audit import log_manager_activity
from app.services.billing import coupon_templates as svc

router = APIRouter(
    prefix="/admin/billing/coupon-templates", tags=["billing"]
)


def _serialize(tpl: CouponTemplate) -> CouponTemplateOut:
    return CouponTemplateOut(
        id=tpl.id,
        code=tpl.code,
        name=tpl.name,
        description=tpl.description,
        discount_fen=tpl.discount_fen,
        min_order_fen=tpl.min_order_fen,
        valid_days=tpl.valid_days,
        applicable_plan_ids=tpl.applicable_plan_ids,
        applicable_order_kinds=tpl.applicable_order_kinds,
        is_active=tpl.is_active,
        is_builtin=tpl.is_builtin,
        created_at=tpl.created_at.isoformat() + "Z",
        updated_at=tpl.updated_at.isoformat() + "Z",
    )


@router.get("", response_model=list[CouponTemplateOut])
async def list_(
    include_inactive: bool = True,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CouponTemplateOut]:
    rows = await svc.list_templates(db, include_inactive=include_inactive)
    return [_serialize(t) for t in rows]


@router.get("/{template_id}", response_model=CouponTemplateOut)
async def get_one(
    template_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponTemplateOut:
    try:
        tpl = await svc.get_template(db, template_id)
    except svc.CouponTemplateNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _serialize(tpl)


@router.post("", response_model=CouponTemplateOut, status_code=201)
async def create(
    payload: CouponTemplateIn,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponTemplateOut:
    try:
        tpl = await svc.create_template(
            db,
            code=payload.code,
            name=payload.name,
            discount_fen=payload.discount_fen,
            description=payload.description,
            min_order_fen=payload.min_order_fen,
            valid_days=payload.valid_days,
            applicable_plan_ids=payload.applicable_plan_ids,
            applicable_order_kinds=payload.applicable_order_kinds,
            is_active=payload.is_active,
        )
    except svc.CouponTemplateCodeTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except svc.CouponTemplateError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        status="success",
        detail_key="billing.coupon_template.created",
        detail_params={"template_id": tpl.id, "name": tpl.name, "code": tpl.code},
    )
    return _serialize(tpl)


@router.patch("/{template_id}", response_model=CouponTemplateOut)
async def update(
    template_id: int,
    payload: CouponTemplateUpdate,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponTemplateOut:
    try:
        tpl = await svc.update_template(
            db,
            template_id,
            name=payload.name,
            description=payload.description,
            discount_fen=payload.discount_fen,
            min_order_fen=payload.min_order_fen,
            valid_days=payload.valid_days,
            applicable_plan_ids=payload.applicable_plan_ids,
            applicable_order_kinds=payload.applicable_order_kinds,
            is_active=payload.is_active,
        )
    except svc.CouponTemplateNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.CouponTemplateError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        status="success",
        detail_key="billing.coupon_template.updated",
        detail_params={"template_id": tpl.id, "name": tpl.name, "code": tpl.code},
    )
    return _serialize(tpl)


@router.delete("/{template_id}", status_code=204)
async def delete(
    template_id: int,
    actor: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        tpl = await svc.get_template(db, template_id)
    except svc.CouponTemplateNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    tpl_name = tpl.name
    tpl_code = tpl.code
    try:
        await svc.delete_template(db, template_id)
    except svc.CouponTemplateNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.CouponTemplateProtected as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except svc.CouponTemplateError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await log_manager_activity(
        db,
        actor=actor.username,
        category="billing",
        status="success",
        detail_key="billing.coupon_template.deleted",
        detail_params={"template_id": template_id, "name": tpl_name, "code": tpl_code},
    )
