"""Admin routes for LLM subscription settings.

All LLM-related keys (NewAPI base URL, admin token, ST endpoint URL)
are DB-backed and UI-editable. The admin token is marked
``sensitive=True`` and is masked in responses by the settings store.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import LLM_SPECS, MASKED_SECRET_VALUE, defaults_for
from app.core.settings_store import get_settings_store
from app.db.models.pterodactyl import PteroUser
from app.schemas.settings import SettingsMessageResponse
from app.services.audit import log_manager_activity

router = APIRouter(prefix="/admin/llm", tags=["llm"])


class LlmSettingValue(BaseModel):
    value: Any


class LlmSettingsBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: dict[str, Any]


class LlmSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get("/settings", response_model=LlmSettingsResponse)
async def llm_settings_get(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    store = get_settings_store()
    return await store.get_many(db, defaults_for(LLM_SPECS))


@router.post("/settings", response_model=SettingsMessageResponse)
async def llm_settings_post(
    payload: LlmSettingsBatchRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsMessageResponse:
    if not payload.settings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未提供任何配置项",
        )

    by_category: dict[str, dict[str, Any]] = {}
    for key, value in payload.settings.items():
        spec = LLM_SPECS.get(key)
        if spec is None:
            continue
        if spec.sensitive and isinstance(value, str) and value == MASKED_SECRET_VALUE:
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
    for category, items in by_category.items():
        if items:
            await store.set_values(db, items, category=category)

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="settings",
        status="success",
        detail_key="llm.settings.batch",
        detail_params={
            "keys": ", ".join(sorted(payload.settings.keys())),
            "count": len(payload.settings),
        },
    )
    return SettingsMessageResponse(message="已保存 LLM 配置")


@router.get("/models")
async def llm_models_list(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Proxy: fetch available models from NewAPI for the admin settings form.

    Calls NewAPI's ``/api/channel/models`` (admin endpoint) server-side
    so the browser never talks to NewAPI directly (avoids CORS / 401
    redirect issues).
    """
    import httpx
    from app.core.runtime_settings import LLM_SPECS, defaults_for

    store = get_settings_store()
    settings = await store.get_many(db, defaults_for(LLM_SPECS))
    base_url = str(settings.get("NEWAPI_BASE_URL", "")).rstrip("/")
    admin_token = str(settings.get("NEWAPI_ADMIN_TOKEN", ""))
    if not base_url or not admin_token:
        return {"models": []}

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.get(
                f"{base_url}/api/channel/models_enabled",
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "New-Api-User": "1",
                },
            )
        if resp.status_code >= 400:
            return {"models": []}
        data = resp.json()
        models = data.get("data", [])
        if isinstance(models, list):
            return {"models": [str(m) for m in models]}
        return {"models": []}
    except Exception:
        return {"models": []}


@router.get("/groups")
async def llm_groups_list(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List available NewAPI groups (method 3A: group → model access).

    Used by the plan editor's group dropdown. Returns group names from
    NewAPI's group ratio setting.
    """
    from app.services.llm_provision import newapi_client

    try:
        groups = await newapi_client.list_groups(db)
        return {"groups": groups}
    except Exception:
        return {"groups": []}
