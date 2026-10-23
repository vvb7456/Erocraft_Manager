"""管理网关接入、小程序登录及计费业务配置。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import BILLING_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.db.models.pterodactyl import PteroUser
from app.schemas.settings import SettingsMessageResponse
from app.services.audit import log_manager_activity
from app.core.contracts import OperationResult

router = APIRouter(prefix="/admin/billing", tags=["billing"])


class BillingSettingValue(BaseModel):
    value: Any


class BillingSettingsBatchRequest(BaseModel):
    """Batch update payload — partial updates are allowed."""

    model_config = ConfigDict(extra="forbid")
    settings: dict[str, Any]


class BillingSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get("/settings", response_model=BillingSettingsResponse)
async def billing_settings_get(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    store = get_settings_store()
    return await store.get_many(db, defaults_for(BILLING_SPECS))


@router.post("/settings", response_model=SettingsMessageResponse)
async def billing_settings_post(
    payload: BillingSettingsBatchRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsMessageResponse:
    """Batch update billing settings — only keys present in payload are updated."""
    if not payload.settings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未提供任何配置项",
        )

    by_category: dict[str, dict[str, Any]] = {}
    for key, value in payload.settings.items():
        spec = BILLING_SPECS[key]
        try:
            normalized = spec.normalize(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}: {exc}",
            ) from exc
        by_category.setdefault(spec.category, {})[key] = normalized

    store = get_settings_store()
    for category, items in by_category.items():
        if items:
            await store.set_values(db, items, category=category)

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="billing",
        operation=OperationResult(action="billing.settings.update", phase="execution", outcome="success"),
        detail_key="billing.settings.batch",
        detail_params={
            "keys": ", ".join(sorted(payload.settings.keys())),
            "count": len(payload.settings),
        },
    )
    return SettingsMessageResponse(message="已保存计费配置")


@router.put("/settings/{key}", response_model=SettingsMessageResponse)
async def billing_setting_put(
    key: str,
    payload: BillingSettingValue,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsMessageResponse:
    """Update one billing setting (legacy single-key endpoint, kept for compat)."""
    spec = BILLING_SPECS.get(key)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知的计费配置项: {key}",
        )
    return await billing_settings_post(
        BillingSettingsBatchRequest(settings={key: payload.value}), current_user, db,
    )
