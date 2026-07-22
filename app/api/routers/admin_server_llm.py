"""Admin routes for per-server LLM key management.

Lets admins inspect and manage a specific server's LLM subscription:
view real-time subscription usage, reset usage (rebind subscription),
enable / disable the token, and revoke (delete the NewAPI user).

Quota is controlled entirely by the NewAPI subscription — there is no
per-token remain_quota adjustment. Model access is determined by the
user's group (set by the plan's UpgradeGroup).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import LLM_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import to_iso_z
from app.db.models.manager import ServerLlmKey, ServerMeta
from app.db.models.billing import BillingPlan
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.services.llm_provision import newapi_client, provision as llm_provision

router = APIRouter(prefix="/admin/servers", tags=["admin-server-llm"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class AdminLlmUsageResponse(_Camel):
    provisioned: bool
    status: str | None = None
    tokenId: int | None = None
    userId: int | None = None
    apiKey: str | None = None
    apiBaseUrl: str = ""
    # Subscription quota fields (from NewAPI subscription)
    quotaGrant: int = 0
    quotaUsed: int = 0
    quotaAvailable: int = 0
    nextResetAt: str | None = None
    newapiPlanId: int | None = None
    newapiSubscriptionId: int | None = None
    lastSyncedAt: str | None = None
    createdAt: str | None = None
    usageQueryFailed: bool = False


class SetStatusRequest(_Camel):
    enabled: bool


class MessageResponse(_Camel):
    message: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


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
    endpoint_url = (
        str(settings.get("LLM_ST_ENDPOINT_URL", "")).rstrip("/")
        or f"{base_url}/v1"
    )

    quota_grant = 0
    quota_used = 0
    quota_available = 0
    next_reset_at: str | None = None
    usage_failed = False

    # Read subscription data via admin token
    try:
        subs = await newapi_client.get_user_subscriptions(db, row.newapi_user_id)
        for item in subs:
            sub = item.get("subscription", {}) if isinstance(item, dict) else {}
            if sub.get("status") == "active":
                quota_grant = int(sub.get("amount_total", 0))
                quota_used = int(sub.get("amount_used", 0))
                quota_available = max(0, quota_grant - quota_used)
                next_reset_ts = int(sub.get("next_reset_time", 0) or 0)
                if next_reset_ts > 0:
                    from datetime import datetime, UTC
                    next_reset_at = to_iso_z(
                        datetime.fromtimestamp(next_reset_ts, tz=UTC).replace(tzinfo=None)
                    )
                break
    except Exception:
        usage_failed = True

    return AdminLlmUsageResponse(
        provisioned=True,
        status=row.status,
        tokenId=row.newapi_token_id,
        userId=row.user_id,
        apiKey=row.api_key,
        apiBaseUrl=endpoint_url,
        quotaGrant=quota_grant,
        quotaUsed=quota_used,
        quotaAvailable=quota_available,
        nextResetAt=next_reset_at,
        newapiPlanId=row.newapi_plan_id,
        newapiSubscriptionId=row.newapi_subscription_id,
        lastSyncedAt=to_iso_z(row.last_synced_at),
        createdAt=to_iso_z(row.created_at),
        usageQueryFailed=usage_failed,
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get("/{server_id}/llm/provisioned")
async def get_server_llm_provisioned(
    server_id: int,
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Lightweight check — only queries local DB, no NewAPI call.

    Used by the admin server detail page to enable/disable the LLM tab
    without waiting for a ~2s NewAPI subscription query.
    """
    row = await db.get(ServerLlmKey, server_id)
    return {"provisioned": row is not None}


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


@router.post("/{server_id}/llm/provision", response_model=AdminLlmUsageResponse)
async def provision_server_llm(
    server_id: int,
    current_user: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLlmUsageResponse:
    server = await _ensure_server(db, server_id)
    meta = await db.get(ServerMeta, server_id)
    if meta is None or meta.plan_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="该服务器未绑定套餐，无法开通 LLM 额度",
        )
    plan = await db.get(BillingPlan, meta.plan_id)
    if plan is None or not plan.llm_enabled or plan.llm_quota_grant <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="该服务器绑定的套餐未启用 LLM 额度",
        )
    existing = await db.get(ServerLlmKey, server_id)
    if existing is not None and existing.status == "active":
        return await _serialize(db, existing)
    snapshot = {
        "llm_enabled": True,
        "llm_quota_grant": plan.llm_quota_grant,
        "newapi_plan_id": plan.newapi_plan_id,
        "llm_group": plan.llm_group,
    }
    try:
        row = await llm_provision.provision_for_server(
            db, server_id, server.owner_id, snapshot
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM 开通失败: {exc}",
        ) from exc
    if row is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LLM 全局开关未开启或套餐未配置 LLM 额度",
        )
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
