"""Admin endpoints for per-node Erocraft Agent V2 configuration & live ops."""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.db.models.pterodactyl import PanelNode, PteroUser
from app.services import agent_client, host_registry, wings_config
from app.services.agent_endpoint import (
    AgentEndpointError,
    validate_agent_endpoint,
)
from app.services.audit import log_manager_activity
from app.services.metrics_builder import build_metrics_row
from app.services.wings import WingsServiceError, wings_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/nodes", tags=["admin-nodes"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentConfigOut(BaseModel):
    nodeId: int
    fqdn: str
    agentEndpoint: str | None = None
    agentTokenSet: bool = False  # never expose plaintext
    updatedAt: str | None = None


class AgentConfigIn(BaseModel):
    """Patch-style body for ``PUT /admin/nodes/{id}/agent``.

    Both fields are **tri-state**:

    * **Field omitted** from the JSON body → keep existing value untouched
      (detected via :pyattr:`BaseModel.model_fields_set`).
    * **Explicit ``null``** or **empty string ``""``** → clear the stored value.
    * **Non-empty string** → set / replace.

    Previously the in-code comment read ``empty => keep existing`` which
    conflated "omitted" with "null / empty" and was misleading (CR §2.8);
    the handler now routes via :pyattr:`model_fields_set` so callers can
    explicitly nullify a field.
    """

    agentEndpoint: str | None = None
    agentToken: str | None = None

    @field_validator("agentEndpoint")
    @classmethod
    def _check_endpoint(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return ""  # caller treats "" as clear
        try:
            return validate_agent_endpoint(v)
        except AgentEndpointError as exc:
            raise ValueError(str(exc)) from exc


class AgentPingOut(BaseModel):
    ok: bool
    detail: str
    response: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_node(db: AsyncSession, node_id: int) -> PanelNode:
    result = await db.execute(select(PanelNode).where(PanelNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="node not found")
    return node


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/agents", response_model=list[AgentConfigOut])
async def list_agent_configs(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AgentConfigOut]:
    """Batch endpoint: return AgentConfigOut for every Panel node in a single query.

    Reads the wings_node manager_hosts rows in one go to avoid fanning out
    N requests from the Settings page (Phase-1 CR §5.4). Nodes without a
    matching host row report ``agentEndpoint=None`` / ``agentTokenSet=False``.
    """
    nodes_res = await db.execute(select(PanelNode).order_by(PanelNode.id))
    nodes = list(nodes_res.scalars().all())

    hosts = await host_registry.list_hosts(
        db, kind=host_registry.KIND_WINGS_NODE,
    )
    host_by_node: dict[int, object] = {
        h.pterodactyl_node_id: h
        for h in hosts
        if h.pterodactyl_node_id is not None
    }

    out: list[AgentConfigOut] = []
    for node in nodes:
        host = host_by_node.get(node.id)
        out.append(
            AgentConfigOut(
                nodeId=node.id,
                fqdn=node.fqdn,
                agentEndpoint=host.agent_url if host else None,
                agentTokenSet=bool(host),
                updatedAt=host.updated_at.isoformat() if host else None,
            )
        )
    return out


@router.get("/{node_id}/agent", response_model=AgentConfigOut)
async def get_agent_config(
    node_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentConfigOut:
    node = await _ensure_node(db, node_id)
    host = await host_registry.get_host_by_node_id(db, node_id)
    return AgentConfigOut(
        nodeId=node_id,
        fqdn=node.fqdn,
        agentEndpoint=host.agent_url if host else None,
        agentTokenSet=bool(host),
        updatedAt=host.updated_at.isoformat() if host else None,
    )


@router.put("/{node_id}/agent", response_model=AgentConfigOut)
async def put_agent_config(
    node_id: int,
    body: AgentConfigIn,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentConfigOut:
    """Set / clear the agent endpoint + token for a wings node.

    Backed by ``manager_hosts`` (kind='wings_node'). Tri-state semantics on
    each field per :class:`AgentConfigIn`:

    * field omitted -> keep existing value
    * field == ``""`` (empty string) or ``None`` -> clear (and if both
      credentials end up cleared, the host row is deleted, leaving the
      Pterodactyl node without manager integration).
    * non-empty string -> set / replace.
    """
    node = await _ensure_node(db, node_id)

    provided = body.model_fields_set
    # Pass None for fields the caller didn't mention; pass empty-string for
    # explicit clears so upsert_wings_node_credentials can disambiguate
    # "keep" from "clear".
    agent_url_arg: str | None = None
    if "agentEndpoint" in provided:
        agent_url_arg = body.agentEndpoint or ""
    agent_token_arg: str | None = None
    if "agentToken" in provided:
        agent_token_arg = body.agentToken or ""

    try:
        host = await host_registry.upsert_wings_node_credentials(
            db,
            node_id,
            name=node.name,
            hostname=node.fqdn,
            agent_url=agent_url_arg,
            agent_token=agent_token_arg,
        )
    except host_registry.HostRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc

    return AgentConfigOut(
        nodeId=node_id,
        fqdn=node.fqdn,
        agentEndpoint=host.agent_url if host else None,
        agentTokenSet=bool(host),
        updatedAt=host.updated_at.isoformat() if host else None,
    )


# ---------------------------------------------------------------------------
# Live ops
# ---------------------------------------------------------------------------


@router.post("/{node_id}/agent/ping", response_model=AgentPingOut)
async def ping_agent(
    node_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentPingOut:
    await _ensure_node(db, node_id)
    try:
        endpoint, token = await host_registry.get_credentials_for_node(db, node_id)
        resp = await agent_client.ping(endpoint, token, timeout=5.0)
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except agent_client.AgentClientError as exc:
        return AgentPingOut(ok=False, detail=str(exc))
    return AgentPingOut(ok=bool(resp.get("ok")), detail="pong", response=resp)


@router.get("/{node_id}/agent/metrics")
async def get_agent_metrics(
    node_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_node(db, node_id)
    try:
        endpoint, token = await host_registry.get_credentials_for_node(db, node_id)
        return await agent_client.fetch_metrics(endpoint, token, timeout=10.0)
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except agent_client.AgentClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/{node_id}/agent/wings-config")
async def get_agent_wings_config(
    node_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_node(db, node_id)
    try:
        endpoint, token = await host_registry.get_credentials_for_node(db, node_id)
        return await agent_client.fetch_wings_config(endpoint, token, timeout=8.0)
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except agent_client.AgentClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/{node_id}/agent/refresh")
async def refresh_agent_pull(
    node_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run a one-shot agent pull and persist NodeMetrics row immediately."""
    from datetime import UTC, datetime

    await _ensure_node(db, node_id)
    try:
        endpoint, token = await host_registry.get_credentials_for_node(db, node_id)
        payload = await agent_client.fetch_metrics(endpoint, token, timeout=10.0)
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except agent_client.AgentClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="agent pull returned empty payload")

    now = datetime.now(UTC).replace(tzinfo=None)
    row = build_metrics_row(node_id, now, payload)
    db.add(row)
    await db.commit()
    return {"ok": True, "ts": now.isoformat()}


# ---------------------------------------------------------------------------
# Wings configuration (Phase 2 — direct write to panel.nodes + push to wings)
# ---------------------------------------------------------------------------


class WingsConfigUpdateIn(BaseModel):
    """Patch body for ``PUT /admin/nodes/{id}/wings-config``.

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

    # Panel columns that are NOT NULL in the schema. Sending these as
    # explicit ``null`` must be rejected with 422, not crash the row.
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


@router.get("/{node_id}/wings-config")
async def get_wings_config(
    node_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    node = await _ensure_node(db, node_id)
    return await wings_config.get_state(db, node)


@router.put("/{node_id}/wings-config")
async def put_wings_config(
    node_id: int,
    body: WingsConfigUpdateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    node = await _ensure_node(db, node_id)
    provided = body.model_fields_set & set(wings_config.WHITE_LIST)
    if not provided:
        raise HTTPException(status_code=400, detail="no editable field provided")

    before: dict = {}
    after: dict = {}
    for field in provided:
        before[field] = getattr(node, field)
        new_value = getattr(body, field)
        after[field] = new_value

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
    # address wings is currently listening on. Token rotation goes through
    # a separate endpoint (reset-token), so the in-DB token is fine to use.
    #
    # Defer the daemon_token decryption until we *know* a wings push will
    # be needed. Otherwise a pure panel-side change (name, description,
    # memory, disk, …) on a node whose token cannot currently be
    # decrypted (PANEL_APP_KEY missing / corrupt cipher / older node
    # encrypted with a different key) would 500 even though the change
    # never touches wings.
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
    # Address / port / scheme may have just changed — invalidate the
    # cached _NodeInfo so subsequent calls (after wings has rebound)
    # don't keep talking to the stale endpoint.
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
        logger.warning("wings push failed for node %s: %s", node_id, exc)

    # Activity log status reflects the *operational* outcome:
    #   success  — panel updated AND (no wings push needed OR wings applied)
    #   partial  — panel updated but wings push failed OR wings reported
    #              applied=false (ignore_panel_config_updates=true).
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
            "node_id": node_id,
            "node_name": node.name,
            "changed": changed,
            "wings_pushed": push_result.get("pushed", False),
            "wings_applied": push_result.get("applied"),
            "wings_error": push_error,
        },
    )

    # ``requires_wings_restart`` reflects the *operationally meaningful*
    # signal: only when wings actually accepted the patch (pushed=True AND
    # applied=True) does a restart make sense. The other branches need
    # different operator action, surfaced via separate flags:
    #   * push transport failed (502)         -> wings_error populated
    #   * wings refused to apply (applied=False) -> wings_apply_rejected
    # Restarting wings in those branches won't pick up the new value: in the
    # first case wings never received it; in the second wings has
    # ``ignore_panel_config_updates`` enabled and will keep ignoring future
    # pushes too. The UI MUST show different remediation for each.
    push_succeeded = (
        push_error is None
        and push_result.get("pushed")
        and push_result.get("applied") is True
    )
    push_was_needed = bool(set(changed) & set(wings_config.WINGS_AFFECTING_FIELDS))
    restart_required_fields_all = wings_config.restart_required_for(changed)
    if push_succeeded:
        restart_required_fields = restart_required_fields_all
    elif not push_was_needed:
        # Pure panel-side change \u2014 wings doesn't care, no restart needed.
        restart_required_fields = []
    else:
        # Push failed or wings rejected \u2014 restart won't help, suppress hint.
        restart_required_fields = []
    response = {
        "panel_updated": True,
        "wings_pushed": push_result.get("pushed", False),
        "applied": push_result.get("applied") if push_result.get("pushed") else None,
        "changed": changed,
        # See the comment above. ``requires_wings_restart`` is the gated
        # signal; ``restart_required_fields`` lists which changed fields
        # caused it (subset of
        # ``wings_config.RUNTIME_RESTART_REQUIRED_FIELDS``).
        "requires_wings_restart": bool(restart_required_fields),
        "restart_required_fields": restart_required_fields,
        # Distinct flag for the ``applied=False`` case: wings accepted the
        # HTTP request but its ``ignore_panel_config_updates`` setting made
        # it discard the change. Operator must SSH in and flip that setting
        # \u2014 no amount of restarting / re-pushing will help.
        "wings_apply_rejected": (
            push_error is None
            and push_result.get("pushed") is True
            and push_result.get("applied") is False
        ),
    }
    if push_error:
        response["wings_error"] = push_error
        # DB has already been updated and is left as-is (matches the design
        # in MONITORING_AND_AGENT.md §11.1: panel is the source of truth).
        # Surface 502 so HTTP-status-only callers don't mistake this for
        # "fully synchronized".
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=response,
        )
    return response


@router.post("/{node_id}/wings-config/reset-token")
async def reset_node_daemon_token(
    node_id: int,
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

    Equivalent to Pterodactyl panel's *Reset Daemon Master Key* action:
    generates a fresh ``token_id`` + ``token``, persists them to
    ``panel.nodes`` and pushes them to wings ``POST /api/update``. A failure
    to reach wings rolls the panel row back to keep manager and wings in sync.

    When ``auto_restart=true`` (default), additionally:

    1. POST ``wings.restart`` command to the node agent.
    2. Poll wings ``GET /api/system`` (with the new token) until it answers
       200 or a 10s budget is exhausted, confirming the new credentials are
       live in the wings process.
    """
    node = await _ensure_node(db, node_id)
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
                "node_id": node_id,
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

    # ---- auto-restart + self-check ----
    auto_restart_outcome: dict[str, object] = {"attempted": False}
    if auto_restart:
        auto_restart_outcome["attempted"] = True
        try:
            endpoint, token = await host_registry.get_credentials_for_node(
                db, node_id,
            )
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
                # Poll wings /api/system with the new token to confirm liveness.
                self_check_ok = False
                self_check_error: str | None = None
                deadline = asyncio.get_event_loop().time() + 10.0
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        await wings_service.get_node_system(db, node_id)
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
            auto_restart_outcome["error"] = "agent not configured for this node"
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
            "node_id": node_id,
            "node_name": node.name,
            "new_token_id": result["token_id"],
            "wings_applied": result["applied"],
            "auto_restart": auto_restart_outcome,
        },
    )

    response["auto_restart"] = auto_restart_outcome
    if auto_restart and auto_restart_outcome.get("restarted") and auto_restart_outcome.get("self_check"):
        # Fully automated success — the legacy "restart required" warning no
        # longer applies.
        response["wings_restart_required"] = False
        response["message"] = (
            "Wings configuration written, agent restarted wings, and the new "
            "daemon master key is verified live."
        )
    else:
        # Either auto_restart=false, or restart/self-check failed — keep the
        # legacy warning so the operator knows manual intervention is needed.
        response["wings_restart_required"] = True
        response["message"] = (
            "Wings configuration written, but the new daemon master key only "
            "becomes active after wings is restarted on the node host."
        )
    return response


# ---------------------------------------------------------------------------
# PR-A: wings systemd control via agent
# ---------------------------------------------------------------------------


@router.post("/{node_id}/wings/restart")
async def restart_wings(
    node_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restart the wings systemd unit on this node via its agent.

    Returns the agent's :class:`CommandResponse` payload (``ok``, ``output``,
    ``error``, ``duration_ms``). 502 is returned when the agent itself is
    unreachable or refuses the call; ``ok=false`` in the body means the
    agent reached but the systemctl invocation failed.
    """
    await _ensure_node(db, node_id)
    try:
        endpoint, token = await host_registry.get_credentials_for_node(db, node_id)
        result = await agent_client.restart_wings(endpoint, token, timeout=60.0)
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except agent_client.AgentClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await log_manager_activity(
        db,
        actor=admin.username,
        action="restart_wings",
        status="success" if result.get("ok") else "error",
        detail_key="node.wings.restart",
        detail_params={
            "node_id": node_id,
            "duration_ms": result.get("duration_ms"),
            "ok": result.get("ok"),
            "error": result.get("error"),
        },
    )
    return result


@router.get("/{node_id}/wings/service")
async def get_wings_service_state(
    node_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the systemd state of the wings unit on this node."""
    await _ensure_node(db, node_id)
    try:
        endpoint, token = await host_registry.get_credentials_for_node(db, node_id)
        return await agent_client.get_wings_service(endpoint, token, timeout=8.0)
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except agent_client.AgentClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/{node_id}/wings/logs/stream")
async def stream_wings_logs(
    node_id: int,
    request: Request,
    lines: int = Query(100, ge=0, le=1000),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Proxy the agent's `journalctl -u wings -f` SSE stream to the admin.

    The connection is held open for the lifetime of the journalctl tail.
    Closing the client connection (or closing the agent) terminates the
    upstream subprocess on the node.
    """
    await _ensure_node(db, node_id)

    async def proxy() -> "asyncio.AsyncIterator[bytes]":
        try:
            endpoint, token = await host_registry.get_credentials_for_node(
                db, node_id,
            )
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
