"""User-facing per-server tunnel endpoints.

Surfaces (all under ``/user``):

* ``GET    /user/servers/{server_id}/tunnel`` — current binding + status
* ``POST   /user/servers/{server_id}/tunnel`` — enable (optionally with custom subdomain)
* ``PUT    /user/servers/{server_id}/tunnel`` — change subdomain
* ``DELETE /user/servers/{server_id}/tunnel`` — disable

Each mutating endpoint orchestrates: dispatcher (CF DNS + DB) → push remote
ingress to Cloudflare. cloudflared on each host receives the new config via
long-poll within ~1s and applies it in-process — zero downtime.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.api.deps.ownership import get_owned_server
from app.db.models.manager import ManagerHost, ManagerHostTunnel, ManagerServerTunnel
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.services import host_registry
from app.services.audit import log_manager_activity
from app.services.tunnel_manager import (
    CloudflareAPIError,
    CloudflareAuthError,
    CloudflareRateLimited,
    HostnameConflict,
    HostTunnelNotReady,
    InvalidSubdomain,
)
from app.services.tunnel_manager import dispatcher as tm_dispatcher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user", tags=["user_servers_tunnel"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TunnelEnableRequest(BaseModel):
    customSubdomain: str | None = Field(default=None, max_length=64)


class TunnelChangeRequest(BaseModel):
    customSubdomain: str = Field(min_length=1, max_length=64)


class TunnelInfo(BaseModel):
    status: str
    hostname: str
    customSubdomain: str | None
    lastError: str | None


class TunnelStateResponse(BaseModel):
    tunnel: TunnelInfo | None
    hostTunnelReady: bool
    zoneName: str | None  # for "<input>.<zoneName>" UI hint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_host_for_server(
    db: AsyncSession, server: PteroServer,
) -> ManagerHost | None:
    return await host_registry.get_host_by_node_id(db, server.node_id)


async def _resolve_host_tunnel(
    db: AsyncSession, host: ManagerHost,
) -> ManagerHostTunnel | None:
    res = await db.execute(
        select(ManagerHostTunnel).where(ManagerHostTunnel.host_id == host.id)
    )
    return res.scalar_one_or_none()


def _serialize_tunnel(st: ManagerServerTunnel | None) -> TunnelInfo | None:
    if st is None or st.status == "deleted":
        return None
    return TunnelInfo(
        status=st.status,
        hostname=st.hostname,
        customSubdomain=st.custom_subdomain,
        lastError=st.last_error,
    )


def _translate_cf_error(exc: CloudflareAPIError) -> HTTPException:
    if isinstance(exc, CloudflareAuthError):
        return HTTPException(
            status_code=503,
            detail="tunnel.cf_auth_failed",
        )
    if isinstance(exc, CloudflareRateLimited):
        return HTTPException(
            status_code=503,
            detail="tunnel.cf_rate_limited",
        )
    return HTTPException(
        status_code=502,
        detail="tunnel.cf_api_error",
    )


async def _push_host_ingress(
    db: AsyncSession,
    host: ManagerHost,
    host_tunnel: ManagerHostTunnel,
) -> int:
    """Rebuild ingress + PUT to Cloudflare.

    Returns the new ``cf_config_version``. Raises ``HTTPException`` on failure.

    Note: a server-tunnel push failure does NOT mark the host_tunnel as
    failed (that flag is reserved for the install pipeline). The caller
    is responsible for any per-server rollback (see
    ``rollback_server_tunnel_after_push_failure``).
    """
    try:
        return await tm_dispatcher.push_remote_ingress(
            db, host_tunnel, host_lan_ip=host.hostname,
        )
    except HostTunnelNotReady as exc:
        raise HTTPException(status_code=503, detail="tunnel.host_not_ready") from exc
    except CloudflareAPIError as exc:
        # Record but don't change anything else (host_tunnel state is
        # determined by live agent probe, not by per-server push errors).
        host_tunnel.last_error = f"server tunnel push: {exc}"[:1024]
        await db.commit()
        raise _translate_cf_error(exc) from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/servers/{server_id}/tunnel", response_model=TunnelStateResponse)
async def get_server_tunnel(
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> TunnelStateResponse:
    host = await _resolve_host_for_server(db, server)
    ht = await _resolve_host_tunnel(db, host) if host else None
    st = await tm_dispatcher.get_server_tunnel(db, server.id)
    return TunnelStateResponse(
        tunnel=_serialize_tunnel(st),
        hostTunnelReady=bool(ht and ht.cf_tunnel_id),
        zoneName=ht.cf_zone_name if ht else None,
    )


@router.post("/servers/{server_id}/tunnel", response_model=TunnelStateResponse)
async def enable_server_tunnel(
    body: TunnelEnableRequest,
    server: PteroServer = Depends(get_owned_server),
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TunnelStateResponse:
    host = await _resolve_host_for_server(db, server)
    if host is None:
        raise HTTPException(status_code=400, detail="tunnel.host_not_found")
    ht = await _resolve_host_tunnel(db, host)
    if ht is None or not ht.cf_tunnel_id:
        raise HTTPException(status_code=400, detail="tunnel.host_not_ready")

    if not server.allocation:
        raise HTTPException(status_code=400, detail="tunnel.no_allocation")

    try:
        st = await tm_dispatcher.enable_server_tunnel(
            db,
            server_id=server.id,
            server_uuid_short=server.uuid_short,
            upstream_port=server.allocation.port,
            host_tunnel=ht,
            custom_subdomain=body.customSubdomain,
        )
    except InvalidSubdomain as exc:
        raise HTTPException(status_code=422, detail="tunnel.invalid_subdomain") from exc
    except HostnameConflict as exc:
        raise HTTPException(status_code=409, detail="tunnel.subdomain_taken") from exc
    except HostTunnelNotReady as exc:
        raise HTTPException(status_code=400, detail="tunnel.host_not_ready") from exc
    except CloudflareAPIError as exc:
        raise _translate_cf_error(exc) from exc

    # Push ingress to CF; if push fails, fully roll back the freshly created
    # row + DNS so the user sees a clean state and can retry (B7 in
    # CF_TUNNEL_LOGIC_AUDIT.md). Without this, the row stays in DB as
    # ``active`` but CF has no ingress for it → CF Error 1033.
    try:
        await _push_host_ingress(db, host, ht)
    except HTTPException:
        try:
            await tm_dispatcher.rollback_server_tunnel_after_push_failure(
                db, server_tunnel=st, host_tunnel=ht,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rollback after enable push failure failed for server %s: %s",
                server.id, exc,
            )
        raise
    await db.refresh(st)

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="tunnel",
        status="success",
        detail_key="tunnel.server.enable.ok",
        detail_params={
            "server_id": server.id,
            "server_name": server.name,
            "hostname": st.hostname,
        },
    )

    return TunnelStateResponse(
        tunnel=_serialize_tunnel(st),
        hostTunnelReady=True,
        zoneName=ht.cf_zone_name,
    )


@router.put("/servers/{server_id}/tunnel", response_model=TunnelStateResponse)
async def change_server_tunnel_subdomain(
    body: TunnelChangeRequest,
    server: PteroServer = Depends(get_owned_server),
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TunnelStateResponse:
    host = await _resolve_host_for_server(db, server)
    if host is None:
        raise HTTPException(status_code=400, detail="tunnel.host_not_found")
    ht = await _resolve_host_tunnel(db, host)
    if ht is None or not ht.cf_tunnel_id:
        raise HTTPException(status_code=400, detail="tunnel.host_not_ready")

    st = await tm_dispatcher.get_server_tunnel(db, server.id)
    if st is None or st.status == "deleted":
        raise HTTPException(status_code=404, detail="tunnel.not_enabled")

    try:
        st = await tm_dispatcher.change_server_subdomain(
            db,
            server_tunnel=st,
            host_tunnel=ht,
            new_subdomain=body.customSubdomain,
        )
    except InvalidSubdomain as exc:
        raise HTTPException(status_code=422, detail="tunnel.invalid_subdomain") from exc
    except HostnameConflict as exc:
        raise HTTPException(status_code=409, detail="tunnel.subdomain_taken") from exc
    except HostTunnelNotReady as exc:
        raise HTTPException(status_code=400, detail="tunnel.host_not_ready") from exc
    except CloudflareAPIError as exc:
        raise _translate_cf_error(exc) from exc

    # If push fails after a rename, the new DNS exists but ingress still
    # points at the old hostname → CF Error 1033 on the new hostname.
    # Mark the row as ``failed`` and record the reason so the user/admin
    # can disable + re-enable to recover (B7).
    try:
        await _push_host_ingress(db, host, ht)
    except HTTPException as exc:
        st.status = "failed"
        st.last_error = f"rename push: {exc.detail}"[:1024]
        await db.commit()
        raise
    await db.refresh(st)

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="tunnel",
        status="success",
        detail_key="tunnel.server.rename.ok",
        detail_params={
            "server_id": server.id,
            "server_name": server.name,
            "hostname": st.hostname,
        },
    )

    return TunnelStateResponse(
        tunnel=_serialize_tunnel(st),
        hostTunnelReady=True,
        zoneName=ht.cf_zone_name,
    )


@router.delete(
    "/servers/{server_id}/tunnel", status_code=status.HTTP_204_NO_CONTENT,
)
async def disable_server_tunnel(
    server: PteroServer = Depends(get_owned_server),
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    host = await _resolve_host_for_server(db, server)
    if host is None:
        return None
    ht = await _resolve_host_tunnel(db, host)
    if ht is None:
        return None

    st = await tm_dispatcher.get_server_tunnel(db, server.id)
    if st is None:
        return None

    hostname_for_log = st.hostname
    try:
        await tm_dispatcher.disable_server_tunnel(
            db, server_tunnel=st, host_tunnel=ht,
        )
    except CloudflareAPIError as exc:
        raise _translate_cf_error(exc) from exc

    # Push updated ingress (this server is no longer in it).
    # Best-effort: even if push fails the row is gone, so return 204 anyway
    # but log the failure for the admin.
    try:
        await _push_host_ingress(db, host, ht)
    except HTTPException as exc:
        logger.warning(
            "disable_server_tunnel: agent push failed for host %s server %s: %s",
            host.id, server.id, exc.detail,
        )

    await log_manager_activity(
        db,
        actor=current_user.username,
        category="tunnel",
        status="success",
        detail_key="tunnel.server.disable.ok",
        detail_params={
            "server_id": server.id,
            "server_name": server.name,
            "hostname": hostname_for_log,
        },
    )
    return None
