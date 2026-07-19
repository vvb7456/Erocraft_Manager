"""Admin agreement management routes.

Full CRUD for agreement definitions + version publishing. All routes
require admin. See ``docs/USER_AGREEMENT_DESIGN.md`` §4.e.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.time import utc_naive_now
from app.db.models.manager import Agreement, AgreementVersion
from app.db.models.pterodactyl import PteroUser
from app.schemas.agreements import (
    AgreementUpsert,
    AgreementVersionOut,
    PublishVersionRequest,
)
from app.services import agreements as agreements_svc
from app.services.audit import log_manager_activity

router = APIRouter(prefix="/admin/agreements", tags=["agreements"])


@router.get("")
async def agreements_list(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all agreement definitions (including disabled)."""
    rows = (
        await db.execute(
            select(Agreement).order_by(Agreement.sort_order, Agreement.id)
        )
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for agr in rows:
        out.append(await agreements_svc.serialize_admin(db, agr))
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
async def agreements_create(
    payload: AgreementUpsert,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new agreement definition.

    ``slug`` must be unique; it's the public URL key and is immutable
    after creation.
    """
    if payload.scope == "egg" and payload.egg_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="agreements.egg_scope_requires_egg_id",
        )
    existing = (
        await db.execute(select(Agreement).where(Agreement.slug == payload.slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="agreements.slug_conflict"
        )
    agr = Agreement(
        slug=payload.slug,
        scope=payload.scope,
        egg_id=payload.egg_id,
        require_register=payload.require_register,
        require_purchase=payload.require_purchase,
        is_enabled=payload.is_enabled,
        sort_order=payload.sort_order,
        current_version=0,
    )
    db.add(agr)
    await db.flush()
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="settings",
        status="success",
        detail_key="agreement.create",
        detail_params={"slug": agr.slug, "id": agr.id},
    )
    await db.commit()
    return await agreements_svc.serialize_admin(db, agr)


@router.patch("/{agreement_id}")
async def agreements_update(
    agreement_id: int,
    payload: AgreementUpsert,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update an agreement definition's metadata.

    ``slug`` in the payload is ignored (immutable) to avoid breaking
    public URLs and acceptance audit rows that store the slug verbatim.
    """
    agr = (
        await db.execute(
            select(Agreement).where(Agreement.id == agreement_id)
        )
    ).scalar_one_or_none()
    if agr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="agreements.not_found")
    if payload.scope == "egg" and payload.egg_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="agreements.egg_scope_requires_egg_id",
        )
    agr.scope = payload.scope
    agr.egg_id = payload.egg_id
    agr.require_register = payload.require_register
    agr.require_purchase = payload.require_purchase
    agr.is_enabled = payload.is_enabled
    agr.sort_order = payload.sort_order
    await db.flush()
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="settings",
        status="success",
        detail_key="agreement.update",
        detail_params={"slug": agr.slug, "id": agr.id},
    )
    await db.commit()
    return await agreements_svc.serialize_admin(db, agr)


@router.get("/{agreement_id}/versions")
async def versions_list(
    agreement_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AgreementVersionOut]:
    """List all published versions of an agreement, newest first."""
    agr = (
        await db.execute(
            select(Agreement).where(Agreement.id == agreement_id)
        )
    ).scalar_one_or_none()
    if agr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="agreements.not_found")
    rows = (
        await db.execute(
            select(AgreementVersion)
            .where(AgreementVersion.agreement_id == agreement_id)
            .order_by(AgreementVersion.version.desc())
        )
    ).scalars().all()
    return [
        AgreementVersionOut(
            id=int(v.id),
            version=v.version,
            title_zh=v.title_zh,
            title_en=v.title_en,
            body_zh=v.body_zh,
            body_en=v.body_en,
            published_at=(
                v.published_at.isoformat() + "Z"
                if v.published_at is not None
                else ""
            ),
            published_by=v.published_by,
        )
        for v in rows
    ]


