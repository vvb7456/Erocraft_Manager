"""Wings-node specific admin endpoints, keyed by ``manager_hosts.id``.

Replaces the legacy ``/admin/nodes/{node_id}/...`` surface. Every route
here resolves a ``host_id`` to its bound ``panel.nodes`` row via
``host.pterodactyl_node_id`` and then talks to wings / agent the same
way the old admin_nodes.py module did.

Routes that *don't* logically need a panel node (e.g. generic agent
status / metrics on non-wings hosts) live in :mod:`admin_hosts` instead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.manager import ManagerHost
from app.db.models.pterodactyl import PanelNode, PteroUser
from app.services import agent_client, host_registry, wings_config
from app.services.audit import log_manager_activity
from app.services.metrics_builder import build_metrics_row
from app.services.wings import WingsServiceError, wings_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/hosts", tags=["admin-hosts-wings"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_wings_host(
    db: AsyncSession, host_id: int,
) -> tuple[ManagerHost, PanelNode]:
    """Resolve ``host_id`` to a wings_node host **and** its bound panel node.

    Raises 404 when the host doesn't exist, 400 when the host is not a
    wings_node or has no ``pterodactyl_node_id`` binding, or when the
    underlying panel node has been deleted out from under us.
    """
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        ) from exc
    if host.kind != host_registry.KIND_WINGS_NODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"host {host_id} is not a wings_node (kind={host.kind!r})",
        )
    if host.pterodactyl_node_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"host {host_id} has no pterodactyl_node_id binding",
        )
    node = await db.get(PanelNode, host.pterodactyl_node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"host {host_id} references panel node "
                f"{host.pterodactyl_node_id}, which no longer exists"
            ),
        )
    return host, node


async def _resolve_credentials(
    db: AsyncSession, host: ManagerHost,
) -> tuple[str, str]:
    try:
        return await host_registry.get_credentials(db, host.id)
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# Live agent ops
# ---------------------------------------------------------------------------


@router.get("/{host_id}/agent/metrics")
async def get_agent_metrics(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    host, _node = await _require_wings_host(db, host_id)
    endpoint, token = await _resolve_credentials(db, host)
    try:
        return await agent_client.fetch_metrics(endpoint, token, timeout=10.0)
    except agent_client.AgentClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc),
        ) from exc


@router.get("/{host_id}/agent/wings-config")
async def get_agent_wings_config(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    host, _node = await _require_wings_host(db, host_id)
    endpoint, token = await _resolve_credentials(db, host)
    try:
        return await agent_client.fetch_wings_config(endpoint, token, timeout=8.0)
    except agent_client.AgentClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc),
        ) from exc


@router.post("/{host_id}/agent/refresh")
async def refresh_agent_pull(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run a one-shot agent pull and persist a HostMetrics row immediately."""
    from datetime import UTC, datetime

    host, _node = await _require_wings_host(db, host_id)
    endpoint, token = await _resolve_credentials(db, host)
    try:
        payload = await agent_client.fetch_metrics(endpoint, token, timeout=10.0)
    except agent_client.AgentClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc),
        ) from exc
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="agent pull returned empty payload",
        )

    now = datetime.now(UTC).replace(tzinfo=None)
    # Bug fix: the legacy admin_nodes.py route passed ``node_id`` here, but
    # ``build_metrics_row`` writes ``host_id`` straight into the
    # ``manager_host_metrics`` row. Sending the panel node id silently
    # corrupted host-keyed metrics on every "refresh now" click.
    row = build_metrics_row(host.id, now, payload)
    db.add(row)
    await db.commit()
    return {"ok": True, "ts": now.isoformat()}


# ---------------------------------------------------------------------------
# Wings configuration (Phase 2 — direct write to panel.nodes + push to wings)
# ---------------------------------------------------------------------------


