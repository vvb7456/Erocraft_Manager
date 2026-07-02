"""Admin routes for per-server LLM key management.

Lets admins inspect and manage a specific server's free-LLM-quota key:
view real-time usage, adjust quota / allowed models, reset (regenerate)
the key, enable / disable it, refill the monthly quota, and revoke it.

Manual provisioning is intentionally not exposed — keys are provisioned
automatically on order apply; servers without a key simply show a disabled
tab in the admin UI.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import LLM_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import to_iso_z
from app.db.models.manager import ServerLlmKey
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.services.llm_provision import newapi_client, provision as llm_provision
from app.services.llm_provision.helpers import next_reset_date

router = APIRouter(prefix="/admin/servers", tags=["admin-server-llm"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class AdminLlmUsageResponse(_Camel):
    provisioned: bool
    status: str | None = None
    tokenId: int | None = Field(default=None)
    userId: int | None = Field(default=None)
    apiKey: str | None = Field(default=None)
    apiBaseUrl: str = ""
    quotaGrant: int = 0
    quotaUsed: int = 0
    quotaAvailable: int = 0
    allowedModels: list[str] | None = None
    resetDay: int | None = Field(default=None)
    nextResetAt: str | None = Field(default=None)
    lastResetAt: str | None = Field(default=None)
    lastSyncedAt: str | None = Field(default=None)
    createdAt: str | None = Field(default=None)
    usageQueryFailed: bool = False


class UpdateLlmKeyRequest(_Camel):
    quotaGrant: int | None = Field(default=None, ge=0)
    # None = unchanged; [] or "" = allow all models; list = whitelist
    allowedModels: list[str] | None = None


class SetStatusRequest(_Camel):
    enabled: bool


class MessageResponse(_Camel):
    message: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _allowed_models(row: ServerLlmKey) -> list[str] | None:
    if not row.model_limits:
        return None
    return [m.strip() for m in row.model_limits.split(",") if m.strip()]


async def _ensure_server(db: AsyncSession, server_id: int) -> PteroServer:
    server = await db.get(PteroServer, server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="服务器不存在")
    return server


def _admin_error(exc: llm_provision.LlmAdminError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))


async def _serialize(db: AsyncSession, row: ServerLlmKey) -> AdminLlmUsageResponse:
    settings = await get_settings_store().get_many(db, defaults_for(LLM_SPECS))
    base_url = str(settings.get("NEWAPI_BASE_URL", "")).rstrip("/")
    endpoint_url = str(settings.get("LLM_ST_ENDPOINT_URL", "")).rstrip("/") or f"{base_url}/v1"

    quota_used = 0
    quota_available = 0
    usage_failed = False
    if base_url:
        try:
            usage = await newapi_client.get_token_usage(row.api_key, base_url)
            quota_used = int(usage.get("total_used", 0))
            quota_available = int(usage.get("total_available", 0))
        except Exception:  # noqa: BLE001
            usage_failed = True
            quota_used = row.quota_used
            quota_available = row.quota_available

    return AdminLlmUsageResponse(
        provisioned=True,
        status=row.status,
        tokenId=row.newapi_token_id,
        userId=row.user_id,
        apiKey=row.api_key,
        apiBaseUrl=endpoint_url,
        quotaGrant=row.quota_grant,
        quotaUsed=quota_used,
        quotaAvailable=quota_available,
        allowedModels=_allowed_models(row),
        resetDay=row.reset_day,
        nextResetAt=next_reset_date(row),
        lastResetAt=to_iso_z(row.last_reset_at),
        lastSyncedAt=to_iso_z(row.last_synced_at),
        createdAt=to_iso_z(row.created_at),
        usageQueryFailed=usage_failed,
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get("/{server_id}/llm", response_model=AdminLlmUsageResponse)
async def get_server_llm(
    server_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLlmUsageResponse:
    await _ensure_server(db, server_id)
    row = await db.get(ServerLlmKey, server_id)
    if row is None:
        return AdminLlmUsageResponse(provisioned=False)
    return await _serialize(db, row)


@router.patch("/{server_id}/llm", response_model=AdminLlmUsageResponse)
async def update_server_llm(
    server_id: int,
    payload: UpdateLlmKeyRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLlmUsageResponse:
    await _ensure_server(db, server_id)
    # Translate allowedModels list -> comma string sentinel for the service.
    #   payload.allowedModels is None      -> leave unchanged
    #   payload.allowedModels is [] / list -> "" (all) or "a,b"
    model_limits: str | None
    if "allowedModels" not in payload.model_fields_set:
        model_limits = None
    else:
        model_limits = ",".join(payload.allowedModels or [])
    try:
        row = await llm_provision.admin_update_key(
            db, server_id,
            quota_grant=payload.quotaGrant,
            model_limits=model_limits,
            actor=current_user.username,
        )
    except llm_provision.LlmAdminError as exc:
        raise _admin_error(exc) from exc
    return await _serialize(db, row)


@router.post("/{server_id}/llm/reset", response_model=AdminLlmUsageResponse)
async def reset_server_llm_key(
    server_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLlmUsageResponse:
    await _ensure_server(db, server_id)
    try:
        row = await llm_provision.admin_reset_key(db, server_id, actor=current_user.username)
    except llm_provision.LlmAdminError as exc:
        raise _admin_error(exc) from exc
    return await _serialize(db, row)


@router.post("/{server_id}/llm/status", response_model=AdminLlmUsageResponse)
async def set_server_llm_status(
    server_id: int,
    payload: SetStatusRequest,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLlmUsageResponse:
    await _ensure_server(db, server_id)
    try:
        row = await llm_provision.admin_set_status(
            db, server_id, enabled=payload.enabled, actor=current_user.username,
        )
    except llm_provision.LlmAdminError as exc:
        raise _admin_error(exc) from exc
    return await _serialize(db, row)


@router.post("/{server_id}/llm/reset-usage", response_model=AdminLlmUsageResponse)
async def reset_server_llm_usage(
    server_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLlmUsageResponse:
    await _ensure_server(db, server_id)
    try:
        row = await llm_provision.admin_reset_usage(db, server_id, actor=current_user.username)
    except llm_provision.LlmAdminError as exc:
        raise _admin_error(exc) from exc
    return await _serialize(db, row)


@router.post("/{server_id}/llm/revoke", response_model=MessageResponse)
async def revoke_server_llm_key(
    server_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await _ensure_server(db, server_id)
    try:
        await llm_provision.admin_revoke(db, server_id, actor=current_user.username)
    except llm_provision.LlmAdminError as exc:
        raise _admin_error(exc) from exc
    return MessageResponse(message="已吊销该服务器的 LLM 额度")