@router.post("/{agreement_id}/versions", status_code=status.HTTP_201_CREATED)
async def versions_publish(
    agreement_id: int,
    payload: PublishVersionRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AgreementVersionOut:
    """Publish a new version (bump) or patch the current version's body
    in-place (no bump, no re-consent).

    ``bump=True``  → inserts a new ``AgreementVersion`` row with
    ``version = max+1`` and advances ``Agreement.current_version``,
    triggering re-consent for every existing user.

    ``bump=False`` → overwrites the current version's body; only allowed
    when ``current_version > 0`` (nothing to patch otherwise).
    """
    agr = (
        await db.execute(
            select(Agreement).where(Agreement.id == agreement_id)
        )
    ).scalar_one_or_none()
    if agr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="agreements.not_found")

    now = utc_naive_now()
    actor = current_user.username

    if payload.bump:
        max_ver = (
            await db.execute(
                select(func.max(AgreementVersion.version)).where(
                    AgreementVersion.agreement_id == agreement_id
                )
            )
        ).scalar_one()
        next_ver = int(max_ver or 0) + 1
        ver = AgreementVersion(
            agreement_id=agreement_id,
            version=next_ver,
            title_zh=payload.title_zh,
            title_en=payload.title_en,
            body_zh=payload.body_zh,
            body_en=payload.body_en,
            published_at=now,
            published_by=actor,
        )
        db.add(ver)
        await db.flush()
        agr.current_version = next_ver
        await db.flush()
        await log_manager_activity(
            db,
            actor=actor,
            category="settings",
            status="success",
            detail_key="agreement.publish_bump",
            detail_params={"slug": agr.slug, "id": agr.id, "version": next_ver},
        )
        await db.commit()
        return AgreementVersionOut(
            id=int(ver.id),
            version=ver.version,
            title_zh=ver.title_zh,
            title_en=ver.title_en,
            body_zh=ver.body_zh,
            body_en=ver.body_en,
            published_at=(
                ver.published_at.isoformat() + "Z"
                if ver.published_at is not None
                else ""
            ),
            published_by=ver.published_by,
        )

    # bump=False → patch current version in place
    if agr.current_version <= 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="agreements.no_current_version_to_patch",
        )
    patch_ver = (
        await db.execute(
            select(AgreementVersion).where(
                AgreementVersion.agreement_id == agreement_id,
                AgreementVersion.version == agr.current_version,
            )
        )
    ).scalar_one_or_none()
    if patch_ver is None:
        # orphaned current_version pointer — treat as not found
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="agreements.no_current_version_to_patch",
        )
    patch_ver.title_zh = payload.title_zh
    patch_ver.title_en = payload.title_en
    patch_ver.body_zh = payload.body_zh
    patch_ver.body_en = payload.body_en
    patch_ver.published_at = now
    patch_ver.published_by = actor
    await db.flush()
    await log_manager_activity(
        db,
        actor=actor,
        category="settings",
        status="success",
        detail_key="agreement.publish_patch",
        detail_params={"slug": agr.slug, "id": agr.id, "version": patch_ver.version},
    )
    await db.commit()
    return AgreementVersionOut(
        id=int(patch_ver.id),
        version=patch_ver.version,
        title_zh=patch_ver.title_zh,
        title_en=patch_ver.title_en,
        body_zh=patch_ver.body_zh,
        body_en=patch_ver.body_en,
        published_at=(
            patch_ver.published_at.isoformat() + "Z"
            if patch_ver.published_at is not None
            else ""
        ),
        published_by=patch_ver.published_by,
    )


@router.delete("/{agreement_id}", status_code=status.HTTP_200_OK)
async def agreements_disable(
    agreement_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Soft-delete an agreement (``is_enabled=0``).

    Physical deletion is forbidden to preserve versions/acceptances
    foreign-key semantics + audit history. The agreement stays queryable
    by admins but disappears from public + required lists.
    """
    agr = (
        await db.execute(
            select(Agreement).where(Agreement.id == agreement_id)
        )
    ).scalar_one_or_none()
    if agr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="agreements.not_found")
    agr.is_enabled = False
    await db.flush()
    await log_manager_activity(
        db,
        actor=current_user.username,
        category="settings",
        status="success",
        detail_key="agreement.disable",
        detail_params={"slug": agr.slug, "id": agr.id},
    )
    await db.commit()
    return {"ok": True, "id": agr.id, "is_enabled": False}