class WingsConfigUpdateIn(BaseModel):
    """Patch body for ``PUT /admin/hosts/{id}/wings-config``.

    Every field is optional; only the fields present in the request body
    are written. Use ``model_fields_set`` to detect what was actually sent.

    Explicit ``null`` for any field whose underlying ``panel.nodes`` column
    is ``NOT NULL`` is rejected at validation time; without that guard a
    ``{"name": null}`` payload would slip past the per-field validators and
    blow up at ``commit()`` with a 500 instead of a clean 422.
    """

    name: str | None = Field(default=None, max_length=191)
    description: str | None = None
    fqdn: str | None = Field(default=None, max_length=191)
    scheme: str | None = None
    behind_proxy: bool | None = None
    maintenance_mode: bool | None = None
    memory: int | None = Field(default=None, ge=0)
    memory_overallocate: int | None = Field(default=None, ge=-1)
    disk: int | None = Field(default=None, ge=0)
    disk_overallocate: int | None = Field(default=None, ge=-1)
    upload_size: int | None = Field(default=None, ge=1, le=1024 * 1024)
    daemon_listen: int | None = Field(default=None, ge=1, le=65535)
    daemon_sftp: int | None = Field(default=None, ge=1, le=65535)
    daemon_base: str | None = Field(default=None, max_length=191)

    _NON_NULLABLE: ClassVar[frozenset[str]] = frozenset({
        "name",
        "fqdn",
        "scheme",
        "behind_proxy",
        "maintenance_mode",
        "memory",
        "memory_overallocate",
        "disk",
        "disk_overallocate",
        "upload_size",
        "daemon_listen",
        "daemon_sftp",
        "daemon_base",
    })

    @field_validator("scheme")
    @classmethod
    def _check_scheme(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ("http", "https"):
            raise ValueError("scheme must be 'http' or 'https'")
        return v

    @field_validator("name", "fqdn", "daemon_base")
    @classmethod
    def _strip_required(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v

    @model_validator(mode="after")
    def _reject_explicit_null_for_required(self) -> "WingsConfigUpdateIn":
        offenders = [
            f
            for f in self.model_fields_set & self._NON_NULLABLE
            if getattr(self, f) is None
        ]
        if offenders:
            raise ValueError(
                f"the following fields cannot be explicitly null: {', '.join(sorted(offenders))}"
            )
        return self


@router.get("/{host_id}/wings-config")
async def get_wings_config(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _host, node = await _require_wings_host(db, host_id)
    return await wings_config.get_state(db, node)


@router.put("/{host_id}/wings-config")
async def put_wings_config(
    host_id: int,
    body: WingsConfigUpdateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _host, node = await _require_wings_host(db, host_id)
    provided = body.model_fields_set & set(wings_config.WHITE_LIST)
    if not provided:
        raise HTTPException(status_code=400, detail="no editable field provided")

    before: dict = {}
    after: dict = {}
    for field in provided:
        before[field] = getattr(node, field)
        after[field] = getattr(body, field)

    changed = [f for f in provided if before[f] != after[f]]
    if not changed:
        return {
            "panel_updated": False,
            "wings_pushed": False,
            "applied": None,
            "changed": [],
        }

    # Capture the wings endpoint coordinates **before** mutating the row,
    # so a change to fqdn / scheme / daemon_listen still pushes to the
    # address wings is currently listening on. Defer daemon_token
    # decryption until we *know* a wings push is needed (see legacy
    # admin_nodes.py for the full rationale).
    needs_wings_push = bool(
        set(changed) & set(wings_config.WINGS_AFFECTING_FIELDS)
    )
    if needs_wings_push:
        pre_base_url = (
            f"{node.scheme}://{node.fqdn}:{node.daemon_listen}".lower()
        )
        pre_token = wings_service._decrypt_laravel(node.daemon_token)
    else:
        pre_base_url = None
        pre_token = None

    for field in changed:
        setattr(node, field, after[field])

    await db.commit()
    await db.refresh(node)
    wings_service.clear_cache()

    push_result: dict = {"pushed": False, "reason": "no_wings_affecting_field"}
    push_error: str | None = None
    try:
        push_result = await wings_config.push_to_wings(
            db,
            node,
            changed,
            override_base_url=pre_base_url,
            override_token=pre_token,
        )
    except WingsServiceError as exc:
        push_error = str(exc)
        logger.warning("wings push failed for host %s (node %s): %s", host_id, node.id, exc)

    if push_error is not None:
        log_status = "partial"
    elif push_result.get("pushed") and push_result.get("applied") is False:
        log_status = "partial"
    else:
        log_status = "success"
    await log_manager_activity(
        db,
        actor=admin.username,
        action="update_node_wings_config",
        status=log_status,
        detail_key="node.wings_config.update",
        detail_params={
            "host_id": host_id,
            "node_id": node.id,
            "node_name": node.name,
            "changed": changed,
            "wings_pushed": push_result.get("pushed", False),
            "wings_applied": push_result.get("applied"),
            "wings_error": push_error,
        },
    )

    push_succeeded = (
        push_error is None
        and push_result.get("pushed")
        and push_result.get("applied") is True
    )
    push_was_needed = needs_wings_push
    restart_required_fields_all = wings_config.restart_required_for(changed)
    if push_succeeded:
        restart_required_fields = restart_required_fields_all
    elif not push_was_needed:
        restart_required_fields = []
    else:
        restart_required_fields = []
    response = {
        "panel_updated": True,
        "wings_pushed": push_result.get("pushed", False),
        "applied": push_result.get("applied") if push_result.get("pushed") else None,
        "changed": changed,
        "requires_wings_restart": bool(restart_required_fields),
        "restart_required_fields": restart_required_fields,
        "wings_apply_rejected": (
            push_error is None
            and push_result.get("pushed") is True
            and push_result.get("applied") is False
        ),
    }
    if push_error:
        response["wings_error"] = push_error
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=response,
        )
    return response


@router.post("/{host_id}/wings-config/reset-token")
async def reset_node_daemon_token(
    host_id: int,
    auto_restart: bool = Query(
        True,
        description=(
            "After rotating the daemon token, automatically restart the wings "
            "service via the node agent and verify it accepts the new token. "
            "Set to false to keep legacy behavior (manual restart required)."
        ),
    ),
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rotate the wings daemon master key.

    See ``docs/MONITORING_AND_AGENT.md`` §11.1 / legacy admin_nodes.py
    for the full design narrative.
    """
    host, node = await _require_wings_host(db, host_id)
    try:
        result = await wings_config.reset_daemon_token(db, node)
    except WingsServiceError as exc:
        await log_manager_activity(
            db,
            actor=admin.username,
            action="reset_node_daemon_token",
            status="error",
            detail_key="node.daemon_token.reset",
            detail_params={
                "host_id": host_id,
                "node_id": node.id,
                "node_name": node.name,
                "wings_error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"wings rejected daemon token rotation: {exc}",
        ) from exc

    response: dict = {
        "ok": True,
        "applied": result["applied"],
        "token_id": result["token_id"],
    }

    auto_restart_outcome: dict[str, object] = {"attempted": False}
    if auto_restart:
        auto_restart_outcome["attempted"] = True
        try:
            endpoint, token = await host_registry.get_credentials(db, host.id)
            restart_resp = await agent_client.restart_wings(
                endpoint, token, timeout=60.0,
            )
            if not restart_resp.get("ok"):
                auto_restart_outcome["restarted"] = False
                auto_restart_outcome["error"] = (
                    restart_resp.get("error") or "agent reported wings.restart failure"
                )
            else:
                auto_restart_outcome["restarted"] = True
                self_check_ok = False
                self_check_error: str | None = None
                deadline = asyncio.get_event_loop().time() + 10.0
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        await wings_service.get_node_system(db, node.id)
                        self_check_ok = True
                        break
                    except WingsServiceError as exc:
                        self_check_error = str(exc)
                        await asyncio.sleep(1.0)
                auto_restart_outcome["self_check"] = self_check_ok
                if not self_check_ok and self_check_error:
                    auto_restart_outcome["self_check_error"] = self_check_error
        except host_registry.AgentNotConfigured:
            auto_restart_outcome["restarted"] = False
            auto_restart_outcome["error"] = "agent not configured for this host"
        except agent_client.AgentClientError as exc:
            auto_restart_outcome["restarted"] = False
            auto_restart_outcome["error"] = str(exc)

    log_status_value = "success"
    if auto_restart_outcome.get("attempted"):
        if not auto_restart_outcome.get("restarted") or (
            "self_check" in auto_restart_outcome and not auto_restart_outcome["self_check"]
        ):
            log_status_value = "partial"

    await log_manager_activity(
        db,
        actor=admin.username,
        action="reset_node_daemon_token",
        status=log_status_value,
        detail_key="node.daemon_token.reset",
        detail_params={
            "host_id": host_id,
            "node_id": node.id,
            "node_name": node.name,
            "new_token_id": result["token_id"],
            "wings_applied": result["applied"],
            "auto_restart": auto_restart_outcome,
        },
    )

    response["auto_restart"] = auto_restart_outcome
    if auto_restart and auto_restart_outcome.get("restarted") and auto_restart_outcome.get("self_check"):
        response["wings_restart_required"] = False
        response["message"] = (
            "Wings configuration written, agent restarted wings, and the new "
            "daemon master key is verified live."
        )
    else:
        response["wings_restart_required"] = True
        response["message"] = (
            "Wings configuration written, but the new daemon master key only "
            "becomes active after wings is restarted on the node host."
        )
    return response


# ---------------------------------------------------------------------------
# Wings systemd control via agent
# ---------------------------------------------------------------------------


@router.post("/{host_id}/wings/restart")
async def restart_wings(
    host_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restart the wings systemd unit on this host via its agent."""
    host, node = await _require_wings_host(db, host_id)
    endpoint, token = await _resolve_credentials(db, host)
    try:
        result = await agent_client.restart_wings(endpoint, token, timeout=60.0)
    except agent_client.AgentClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc),
        ) from exc

    await log_manager_activity(
        db,
        actor=admin.username,
        action="restart_wings",
        status="success" if result.get("ok") else "error",
        detail_key="node.wings.restart",
        detail_params={
            "host_id": host_id,
            "node_id": node.id,
            "duration_ms": result.get("duration_ms"),
            "ok": result.get("ok"),
            "error": result.get("error"),
        },
    )
    return result


@router.get("/{host_id}/wings/service")
async def get_wings_service_state(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the systemd state of the wings unit on this host."""
    host, _node = await _require_wings_host(db, host_id)
    endpoint, token = await _resolve_credentials(db, host)
    try:
        return await agent_client.get_wings_service(endpoint, token, timeout=8.0)
    except agent_client.AgentClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc),
        ) from exc


@router.get("/{host_id}/wings/logs/stream")
async def stream_wings_logs(
    host_id: int,
    request: Request,
    lines: int = Query(100, ge=0, le=1000),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Proxy the agent's `journalctl -u wings -f` SSE stream to the admin."""
    host, _node = await _require_wings_host(db, host_id)

    async def proxy() -> "asyncio.AsyncIterator[bytes]":
        try:
            endpoint, token = await host_registry.get_credentials(db, host.id)
            agen = agent_client.stream_wings_logs(
                endpoint, token, lines=lines,
            )
            try:
                async for chunk in agen:
                    if await request.is_disconnected():
                        break
                    yield chunk
            finally:
                await agen.aclose()
        except host_registry.AgentNotConfigured as exc:
            yield f"event: error\ndata: agent not configured: {exc}\n\n".encode("utf-8")
        except agent_client.AgentClientError as exc:
            yield f"event: error\ndata: {exc}\n\n".encode("utf-8")

    return StreamingResponse(
        proxy(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
