"""Admin routes for DB-backed runtime settings."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import (
    AUTOMATION_SPECS,
    MONITORING_SPECS,
    SETTINGS_SPECS,
    defaults_for,
)
from app.core.settings_store import get_settings_store
from app.db.models.pterodactyl import PteroUser
from app.schemas.settings import SettingsMessageResponse
from app.services.audit import log_manager_activity

router = APIRouter(tags=["settings"])


async def _save_settings(
    db: AsyncSession,
    specs: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    store = get_settings_store()
    values_by_category: dict[str, dict[str, Any]] = defaultdict(dict)

    for key, spec in specs.items():
        if key not in payload:
            continue
        incoming = payload[key]
        try:
            normalized = spec.normalize(incoming)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        values_by_category[spec.category][key] = normalized

    if not values_by_category:
        return

    for category, values in values_by_category.items():
        await store.set_values(db, values, category=category, commit=False)
    await db.commit()


@router.get("/settings")
async def settings_get(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    store = get_settings_store()
    return await store.get_many(db, defaults_for(SETTINGS_SPECS))


@router.post("/settings", response_model=SettingsMessageResponse)
async def settings_save(
    request: Request,
    payload: dict[str, Any],
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsMessageResponse:
    await _save_settings(db, SETTINGS_SPECS, payload)
    await log_manager_activity(
        db,
        actor=current_user.username,
        action="settings",
        status="success",
        detail_key="settings_change",
        detail_params={"actor": current_user.username},
    )
    return SettingsMessageResponse(message="设置已保存")


@router.get("/automation")
async def automation_get(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    store = get_settings_store()
    return await store.get_many(db, defaults_for(AUTOMATION_SPECS))


@router.post("/automation", response_model=SettingsMessageResponse)
async def automation_save(
    request: Request,
    payload: dict[str, Any],
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsMessageResponse:
    await _save_settings(db, AUTOMATION_SPECS, payload)
    await log_manager_activity(
        db,
        actor=current_user.username,
        action="settings",
        status="success",
        detail_key="automation_settings_change",
        detail_params={"actor": current_user.username},
    )
    return SettingsMessageResponse(message="自动化设置已保存。")


@router.get("/monitoring-settings")
async def monitoring_settings_get(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    store = get_settings_store()
    return await store.get_many(db, defaults_for(MONITORING_SPECS))


@router.post("/monitoring-settings", response_model=SettingsMessageResponse)
async def monitoring_settings_save(
    request: Request,
    payload: dict[str, Any],
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsMessageResponse:
    await _save_settings(db, MONITORING_SPECS, payload)
    await log_manager_activity(
        db,
        actor=current_user.username,
        action="settings",
        status="success",
        detail_key="monitoring_settings_change",
        detail_params={"actor": current_user.username},
    )
    return SettingsMessageResponse(message="监控设置已保存。")
