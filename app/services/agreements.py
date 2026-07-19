"""User-agreement service: list, validate, record acceptances.

See ``docs/USER_AGREEMENT_DESIGN.md`` §4.3 for the contract.

Scope rules:

* ``context='register'`` → only ``require_register`` global agreements.
* ``context='purchase'`` → ``require_purchase`` agreements filtered by
  the plan's ``egg_id`` (``scope='global'`` always included,
  ``scope='egg'`` only when ``egg_id`` matches).
* ``context='reconsent'`` → same as ``register`` (egg-scoped AUP never
  enters the login gate; it's enforced at next purchase).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.manager import (
    Agreement,
    AgreementVersion,
    UserAgreementAcceptance,
)
from app.schemas.agreements import AcceptanceItem, AgreementPublicOut

logger = logging.getLogger(__name__)


class AgreementError(Exception):
    """Raised when acceptance validation fails (missing / version mismatch).

    The router surfaces this as HTTP 400 with the i18n detail key
    ``register.agreement_required``.
    """


def _pick_locale(zh: str, en: str, locale: str | None) -> str:
    """Return the value for the requested locale, falling back to the other
    language when the requested one is blank. 'zh*' selects Chinese,
    everything else selects English."""
    want_zh = (locale or "zh").lower().startswith("zh")
    if want_zh:
        return zh if (zh and zh.strip()) else (en or "")
    return en if (en and en.strip()) else (zh or "")


async def list_required(
    db: AsyncSession,
    *,
    context: str,
    egg_id: int | None = None,
) -> list[Agreement]:
    """Return the agreements a user must consent to in this context.

    Filters: ``is_enabled=1``, ``current_version > 0``, and the
    appropriate require-flag for the context. For ``context='purchase'``
    egg-scoped AUP agreements are additionally filtered by ``egg_id``.
    """
    base = select(Agreement).where(
        Agreement.is_enabled.is_(True),
        Agreement.current_version > 0,
    )
    if context == "register" or context == "reconsent":
        base = base.where(Agreement.require_register.is_(True))
    elif context == "purchase":
        base = base.where(Agreement.require_purchase.is_(True))
        if egg_id is not None:
            # global agreements + egg-scoped matching the plan's egg_id
            base = base.where(
                (Agreement.scope == "global")
                | (
                    (Agreement.scope == "egg")
                    & (Agreement.egg_id == egg_id)
                )
            )
        else:
            base = base.where(Agreement.scope == "global")
    else:
        raise ValueError(f"unknown context {context!r}")

    result = await db.execute(base.order_by(Agreement.sort_order, Agreement.id))
    return list(result.scalars().all())


async def public_view(
    db: AsyncSession, slug: str, locale: str | None
) -> AgreementPublicOut | None:
    """Return the current version body for public display.

    Returns ``None`` when the agreement doesn't exist, is disabled, or
    has no published version (``current_version == 0``).
    """
    agr = (
        await db.execute(
            select(Agreement).where(
                Agreement.slug == slug,
                Agreement.is_enabled.is_(True),
                Agreement.current_version > 0,
            )
        )
    ).scalar_one_or_none()
    if agr is None:
        return None
    ver = (
        await db.execute(
            select(AgreementVersion).where(
                AgreementVersion.agreement_id == agr.id,
                AgreementVersion.version == agr.current_version,
            )
        )
    ).scalar_one_or_none()
    if ver is None:
        return None
    title = _pick_locale(ver.title_zh, ver.title_en, locale)
    body = _pick_locale(ver.body_zh, ver.body_en, locale)
    return AgreementPublicOut(
        agreement_id=agr.id,
        slug=agr.slug,
        scope=agr.scope,
        version=ver.version,
        title=title,
        body_md=body,
    )


async def _current_version_map(
    db: AsyncSession, agreement_ids: list[int]
) -> dict[int, int]:
    """Return ``{agreement_id: current_version}`` for the given ids."""
    if not agreement_ids:
        return {}
    rows = (
        await db.execute(
            select(Agreement.id, Agreement.current_version).where(
                Agreement.id.in_(agreement_ids)
            )
        )
    ).all()
    return {int(row[0]): int(row[1]) for row in rows}


async def validate_acceptance(
    db: AsyncSession,
    items: list[AcceptanceItem],
    *,
    context: str,
    egg_id: int | None = None,
) -> list[AcceptanceItem]:
    """Validate that every required agreement appears in ``items`` with the
    current version.

    Raises :class:`AgreementError` on missing agreement or version
    mismatch (stale / tampered). Returns the *canonical* validated set —
    one item per required agreement, built from the server's own
    ``agreement_id``/``current_version``. Client-supplied extras or junk
    ids are dropped rather than forwarded, so :func:`record` never
    materializes an acceptance row for an agreement that isn't actually
    required in this context. When nothing is required, returns ``[]``.
    """
    required = await list_required(db, context=context, egg_id=egg_id)
    if not required:
        return []
    current = await _current_version_map(
        db, [a.id for a in required]
    )
    by_id = {item.agreement_id: item for item in items}
    validated: list[AcceptanceItem] = []
    for agr in required:
        item = by_id.get(agr.id)
        if item is None:
            raise AgreementError(
                f"missing acceptance for agreement {agr.slug!r}"
            )
        cur = current.get(agr.id, 0)
        if item.version != cur:
            raise AgreementError(
                f"version mismatch for {agr.slug!r}: "
                f"got {item.version}, expected {cur}"
            )
        validated.append(AcceptanceItem(agreement_id=agr.id, version=cur))
    return validated


async def record(
    db: AsyncSession,
    user_id: int,
    items: list[AcceptanceItem],
    *,
    context: str,
    ip: str | None,
    order_id: int | None = None,
    locale: str | None,
    commit: bool = True,
) -> int:
    """Persist acceptance rows.

    Idempotent: the ``UNIQUE(user_id, agreement_id, version)`` constraint
    makes repeat submissions for the same version a no-op. Missing /
    mismatched versions must have been validated beforehand by
    :func:`validate_acceptance`; this function does not re-check.

    Returns the number of new rows actually inserted (0 if all were
    duplicates). ``commit=False`` lets the caller batch this inside a
    larger transaction (e.g. user creation).
    """
    if not items:
        return 0
    inserted = 0
    now = utc_naive_now()
    # Resolve slug per agreement_id for the redundant slug column
    ids = [item.agreement_id for item in items]
    rows = (
        await db.execute(
            select(Agreement.id, Agreement.slug).where(Agreement.id.in_(ids))
        )
    ).all()
    slug_map = {int(row[0]): str(row[1]) for row in rows}

    for item in items:
        slug = slug_map.get(item.agreement_id, "")
        # Idempotent INSERT: skip when the (user, agreement, version) row
        # already exists. SELECT first is cheaper than catching IntegrityError
        # per-row and keeps the audit log free of duplicate-near-miss noise.
        exists = (
            await db.execute(
                select(UserAgreementAcceptance.id).where(
                    UserAgreementAcceptance.user_id == user_id,
                    UserAgreementAcceptance.agreement_id == item.agreement_id,
                    UserAgreementAcceptance.version == item.version,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        db.add(
            UserAgreementAcceptance(
                user_id=user_id,
                agreement_id=item.agreement_id,
                slug=slug,
                version=item.version,
                context=context,
                order_id=order_id,
                locale=locale,
                ip=ip,
                accepted_at=now,
            )
        )
        inserted += 1
    if commit:
        await db.commit()
    return inserted


async def pending_for_user(
    db: AsyncSession, user_id: int
) -> list[Agreement]:
    """Return ``require_register`` agreements the user hasn't yet
    consented to at the current version.

    NOTE: currently unwired. The login re-consent gate (front-end modal +
    a ``POST`` acceptance endpoint for logged-in users) is deferred to a
    later phase; this function is the ready-made detection seam for it.
    It is intentionally NOT called from the hot ``/me`` path — doing so
    added two DB queries per request for a value nothing consumed yet.

    Egg-scoped AUP agreements are deliberately excluded — they are
    enforced at purchase time so users don't see agreements for
    containers they may never buy.
    """
    required = await list_required(db, context="reconsent")
    if not required:
        return []
    required_ids = [a.id for a in required]
    # Find (agreement_id, version) pairs the user has already accepted at
    # the current version
    accepted = (
        await db.execute(
            select(
                UserAgreementAcceptance.agreement_id,
                UserAgreementAcceptance.version,
            ).where(
                UserAgreementAcceptance.user_id == user_id,
                UserAgreementAcceptance.agreement_id.in_(required_ids),
            )
        )
    ).all()
    accepted_map: dict[int, int] = {}
    for row in accepted:
        aid = int(row[0])
        ver = int(row[1])
        # keep the highest accepted version per agreement
        if aid not in accepted_map or ver > accepted_map[aid]:
            accepted_map[aid] = ver
    out = [
        a for a in required
        if accepted_map.get(a.id, 0) < a.current_version
    ]
    return out


async def serialize_public(
    db: AsyncSession,
    agreement: Agreement,
    locale: str | None,
) -> AgreementPublicOut:
    """Resolve a single Agreement into its public view (used by the
    pending endpoint — the list view already returned by
    :func:`list_required` is just the model rows; this loads the version
    body for display).
    """
    ver = (
        await db.execute(
            select(AgreementVersion).where(
                AgreementVersion.agreement_id == agreement.id,
                AgreementVersion.version == agreement.current_version,
            )
        )
    ).scalar_one_or_none()
    if ver is None:
        return AgreementPublicOut(
            agreement_id=agreement.id,
            slug=agreement.slug,
            scope=agreement.scope,
            version=agreement.current_version,
            title="",
            body_md="",
        )
    title = _pick_locale(ver.title_zh, ver.title_en, locale)
    body = _pick_locale(ver.body_zh, ver.body_en, locale)
    return AgreementPublicOut(
        agreement_id=agreement.id,
        slug=agreement.slug,
        scope=agreement.scope,
        version=ver.version,
        title=title,
        body_md=body,
    )


async def serialize_admin(
    db: AsyncSession, agreement: Agreement
) -> dict[str, Any]:
    """Serialize an Agreement row for the admin list endpoint."""
    version_count = (
        await db.execute(
            select(func.count(AgreementVersion.id)).where(
                AgreementVersion.agreement_id == agreement.id
            )
        )
    ).scalar_one()
    # Resolve the current version's titles so the admin list can show a
    # human-readable document name alongside the slug. Empty strings when
    # there is no published version yet (current_version == 0) or the row
    # is missing (orphaned pointer).
    current_title_zh = ""
    current_title_en = ""
    if agreement.current_version > 0:
        cur_ver = (
            await db.execute(
                select(
                    AgreementVersion.title_zh,
                    AgreementVersion.title_en,
                ).where(
                    AgreementVersion.agreement_id == agreement.id,
                    AgreementVersion.version == agreement.current_version,
                )
            )
        ).one_or_none()
        if cur_ver is not None:
            current_title_zh = cur_ver.title_zh or ""
            current_title_en = cur_ver.title_en or ""
    created_at = agreement.created_at
    updated_at = agreement.updated_at
    return {
        "id": agreement.id,
        "slug": agreement.slug,
        "scope": agreement.scope,
        "egg_id": agreement.egg_id,
        "require_register": agreement.require_register,
        "require_purchase": agreement.require_purchase,
        "is_enabled": agreement.is_enabled,
        "sort_order": agreement.sort_order,
        "current_version": agreement.current_version,
        "version_count": int(version_count or 0),
        "current_title_zh": current_title_zh,
        "current_title_en": current_title_en,
        "created_at": (
            created_at.isoformat() + "Z" if created_at is not None else ""
        ),
        "updated_at": (
            updated_at.isoformat() + "Z" if updated_at is not None else ""
        ),
    }
