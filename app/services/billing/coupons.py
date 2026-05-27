"""Coupon instance lifecycle service.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §4.2 / §5 / §15.

State machine (enforced by status-guarded UPDATE everywhere):

::

    unused ──reserve──▶ reserved ──use──▶ used (terminal)
       │                    │
       │                    ▼
       │                  release
       │                    │
       └─────────────────────│
                            ▼
                          unused

    (any) ──admin-revoke──▶ revoked (terminal)

Expiry is a *derived* fact (``status == 'unused' AND expires_at <= now``),
not a stored state. Past-expiry coupons are filtered out by the
``expires_at`` predicate on every read path; there is no cron job.

Invariants enforced here (also doc §15):

* **C1 — snapshot immutable**: ``discount_fen`` / ``min_order_fen`` /
  ``applicable_*`` are copied from the template at issue-time and never
  re-read from the template afterwards.
* **C2 — at most one reservation per order**: enforced by the
  ``uk_coupon_reserved_order`` unique index on ``reserved_order_id``.
* **C3 — exclusive reservation**: a coupon held by ``reserve()`` is
  invisible to all subsequent ``list_usable_for_order()`` calls.
* **C4 — never below zero**: the actual discount applied is
  ``min(snapshot_discount_fen, order_subtotal_fen)``; the difference (if
  any) is dropped, never refunded.
"""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.billing import (
    COUPON_SOURCE_VALUES,
    BillingPlan,
    Coupon,
    CouponTemplate,
)

logger = logging.getLogger(__name__)

# Coupon codes are 16 chars from a hex-friendly alphabet (no 0/O/1/I/L).
# 32**16 ≈ 1.2 × 10^24 — far beyond any realistic collision pressure.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_CODE_LEN = 16
_CODE_MAX_RETRIES = 5


class CouponError(Exception):
    pass


class CouponNotFound(CouponError):
    pass


class CouponNotUsable(CouponError):
    """Coupon exists but cannot be used right now (expired / used / etc.)."""


class CouponNotApplicable(CouponError):
    """Coupon's snapshot constraints don't match this order."""


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


# --------------------------------------------------------------------------- #
# Applicability check (snapshot vs. order context)
# --------------------------------------------------------------------------- #


def _is_applicable(
    coupon: Coupon,
    *,
    order_kind: str,
    plan_id: int | None,
    subtotal_fen: int,
    now: datetime,
) -> tuple[bool, str | None]:
    """Pure check; returns (ok, reason_code) — None reason on success.

    Reason codes (stable, machine-readable; useful for i18n in the UI):

    * ``not_unused`` — coupon already reserved/used/revoked.
    * ``expired_at_check`` — past ``expires_at``.
    * ``below_min`` — subtotal below ``min_order_fen``.
    * ``kind_not_allowed`` — order_kind not in snapshot whitelist.
    * ``plan_not_allowed`` — plan_id not in snapshot whitelist.
    """
    if coupon.status != "unused":
        return False, "not_unused"
    if coupon.expires_at <= now:
        return False, "expired_at_check"
    if subtotal_fen < coupon.min_order_fen:
        return False, "below_min"
    if coupon.applicable_order_kinds and order_kind not in coupon.applicable_order_kinds:
        return False, "kind_not_allowed"
    if coupon.applicable_plan_ids:
        if plan_id is None or plan_id not in coupon.applicable_plan_ids:
            return False, "plan_not_allowed"
    return True, None


# --------------------------------------------------------------------------- #
# Issue (admin / system / referral)
# --------------------------------------------------------------------------- #


