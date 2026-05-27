"""Admin CRUD for coupon templates.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §4.2.

Templates are the *rules*; ``Coupon`` instances carry a snapshot at
issuance so admin edits never retro-apply (invariant C1). The only
template fields admins can mutate freely are ``name`` / ``description``
/ ``is_active`` — the *economic* fields (``discount_fen``,
``min_order_fen``, ``valid_days``, applicability) MAY be edited but the
change only affects coupons issued *after* the edit.

Built-in templates (``is_builtin=True``) cannot be deleted, only
deactivated; this protects the referral flow from accidentally being
broken by an over-zealous cleanup.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.billing import CouponTemplate


class CouponTemplateError(Exception):
    """Base error for template CRUD."""


class CouponTemplateNotFound(CouponTemplateError):
    pass


class CouponTemplateCodeTaken(CouponTemplateError):
    pass


class CouponTemplateProtected(CouponTemplateError):
    """Built-in template — cannot delete."""


_ORDER_KINDS = {"new_purchase", "renew", "upgrade"}


def _validate_applicable_order_kinds(
    kinds: Iterable[str] | None,
) -> list[str] | None:
    if kinds is None:
        return None
    cleaned = sorted({k.strip() for k in kinds if k and k.strip()})
    bad = [k for k in cleaned if k not in _ORDER_KINDS]
    if bad:
        raise CouponTemplateError(
            f"applicable_order_kinds contains invalid kind(s): {bad!r}"
        )
    return cleaned or None


def _validate_applicable_plan_ids(
    plan_ids: Iterable[int] | None,
) -> list[int] | None:
    if plan_ids is None:
        return None
    cleaned = sorted({int(pid) for pid in plan_ids})
    if any(pid <= 0 for pid in cleaned):
        raise CouponTemplateError("applicable_plan_ids must be positive ints")
    return cleaned or None


async def list_templates(
    db: AsyncSession, *, include_inactive: bool = True
) -> list[CouponTemplate]:
    stmt = select(CouponTemplate).order_by(CouponTemplate.id.asc())
    if not include_inactive:
        stmt = stmt.where(CouponTemplate.is_active.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_template(db: AsyncSession, template_id: int) -> CouponTemplate:
    tpl = await db.get(CouponTemplate, template_id)
    if tpl is None:
        raise CouponTemplateNotFound(f"coupon template {template_id} not found")
    return tpl


async def get_template_by_code(
    db: AsyncSession, code: str
) -> CouponTemplate | None:
    return (
        await db.execute(
            select(CouponTemplate).where(
                CouponTemplate.code == code.strip().upper()
            )
        )
    ).scalar_one_or_none()


async def create_template(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    discount_fen: int,
    description: str | None = None,
    min_order_fen: int = 0,
    valid_days: int = 30,
    applicable_plan_ids: Iterable[int] | None = None,
    applicable_order_kinds: Iterable[str] | None = None,
    is_active: bool = True,
) -> CouponTemplate:
    if discount_fen <= 0:
        raise CouponTemplateError("discount_fen must be > 0")
    if min_order_fen < 0:
        raise CouponTemplateError("min_order_fen must be >= 0")
    if valid_days <= 0:
        raise CouponTemplateError("valid_days must be > 0")

    tpl = CouponTemplate(
        code=code.strip().upper(),
        name=name.strip(),
        description=description,
        discount_fen=discount_fen,
        min_order_fen=min_order_fen,
        valid_days=valid_days,
        applicable_plan_ids=_validate_applicable_plan_ids(applicable_plan_ids),
        applicable_order_kinds=_validate_applicable_order_kinds(
            applicable_order_kinds
        ),
        is_active=is_active,
        is_builtin=False,
    )
    db.add(tpl)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uk_coupon_tpl_code" in str(exc.orig):
            raise CouponTemplateCodeTaken(
                f"coupon template code {code!r} already exists"
            ) from exc
        raise
    await db.refresh(tpl)
    return tpl


async def update_template(
    db: AsyncSession,
    template_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    discount_fen: int | None = None,
    min_order_fen: int | None = None,
    valid_days: int | None = None,
    applicable_plan_ids: Iterable[int] | None = None,
    applicable_order_kinds: Iterable[str] | None = None,
    is_active: bool | None = None,
    # Sentinel so callers can explicitly send ``None`` to clear the field
    # via the API layer; we use ``...`` to distinguish "not provided".
    _clear_plan_ids: bool = False,
    _clear_order_kinds: bool = False,
) -> CouponTemplate:
    tpl = await get_template(db, template_id)
    if name is not None:
        tpl.name = name.strip()
    if description is not None:
        tpl.description = description
    if discount_fen is not None:
        if discount_fen <= 0:
            raise CouponTemplateError("discount_fen must be > 0")
        tpl.discount_fen = discount_fen
    if min_order_fen is not None:
        if min_order_fen < 0:
            raise CouponTemplateError("min_order_fen must be >= 0")
        tpl.min_order_fen = min_order_fen
    if valid_days is not None:
        if valid_days <= 0:
            raise CouponTemplateError("valid_days must be > 0")
        tpl.valid_days = valid_days
    if _clear_plan_ids:
        tpl.applicable_plan_ids = None
    elif applicable_plan_ids is not None:
        tpl.applicable_plan_ids = _validate_applicable_plan_ids(
            applicable_plan_ids
        )
    if _clear_order_kinds:
        tpl.applicable_order_kinds = None
    elif applicable_order_kinds is not None:
        tpl.applicable_order_kinds = _validate_applicable_order_kinds(
            applicable_order_kinds
        )
    if is_active is not None:
        tpl.is_active = is_active
    await db.commit()
    await db.refresh(tpl)
    return tpl


async def delete_template(db: AsyncSession, template_id: int) -> None:
    tpl = await get_template(db, template_id)
    if tpl.is_builtin:
        raise CouponTemplateProtected(
            "built-in templates cannot be deleted; deactivate instead"
        )
    # FK on ``manager_billing_coupons.template_id`` is RESTRICT, so this
    # will raise IntegrityError if any issued coupon references it. We
    # surface a friendly error in that case.
    await db.delete(tpl)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CouponTemplateError(
            "template has issued coupons and cannot be deleted; "
            "deactivate it instead"
        ) from exc
