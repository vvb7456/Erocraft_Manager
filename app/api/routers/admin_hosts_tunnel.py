"""Cloudflare Tunnel admin endpoints, keyed by ``manager_hosts.id``.

Surfaces:

* ``GET    /admin/hosts/{host_id}/tunnel`` — current binding + status
* ``PUT    /admin/hosts/{host_id}/tunnel`` — bind / rebind CF account+zone
* ``POST   /admin/hosts/{host_id}/tunnel/install`` — full install flow
                                                     (CF create + agent install + push + enable)
* ``POST   /admin/hosts/{host_id}/tunnel/sync`` — recompute + push config
* ``POST   /admin/hosts/{host_id}/tunnel/restart`` — agent ``cloudflared.restart``
* ``DELETE /admin/hosts/{host_id}/tunnel`` — uninstall (refuses if any active server tunnels)
* ``POST   /admin/cf/zones`` — list zones for a candidate token (pre-bind UI helper)

See ``docs/CLOUDFLARE_TUNNEL_DESIGN.md`` §6 for the contract.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.manager import (
    ManagerHost,
    ManagerHostTunnel,
    ManagerServerTunnel,
)
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.services import agent_client, host_registry
from app.services.audit import log_manager_activity
from app.services.tunnel_manager import (
    CloudflareAPIError,
    CloudflareAuthError,
    CloudflareRateLimited,
    HostTunnelNotConfigured,
    HostTunnelNotReady,
    TunnelManagerError,
)
from app.services.tunnel_manager import dispatcher as tm_dispatcher
from app.services.tunnel_manager.schemas import (
    HostTunnelBindRequest,
    HostTunnelDetail,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin-hosts-tunnel"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_wings_host(db: AsyncSession, host_id: int) -> ManagerHost:
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if host.kind != host_registry.KIND_WINGS_NODE:
        raise HTTPException(
            status_code=400,
            detail=f"host {host_id} is not a wings_node (kind={host.kind!r})",
        )
    return host


async def _resolve_agent_credentials(
    db: AsyncSession, host: ManagerHost,
) -> tuple[str, str]:
    try:
        return await host_registry.get_credentials(db, host.id)
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _translate_cf_error(exc: CloudflareAPIError) -> HTTPException:
    """Map CF API errors to appropriate HTTP statuses."""
    if isinstance(exc, CloudflareAuthError):
        return HTTPException(status_code=400, detail=f"Cloudflare auth failed: {exc}")
    if isinstance(exc, CloudflareRateLimited):
        return HTTPException(
            status_code=503,
            detail="Cloudflare API rate-limited; please retry in a moment",
        )
    return HTTPException(
        status_code=502, detail=f"Cloudflare API error: {exc}",
    )


async def _server_tunnel_count(db: AsyncSession, host_tunnel_id: int) -> int:
    res = await db.execute(
        select(func.count(ManagerServerTunnel.id)).where(
            ManagerServerTunnel.host_tunnel_id == host_tunnel_id,
        )
    )
    return int(res.scalar() or 0)


async def _serialize_detail(
    db: AsyncSession, ht: ManagerHostTunnel,
    *, host: ManagerHost | None = None,
) -> HostTunnelDetail:
    # Best-effort live probe: ask the agent whether cloudflared is running.
    # 3s timeout; any failure leaves live_* as None + records the reason.
    live_active: bool | None = None
    live_unit_present: bool | None = None
    live_version: str | None = None
    live_error: str | None = None
    if host is not None:
        try:
            endpoint, token = await host_registry.get_credentials(db, host.id)
            resp = await asyncio.wait_for(
                agent_client.cloudflared_status(endpoint, token),
                timeout=3.0,
            )
            if resp.get("ok"):
                out = resp.get("output") or {}
                live_active = bool(out.get("active"))
                live_unit_present = bool(out.get("unit_present"))
                live_version = out.get("version")
            else:
                live_error = resp.get("error") or "agent returned not-ok"
        except (host_registry.AgentNotConfigured, asyncio.TimeoutError) as exc:
            live_error = str(exc) or exc.__class__.__name__
        except Exception as exc:  # noqa: BLE001 — best-effort probe
            live_error = str(exc)[:200]

    return HostTunnelDetail(
        host_id=ht.host_id,
        cf_account_id=ht.cf_account_id,
        cf_zone_id=ht.cf_zone_id,
        cf_zone_name=ht.cf_zone_name,
        cf_tunnel_id=ht.cf_tunnel_id,
        cf_tunnel_name=ht.cf_tunnel_name,
        cloudflared_version=ht.cloudflared_version,
        cf_config_version=ht.cf_config_version,
        last_synced_at=ht.last_synced_at,
        last_error=ht.last_error,
        cloudflared_live_active=live_active,
        cloudflared_live_unit_present=live_unit_present,
        cloudflared_live_version=live_version,
        cloudflared_live_error=live_error,
        server_tunnel_count=await _server_tunnel_count(db, ht.id),
        created_at=ht.created_at,
        updated_at=ht.updated_at,
    )


# ---------------------------------------------------------------------------
# Pre-bind helper: list zones for a candidate token
# ---------------------------------------------------------------------------


class CFZoneListRequest(BaseModel):
    cf_account_id: str = Field(min_length=1, max_length=64)
    cf_api_token: str = Field(min_length=20, max_length=512)


@router.post("/cf/zones")
async def list_cf_zones(
    body: CFZoneListRequest,
    _admin: PteroUser = Depends(require_admin),
) -> dict:
    """Validate a candidate CF token and return the zones it can see.

    Used by the admin UI's bind form before the user picks a zone. We do
    **not** persist anything here — the token is held in memory only.
    """
    try:
        zones = await tm_dispatcher.list_zones_for_token(
            cf_account_id=body.cf_account_id, cf_api_token=body.cf_api_token,
        )
    except CloudflareAPIError as exc:
        raise _translate_cf_error(exc) from exc
    return {"zones": zones}


# ---------------------------------------------------------------------------
# GET / PUT — binding
# ---------------------------------------------------------------------------


@router.get("/hosts/{host_id}/tunnel")
async def get_tunnel(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    host = await _require_wings_host(db, host_id)
    res = await db.execute(
        select(ManagerHostTunnel).where(ManagerHostTunnel.host_id == host.id)
    )
    ht = res.scalar_one_or_none()
    if ht is None:
        return None
    detail = await _serialize_detail(db, ht, host=host)
    return detail.model_dump(mode="json")


@router.put("/hosts/{host_id}/tunnel")
async def bind_tunnel(
    host_id: int,
    body: HostTunnelBindRequest,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    host = await _require_wings_host(db, host_id)
    try:
        ht = await tm_dispatcher.bind_account(
            db, host,
            cf_account_id=body.cf_account_id,
            cf_api_token=body.cf_api_token,
            cf_zone_id=body.cf_zone_id,
            cf_zone_name=body.cf_zone_name,
        )
    except CloudflareAPIError as exc:
        raise _translate_cf_error(exc) from exc

    await log_manager_activity(
        db,
        actor=_admin.username,
        category="tunnel",
        status="success",
        detail_key="tunnel.bind.ok",
        detail_params={
            "host_id": host.id,
            "host_name": host.name,
            "cf_zone_name": ht.cf_zone_name,
        },
    )
    detail = await _serialize_detail(db, ht, host=host)
    return detail.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Install — the orchestrated CF + agent flow
# ---------------------------------------------------------------------------


@router.post("/hosts/{host_id}/tunnel/install")
async def install_tunnel(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full install flow.

    1. CF: create remote-managed tunnel (skipped if already created — idempotent).
    2. DB: persist tunnel_id + secret immediately.
    3. Agent: ``cloudflared.setup`` (verify binary + write systemd unit).
    4. Agent: ``cloudflared.write_config_minimal`` (credentials + minimal config.yml,
       no ingress).
    5. Agent: ``cloudflared.enable`` (``systemctl enable --now``).
    6. CF: PUT initial ingress (rebuilt from current ``manager_server_tunnels``
       — typically empty list at install time).
    7. DB: mark status=ready, persist version + cf_config_version.

    On any agent step failure we mark status=failed but **leave the CF
    tunnel in place** — admin can retry by calling install again, and CF
    creation is skipped on retry.
    """
    host = await _require_wings_host(db, host_id)
    logger.info("tunnel install: host_id=%s starting", host.id)

    # Step 1+2: CF create (idempotent)
    try:
        ht = await tm_dispatcher.install_tunnel(db, host)
        logger.info(
            "tunnel install: host_id=%s step=cf_create cf_tunnel_id=%s",
            host.id, ht.cf_tunnel_id,
        )
    except HostTunnelNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CloudflareAPIError as exc:
        logger.warning("tunnel install: host_id=%s step=cf_create failed: %s", host.id, exc)
        raise _translate_cf_error(exc) from exc

    endpoint, token = await _resolve_agent_credentials(db, host)

    # Step 3: agent install (binary check + systemd unit)
    try:
        install_resp = await agent_client.cloudflared_setup(endpoint, token)
        if not install_resp.get("ok"):
            raise RuntimeError(install_resp.get("error") or "agent install failed")
        version = (install_resp.get("output") or {}).get("version")
        logger.info(
            "tunnel install: host_id=%s step=agent_install version=%s",
            host.id, version,
        )
    except Exception as exc:
        logger.warning("tunnel install: host_id=%s step=agent_install failed: %s", host.id, exc)
        await tm_dispatcher.mark_install_failed(db, ht, f"agent install: {exc}")
        raise HTTPException(
            status_code=502, detail=f"agent cloudflared.setup failed: {exc}",
        ) from exc

    # Step 4: write minimal config (credentials + tunnel_id, no ingress)
    try:
        creds = tm_dispatcher.build_credentials_payload(ht)
        write_resp = await agent_client.cloudflared_write_config_minimal(
            endpoint, token, **creds,
        )
        if not write_resp.get("ok"):
            raise RuntimeError(write_resp.get("error") or "agent write_config_minimal failed")
        logger.info(
            "tunnel install: host_id=%s step=write_config_minimal ok",
            host.id,
        )
    except HostTunnelNotReady as exc:
        logger.warning("tunnel install: host_id=%s step=write_config_minimal not ready: %s", host.id, exc)
        await tm_dispatcher.mark_install_failed(db, ht, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("tunnel install: host_id=%s step=write_config_minimal failed: %s", host.id, exc)
        await tm_dispatcher.mark_install_failed(db, ht, f"agent write_config_minimal: {exc}")
        raise HTTPException(
            status_code=502, detail=f"agent cloudflared.write_config_minimal failed: {exc}",
        ) from exc

    # Step 5: enable + start
    try:
        enable_resp = await agent_client.cloudflared_enable(endpoint, token)
        if not enable_resp.get("ok"):
            raise RuntimeError(enable_resp.get("error") or "agent enable failed")
        logger.info("tunnel install: host_id=%s step=enable ok", host.id)
    except Exception as exc:
        logger.warning("tunnel install: host_id=%s step=enable failed: %s", host.id, exc)
        await tm_dispatcher.mark_install_failed(db, ht, f"agent enable: {exc}")
        raise HTTPException(
            status_code=502, detail=f"agent cloudflared.enable failed: {exc}",
        ) from exc

    # Step 5b: live verification — `systemctl enable --now` rc=0 does NOT
    # prove the service is actually running (start is async; failures show
    # up in `systemctl show ActiveState` after the fact). Wait briefly,
    # then poll agent status. See B2 in CF_TUNNEL_LOGIC_AUDIT.md.
    live_active = False
    live_status: dict[str, object] = {}
    last_err: str = ""
    for _attempt in range(5):  # up to ~5s
        await asyncio.sleep(1.0)
        try:
            status_resp = await agent_client.cloudflared_status(endpoint, token)
        except Exception as exc:  # noqa: BLE001
            last_err = f"agent status read: {exc}"
            continue
        if not status_resp.get("ok"):
            last_err = status_resp.get("error") or "agent status not ok"
            continue
        live_status = status_resp.get("output") or {}
        if live_status.get("active") and live_status.get("unit_present"):
            live_active = True
            break
        last_err = (
            f"cloudflared not active after enable: "
            f"unit_present={live_status.get('unit_present')} "
            f"active={live_status.get('active')} "
            f"sub_state={live_status.get('sub_state')!r}"
        )
    if not live_active:
        logger.warning(
            "tunnel install: host_id=%s step=live_verify failed: %s",
            host.id, last_err,
        )
        await tm_dispatcher.mark_install_failed(db, ht, f"live verify: {last_err}")
        raise HTTPException(
            status_code=502, detail=f"cloudflared did not come up: {last_err}",
        )
    # Prefer live-reported version (more authoritative than the one we
    # captured during the install step).
    live_version = live_status.get("version") or version
    logger.info(
        "tunnel install: host_id=%s step=live_verify ok version=%s sub_state=%s",
        host.id, live_version, live_status.get("sub_state"),
    )

    # Step 6: PUT initial ingress to CF (auto-flips source to cloudflare).
    # This also covers re-install where prior server_tunnels exist.
    try:
        cf_version = await tm_dispatcher.push_remote_ingress(
            db, ht, host_lan_ip=host.hostname,
        )
        logger.info(
            "tunnel install: host_id=%s step=push_ingress cf_version=%s",
            host.id, cf_version,
        )
    except CloudflareAPIError as exc:
        logger.warning("tunnel install: host_id=%s step=push_ingress failed: %s", host.id, exc)
        await tm_dispatcher.mark_install_failed(db, ht, f"push ingress: {exc}")
        raise _translate_cf_error(exc) from exc

    # Step 7: mark complete
    await tm_dispatcher.mark_install_complete(
        db, ht, cloudflared_version=live_version, cf_config_version=cf_version,
    )

    await log_manager_activity(
        db,
        actor=_admin.username,
        category="tunnel",
        status="success",
        detail_key="tunnel.install.ok",
        detail_params={
            "host_id": host.id,
            "host_name": host.name,
            "cf_tunnel_id": ht.cf_tunnel_id,
            "cloudflared_version": live_version,
        },
    )

    detail = await _serialize_detail(db, ht, host=host)
    return detail.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Sync — recompute ingress and push (Phase 2 hook; safe in Phase 1)
# ---------------------------------------------------------------------------


@router.post("/hosts/{host_id}/tunnel/sync")
async def sync_tunnel(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Recompute ingress from current ``manager_server_tunnels`` and PUT to CF.

    **Sync only updates** ``cf_config_version`` + ``last_synced_at``.
    Refusal logic: live-probe cloudflared on the agent; only push if it
    reports ``active`` AND ``unit_present``. Pushing into a non-running
    cloudflared papers over a node-side problem (B1 in
    ``CF_TUNNEL_LOGIC_AUDIT.md``).
    """
    host = await _require_wings_host(db, host_id)
    res = await db.execute(
        select(ManagerHostTunnel).where(ManagerHostTunnel.host_id == host.id)
    )
    ht = res.scalar_one_or_none()
    if ht is None or not ht.cf_tunnel_id:
        raise HTTPException(
            status_code=400, detail="host has no installed tunnel",
        )

    # Live probe — refuse if cloudflared is not running.
    try:
        endpoint, token = await _resolve_agent_credentials(db, host)
        live_resp = await asyncio.wait_for(
            agent_client.cloudflared_status(endpoint, token), timeout=3.0,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail="agent live probe timed out; cannot verify cloudflared state",
        ) from exc
    if not live_resp.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=f"agent probe failed: {live_resp.get('error') or 'unknown'}",
        )
    live_out = live_resp.get("output") or {}
    if not (live_out.get("active") and live_out.get("unit_present")):
        raise HTTPException(
            status_code=409,
            detail=(
                "sync refused: cloudflared is not running on this host "
                f"(active={live_out.get('active')}, "
                f"unit_present={live_out.get('unit_present')}); "
                "run install or fix the node first"
            ),
        )

    try:
        cf_version = await tm_dispatcher.push_remote_ingress(
            db, ht, host_lan_ip=host.hostname,
        )
    except CloudflareAPIError as exc:
        # Push failed — record the error but do NOT change desired status.
        ht.last_error = f"sync: {exc}"[:1024]
        await db.commit()
        raise _translate_cf_error(exc) from exc
    except Exception as exc:
        ht.last_error = f"sync: {exc}"[:1024]
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await log_manager_activity(
        db,
        actor=_admin.username,
        category="tunnel",
        status="success",
        detail_key="tunnel.sync.ok",
        detail_params={
            "host_id": host.id,
            "host_name": host.name,
            "cf_config_version": cf_version,
        },
    )
    detail = await _serialize_detail(db, ht, host=host)
    return detail.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Restart cloudflared
# ---------------------------------------------------------------------------


@router.post("/hosts/{host_id}/tunnel/restart")
async def restart_tunnel(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    host = await _require_wings_host(db, host_id)
    endpoint, token = await _resolve_agent_credentials(db, host)
    resp = await agent_client.cloudflared_restart(endpoint, token)
    if not resp.get("ok"):
        raise HTTPException(
            status_code=502, detail=resp.get("error") or "restart failed",
        )
    await log_manager_activity(
        db,
        actor=_admin.username,
        category="tunnel",
        status="success",
        detail_key="tunnel.restart.ok",
        detail_params={"host_id": host.id, "host_name": host.name},
    )
    return resp.get("output") or {"ok": True}


# ---------------------------------------------------------------------------
# Status (live read from agent)
# ---------------------------------------------------------------------------


@router.get("/hosts/{host_id}/tunnel/status")
async def get_tunnel_status(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Live read of cloudflared service status from the agent."""
    host = await _require_wings_host(db, host_id)
    endpoint, token = await _resolve_agent_credentials(db, host)
    resp = await agent_client.cloudflared_status(endpoint, token)
    if not resp.get("ok"):
        raise HTTPException(
            status_code=502, detail=resp.get("error") or "status read failed",
        )
    return resp.get("output") or {}


# ---------------------------------------------------------------------------
# Server tunnels listing — populates the bottom table on the admin host pane
# ---------------------------------------------------------------------------


@router.get("/hosts/{host_id}/tunnel/servers")
async def list_server_tunnels(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all per-server tunnels bound to this host's tunnel.

    Returns ``{"items": [...]}``. Each row joins ``manager_server_tunnels``
    with ``panel.servers`` so the UI can show the server name + uuid_short
    alongside hostname/upstream/status. Empty list when no host tunnel is
    bound or no server has enabled a custom domain yet.
    """
    host = await _require_wings_host(db, host_id)
    res = await db.execute(
        select(ManagerHostTunnel).where(ManagerHostTunnel.host_id == host.id)
    )
    ht = res.scalar_one_or_none()
    if ht is None:
        return {"items": []}

    rows = await db.execute(
        select(ManagerServerTunnel, PteroServer)
        .join(PteroServer, PteroServer.id == ManagerServerTunnel.server_id, isouter=True)
        .where(ManagerServerTunnel.host_tunnel_id == ht.id)
        .order_by(ManagerServerTunnel.id.asc())
    )
    items: list[dict] = []
    for st, srv in rows.all():
        items.append({
            "id": st.id,
            "server_id": st.server_id,
            "server_name": srv.name if srv is not None else None,
            "server_uuid_short": srv.uuid_short if srv is not None else None,
            "hostname": st.hostname,
            "upstream": f"{st.upstream_scheme}://127.0.0.1:{st.upstream_port}",
            "upstream_port": st.upstream_port,
            "upstream_scheme": st.upstream_scheme,
            "status": st.status,
            "last_error": st.last_error,
            "enabled_at": st.enabled_at.isoformat() + "Z" if st.enabled_at else None,
            "last_synced_at": st.last_synced_at.isoformat() + "Z" if st.last_synced_at else None,
        })
    return {"items": items}


# ---------------------------------------------------------------------------
# DELETE — uninstall
# ---------------------------------------------------------------------------


@router.delete("/hosts/{host_id}/tunnel")
async def uninstall_tunnel(
    host_id: int,
    force: bool = False,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    host = await _require_wings_host(db, host_id)
    res = await db.execute(
        select(ManagerHostTunnel).where(ManagerHostTunnel.host_id == host.id)
    )
    ht = res.scalar_one_or_none()
    if ht is None:
        return {"ok": True, "noop": True}

    # Step 1+2: validate + mark disabling
    try:
        await tm_dispatcher.uninstall_tunnel(db, host, force=force)
    except TunnelManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Step 3: stop cloudflared on agent (best-effort — proceed even on failure)
    agent_ok = True
    agent_error: str | None = None
    try:
        endpoint, token = await _resolve_agent_credentials(db, host)
        resp = await agent_client.cloudflared_uninstall(endpoint, token)
        if not resp.get("ok"):
            agent_ok = False
            agent_error = resp.get("error") or "agent uninstall failed"
    except HTTPException as exc:
        agent_ok = False
        agent_error = str(exc.detail)
    except Exception as exc:
        agent_ok = False
        agent_error = str(exc)
        logger.warning(
            "agent uninstall failed for host %s: %s", host.id, exc,
        )

    # Refresh ht (it was updated by uninstall_tunnel)
    await db.refresh(ht)

    # Step 4+5: delete from CF + DB
    try:
        await tm_dispatcher.finalize_uninstall(db, ht)
    except CloudflareAPIError as exc:
        raise _translate_cf_error(exc) from exc

    await log_manager_activity(
        db,
        actor=_admin.username,
        category="tunnel",
        status="success" if agent_ok else "partial",
        detail_key="tunnel.uninstall.ok",
        detail_params={
            "host_id": host.id,
            "host_name": host.name,
            "agent_ok": agent_ok,
            "agent_error": agent_error,
        },
    )
    return {"ok": True, "agent_ok": agent_ok, "agent_error": agent_error}