async def issue_from_template(
    db: AsyncSession,
    *,
    user_id: int,
    template: CouponTemplate,
    source: str,
    source_ref_id: int | None = None,
    valid_days_override: int | None = None,
    commit: bool = True,
) -> Coupon:
    """Issue a fresh coupon to ``user_id`` from ``template`` (snapshot copy).

    ``source`` must be one of ``COUPON_SOURCE_VALUES``. ``commit=False``
    lets callers (e.g. the referral reward path) batch multiple issues
    into a single transaction — but they must handle ``IntegrityError``
    on the global code collision themselves in that case.
    """
    if source not in COUPON_SOURCE_VALUES:
        raise CouponError(f"invalid coupon source: {source!r}")
    if not template.is_active:
        raise CouponError(f"template {template.code!r} is inactive")

    now = utc_naive_now()
    valid_days = valid_days_override or template.valid_days
    expires_at = now + timedelta(days=valid_days)

    for _ in range(_CODE_MAX_RETRIES):
        coupon = Coupon(
            code=_generate_code(),
            template_id=template.id,
            user_id=user_id,
            source=source,
            source_ref_id=source_ref_id,
            status="unused",
            discount_fen=template.discount_fen,
            min_order_fen=template.min_order_fen,
            applicable_plan_ids=(
                list(template.applicable_plan_ids)
                if template.applicable_plan_ids else None
            ),
            applicable_order_kinds=(
                list(template.applicable_order_kinds)
                if template.applicable_order_kinds else None
            ),
            issued_at=now,
            expires_at=expires_at,
        )
        db.add(coupon)
        if not commit:
            try:
                await db.flush()
                return coupon
            except IntegrityError:
                # Caller is composing a larger tx — rollback is their
                # responsibility. We just bubble.
                raise
        try:
            await db.commit()
            await db.refresh(coupon)
            return coupon
        except IntegrityError as exc:
            await db.rollback()
            if "uk_coupon_code" in str(exc.orig):
                continue  # retry
            raise
    raise RuntimeError("coupon code generation exhausted retries")


# --------------------------------------------------------------------------- #
# List / lookup
# --------------------------------------------------------------------------- #


