"""Per-user invite-code service.

See ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §4.1.

Each user gets exactly one 8-character code, **lazy-generated** on first
access (account page render or admin lookup). The code uses an
unambiguous alphabet (no ``0/O/1/I``) for hand-typing, and collisions
during generation retry up to ``_MAX_RETRIES`` times before bubbling up.

Codes are case-insensitive on lookup but stored uppercase. The
``disabled_at`` field exists for the admin "disable but keep audit trail"
flow — when set, the row still resolves for historical referral lookups
but :func:`resolve_active_inviter` rejects it.
"""

from __future__ import annotations

import secrets
from typing import Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.manager import UserInviteCode

# 32 unambiguous chars — drops 0/O, 1/I/L. 32**8 ≈ 1.1 × 10^12 — collision
# odds are negligible at expected user scale.
_ALPHABET: Final[str] = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_CODE_LEN: Final[int] = 8
_MAX_RETRIES: Final[int] = 5


def _generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))


def normalize_code(raw: str | None) -> str | None:
    """Uppercase + strip whitespace; return None for empty input.

    Does NOT validate the alphabet — callers that need strict validation
    should match against ``^[A-Z0-9]{8}$`` first (the schema regex). This
    helper exists for consistent storage form between
    ``/register`` capture and dashboard lookup.
    """
    if not raw:
        return None
    cleaned = raw.strip().upper()
    return cleaned or None


async def get_or_create_for_user(
    db: AsyncSession, user_id: int
) -> UserInviteCode:
    """Return the user's invite-code row, lazily generating it on first call.

    Concurrent first-access by the same user is safe: the PRIMARY KEY on
    ``user_id`` makes the second INSERT raise ``IntegrityError`` which we
    catch and re-read. Concurrent global collisions on ``code`` retry up
    to ``_MAX_RETRIES`` with a fresh code each time.
    """
    existing = await db.get(UserInviteCode, user_id)
    if existing is not None:
        return existing

    for _ in range(_MAX_RETRIES):
        row = UserInviteCode(user_id=user_id, code=_generate_code())
        db.add(row)
        try:
            await db.commit()
            await db.refresh(row)
            return row
        except IntegrityError:
            await db.rollback()
            # Someone else inserted *our* row → re-read.
            existing = await db.get(UserInviteCode, user_id)
            if existing is not None:
                return existing
            # Otherwise it was a global ``code`` collision → retry.

    raise RuntimeError(
        "invite code generation exhausted retries — alphabet collision?"
    )


async def get_by_code(
    db: AsyncSession, code: str | None
) -> UserInviteCode | None:
    """Look up a code (case-insensitive). Returns None for empty input."""
    normalized = normalize_code(code)
    if normalized is None:
        return None
    return (
        await db.execute(
            select(UserInviteCode).where(UserInviteCode.code == normalized)
        )
    ).scalar_one_or_none()


async def resolve_active_inviter(
    db: AsyncSession, code: str | None
) -> int | None:
    """Return inviter user_id if ``code`` exists and is not disabled.

    Used by registration to validate ``?invite=XXXXXXXX``. Returns None
    on empty input, unknown code, or disabled code — the caller decides
    how to surface the difference (we deliberately don't raise here so
    invalid codes don't block registration).
    """
    row = await get_by_code(db, code)
    if row is None or row.disabled_at is not None:
        return None
    return row.user_id


async def set_disabled(
    db: AsyncSession, user_id: int, disabled: bool
) -> UserInviteCode | None:
    """Admin toggle. Returns the updated row or None if user has no code."""
    from app.core.time import utc_naive_now

    row = await db.get(UserInviteCode, user_id)
    if row is None:
        return None
    row.disabled_at = utc_naive_now() if disabled else None
    await db.commit()
    await db.refresh(row)
    return row
