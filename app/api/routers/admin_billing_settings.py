"""Admin routes for billing runtime settings.

All billing-related keys (gateway credentials, gateway display names, gateway
URLs, billing quotas, refund policy) are now B-class (DB-backed, UI-editable).
Sensitive keys (e.g. ``HUPIJIAO_APPSECRET``) are marked ``sensitive=True`` on
their :class:`SettingSpec` and are encrypted at rest.
"""

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
        spec = BILLING_SPECS.get(key)
        if spec is None:
            # Silently ignore unknown keys (e.g. removed/legacy settings still
            # held in stale frontend state). Avoids 404 storms after spec changes.
            continue
        try:
            normalized = spec.normalize(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}: {exc}",
            ) from exc
        by_category.setdefault(spec.category, {})[key] = normalized

    store = get_settings_store()
    candidate = await store.get_many(db, defaults_for(BILLING_SPECS))
    candidate.update(by_category.get("billing", {}))
    if candidate.get("WECHAT_PAY_ENABLED"):
        from app.services.billing.gateway.wechat_pay import WechatPayGateway

        try:
            WechatPayGateway.from_settings(candidate)
            if not candidate.get("WECHAT_PAY_APP_SECRET"):
                raise ValueError("请填写服务号AppSecret")
            if bool(candidate.get("WECHAT_PAY_MINIPROGRAM_APPID")) != bool(candidate.get("WECHAT_PAY_MINIPROGRAM_APP_SECRET")):
                raise ValueError("小程序AppID和AppSecret必须同时填写")
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, f"微信支付配置错误：{exc}") from exc
    for category, items in by_category.items():
        if items:
            await store.set_values(db, items, category=category)

    # Rebuild gateway registry so credential / enabled / display_name changes
    # take effect immediately for the next request.
    from app.services.billing.gateway import registry as gateway_registry
    await gateway_registry.ensure_loaded(db, force=True)

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="billing",
        status="success",
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
