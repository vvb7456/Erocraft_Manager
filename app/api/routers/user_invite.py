"""User-facing invite (referral) endpoints.

* ``GET  /api/user/invite``         — return my invite code + stats + recent referrals.
* ``GET  /api/user/invite/referrals`` — paginated list of users I've referred.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §10.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.core.runtime_settings import BILLING_SPECS
from app.core.settings_store import get_settings_store
from app.db.models.billing import CouponTemplate
from app.db.models.manager import UserInviteCode, UserReferral
from app.db.models.pterodactyl import PteroUser
from app.schemas.referrals import (
    InviteCodeOut,
    InviteSummaryResponse,
    ReferralListResponse,
    ReferralOut,
    RewardPreview,
)
from app.services.user import invite_codes as svc

router = APIRouter(prefix="/user/invite", tags=["referral"])


def _iso(dt) -> str | None:
    return (dt.isoformat() + "Z") if dt is not None else None


async def _invite_url(db: AsyncSession, code: str) -> str | None:
    site = await get_settings_store().get(db, "SITE_URL", "")
    base = str(site or "").rstrip("/")
    return f"{base}/#/register?invite={code}" if base else None


async def _runtime(db: AsyncSession, key: str):
    spec = BILLING_SPECS[key]
    return await get_settings_store().get(db, key, spec.default_value())


async def _reward_preview(db: AsyncSession) -> RewardPreview:
    """Resolve the public-facing reward preview (no admin-only fields)."""
    enabled = bool(await _runtime(db, "REFERRAL_REWARD_ENABLED"))
    min_fen = int(await _runtime(db, "REFERRAL_QUALIFYING_MIN_FEN"))
    inviter_code = str(await _runtime(db, "REFERRAL_INVITER_TEMPLATE_CODE"))
    invitee_code = str(await _runtime(db, "REFERRAL_INVITEE_TEMPLATE_CODE"))

    async def _tpl(code: str) -> CouponTemplate | None:
        if not code:
            return None
        return (
            await db.execute(
                select(CouponTemplate).where(
                    CouponTemplate.code == code,
                    CouponTemplate.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

    inviter_tpl = await _tpl(inviter_code)
    invitee_tpl = await _tpl(invitee_code)

    return RewardPreview(
        enabled=enabled and inviter_tpl is not None and invitee_tpl is not None,
        qualifying_min_fen=min_fen,
        inviter_discount_fen=inviter_tpl.discount_fen if inviter_tpl else None,
        invitee_discount_fen=invitee_tpl.discount_fen if invitee_tpl else None,
        inviter_valid_days=inviter_tpl.valid_days if inviter_tpl else None,
        invitee_valid_days=invitee_tpl.valid_days if invitee_tpl else None,
        inviter_min_order_fen=inviter_tpl.min_order_fen if inviter_tpl else None,
        invitee_min_order_fen=invitee_tpl.min_order_fen if invitee_tpl else None,
    )


async def _serialize_referral(
    db: AsyncSession, r: UserReferral
) -> ReferralOut:
    invitee = await db.get(PteroUser, r.invitee_user_id)
    return ReferralOut(
        id=r.id,
        inviter_user_id=r.inviter_user_id,
        invitee_user_id=r.invitee_user_id,
        invitee_username=invitee.username if invitee else None,
        invitee_email=invitee.email if invitee else None,
        invite_code=r.invite_code,
        status=r.status,
        qualifying_order_id=r.qualifying_order_id,
        rewarded_at=_iso(r.rewarded_at),
        inviter_coupon_id=r.inviter_coupon_id,
        invitee_coupon_id=r.invitee_coupon_id,
        created_at=_iso(r.created_at) or "",
    )


@router.get("", response_model=InviteSummaryResponse)
async def my_invite(
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InviteSummaryResponse:
    row = await svc.get_or_create_for_user(db, int(user.id))
    invite_url = await _invite_url(db, row.code)

    # Stats by status — small per-user N so a single grouped query is fine.
    stats: dict[str, int] = {
        "registered": 0,
        "rewarded": 0,
        "revoked": 0,
    }
    stmt = (
        select(UserReferral.status, func.count(UserReferral.id))
        .where(UserReferral.inviter_user_id == int(user.id))
        .group_by(UserReferral.status)
    )
    for status_, n in (await db.execute(stmt)).all():
        stats[status_] = int(n)
    stats["total"] = sum(stats.values())

    # Most recent 10 referrals for the dashboard widget.
    recent_rows = list(
        (
            await db.execute(
                select(UserReferral)
                .where(UserReferral.inviter_user_id == int(user.id))
                .order_by(UserReferral.id.desc())
                .limit(10)
            )
        ).scalars()
    )
    recent = [await _serialize_referral(db, r) for r in recent_rows]
    reward = await _reward_preview(db)
    return InviteSummaryResponse(
        invite=InviteCodeOut(
            code=row.code,
            invite_url=invite_url,
            disabled=row.disabled_at is not None,
            created_at=_iso(row.created_at),
        ),
        stats=stats,
        recent=recent,
        reward=reward,
    )


@router.get("/referrals", response_model=ReferralListResponse)
async def my_referrals(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReferralListResponse:
    total = int(
        await db.scalar(
            select(func.count(UserReferral.id)).where(
                UserReferral.inviter_user_id == int(user.id)
            )
        )
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(UserReferral)
                .where(UserReferral.inviter_user_id == int(user.id))
                .order_by(UserReferral.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )
    items = [await _serialize_referral(db, r) for r in rows]
    return ReferralListResponse(items=items, total=total)