async def list_for_user(
    db: AsyncSession,
    user_id: int,
    *,
    statuses: Iterable[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Coupon]:
    """List coupons owned by ``user_id``, newest first."""
    stmt = select(Coupon).where(Coupon.user_id == user_id)
    if statuses is not None:
        statuses = list(statuses)
        if statuses:
            stmt = stmt.where(Coupon.status.in_(statuses))
    stmt = (
        stmt.order_by(Coupon.created_at.desc(), Coupon.id.desc())
        .limit(min(max(limit, 1), 500))
        .offset(max(offset, 0))
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_usable_for_order(
    db: AsyncSession,
    user_id: int,
    *,
    order_kind: str,
    plan_id: int | None,
    subtotal_fen: int,
) -> list[Coupon]:
    """Return user's unused, unexpired coupons that match this order context.

    This is the source-of-truth feed for the checkout-modal ``<select>``.
    We deliberately do not include ``reserved`` coupons — once a coupon
    is held by another in-flight order it must not appear for a parallel
    order on a different tab.
    """
    now = utc_naive_now()
    stmt = (
        select(Coupon)
        .where(
            Coupon.user_id == user_id,
            Coupon.status == "unused",
            Coupon.expires_at > now,
            Coupon.min_order_fen <= subtotal_fen,
        )
        .order_by(
            # Largest discount first so the default selection (if the UI
            # picks index 0) is the best deal.
            Coupon.discount_fen.desc(),
            Coupon.expires_at.asc(),
            Coupon.id.asc(),
        )
    )
    rows = list((await db.execute(stmt)).scalars().all())
    # In-Python filter for the JSON whitelists — pushing this into SQL
    # would need vendor-specific JSON_CONTAINS and the per-user coupon
    # count is small enough that filtering in Python is fine.
    return [
        c for c in rows
        if _is_applicable(
            c,
            order_kind=order_kind,
            plan_id=plan_id,
            subtotal_fen=subtotal_fen,
            now=now,
        )[0]
    ]


async def get_by_code_for_user(
    db: AsyncSession, user_id: int, code: str
) -> Coupon | None:
    return (
        await db.execute(
            select(Coupon).where(
                Coupon.user_id == user_id,
                Coupon.code == code.strip().upper(),
            )
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Reserve / release / use (the order-flow hooks)
# --------------------------------------------------------------------------- #


async def reserve_for_order(
    db: AsyncSession,
    *,
    user_id: int,
    coupon_code: str,
    order_id: int,
    order_kind: str,
    plan_id: int | None,
    subtotal_fen: int,
) -> Coupon:
    """Atomically claim ``coupon_code`` for ``order_id``.

    Must be called inside the same transaction that creates the order.
    Uses a status-guarded UPDATE so concurrent reservations on the same
    coupon all-but-one fail with :class:`CouponNotUsable`.

    Returns the refreshed coupon (status=``reserved``, reserved_order_id
    set). Caller is responsible for committing the surrounding tx.
    """
    coupon = await get_by_code_for_user(db, user_id, coupon_code)
    if coupon is None:
        raise CouponNotFound("优惠券不存在或不属于你")

    now = utc_naive_now()
    ok, reason = _is_applicable(
        coupon,
        order_kind=order_kind,
        plan_id=plan_id,
        subtotal_fen=subtotal_fen,
        now=now,
    )
    if not ok:
        # Pre-check before we even attempt the UPDATE so we can produce
        # a precise error message; the UPDATE below would simply return
        # rowcount=0 without telling us why.
        if reason in ("not_unused", "expired_at_check"):
            raise CouponNotUsable(_reason_to_msg(reason))
        raise CouponNotApplicable(_reason_to_msg(reason))

    rc = await db.execute(
        update(Coupon)
        .where(
            Coupon.id == coupon.id,
            Coupon.status == "unused",
            Coupon.expires_at > now,
        )
        .values(
            status="reserved",
            reserved_order_id=order_id,
            reserved_at=now,
        )
    )
    if rc.rowcount == 0:
        # Someone else won — re-read for a fresh status.
        await db.refresh(coupon)
        raise CouponNotUsable(_reason_to_msg("not_unused"))
    await db.flush()
    await db.refresh(coupon)
    return coupon


async def release_for_order(
    db: AsyncSession, *, order_id: int, commit: bool = True
) -> int:
    """Release any coupon reserved by ``order_id`` back to ``unused``.

    Idempotent: returns the number of rows actually released (0 or 1).
    Called from cancel_order, _rollback_failed_order, and the
    apply_engine terminate path. Released coupons return to ``unused``;
    if past ``expires_at`` they're simply filtered out by the read paths
    (no status materialization).
    """
    now = utc_naive_now()
    rc = await db.execute(
        update(Coupon)
        .where(
            Coupon.reserved_order_id == order_id,
            Coupon.status == "reserved",
        )
        .values(
            status="unused",
            reserved_order_id=None,
            reserved_at=None,
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return rc.rowcount or 0


async def mark_used_for_order(
    db: AsyncSession,
    *,
    order_id: int,
    actual_discount_fen: int,
    commit: bool = True,
) -> int:
    """Transition the reserved coupon to ``used`` once the order applied.

    Called from the apply_engine post-action hook (after status='applied'
    is set). ``actual_discount_fen`` is what we actually subtracted —
    usually equals snapshot ``discount_fen`` but may be smaller if the
    order subtotal was less than the discount (invariant C4).
    """
    now = utc_naive_now()
    rc = await db.execute(
        update(Coupon)
        .where(
            Coupon.reserved_order_id == order_id,
            Coupon.status == "reserved",
        )
        .values(
            status="used",
            used_order_id=order_id,
            used_at=now,
            actual_discount_fen=max(0, int(actual_discount_fen)),
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return rc.rowcount or 0


# --------------------------------------------------------------------------- #
# Cron / admin
# --------------------------------------------------------------------------- #


async def revoke(
    db: AsyncSession,
    *,
    coupon_id: int,
    actor_user_id: int | None,
    reason: str | None,
) -> Coupon:
    """Admin revoke — only allowed for ``unused`` / ``reserved`` coupons.

    Used coupons cannot be revoked (we'd have to also refund the order
    discount); admins should issue a refund through the billing flow
    instead.
    """
    coupon = await db.get(Coupon, coupon_id)
    if coupon is None:
        raise CouponNotFound(f"coupon {coupon_id} not found")
    if coupon.status in ("used", "revoked"):
        raise CouponError(
            f"cannot revoke coupon in status {coupon.status!r}"
        )

    now = utc_naive_now()
    rc = await db.execute(
        update(Coupon)
        .where(
            Coupon.id == coupon_id,
            Coupon.status.in_(("unused", "reserved")),
        )
        .values(
            status="revoked",
            revoked_at=now,
            revoked_by=actor_user_id,
            revoke_reason=(reason or None),
            # Clear reservation so the linked order isn't blocked on a
            # dangling FK — the order's coupon_id stays for audit but the
            # coupon row no longer says "I'm held by you".
            reserved_order_id=None,
            reserved_at=None,
        )
    )
    await db.commit()
    if rc.rowcount == 0:
        raise CouponError("coupon state changed during revoke; retry")
    await db.refresh(coupon)
    return coupon


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


_REASON_MSG = {
    "not_unused": "优惠券已被使用或不可用",
    "expired_at_check": "优惠券已过期",
    "below_min": "订单金额未达到优惠券的最低消费",
    "kind_not_allowed": "优惠券不适用于此类订单",
    "plan_not_allowed": "优惠券不适用于此套餐",
}


def _reason_to_msg(reason: str) -> str:
    return _REASON_MSG.get(reason, "优惠券不可用")
