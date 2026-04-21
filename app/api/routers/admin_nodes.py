"""Admin endpoints for per-node Erocraft Agent V2 configuration & live ops."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value
from app.db.models.manager import NodeMeta
from app.db.models.pterodactyl import PanelNode, PteroUser
from app.services import agent_client
from app.services.agent_endpoint import (
    AgentEndpointError,
    validate_agent_endpoint,
)
from app.services.metrics_builder import build_metrics_row

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


async def _get_meta(db: AsyncSession, node_id: int) -> NodeMeta | None:
    result = await db.execute(select(NodeMeta).where(NodeMeta.node_id == node_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/agents", response_model=list[AgentConfigOut])
async def list_agent_configs(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AgentConfigOut]:
    """Batch endpoint: return AgentConfigOut for every Panel node in a single query.

    Preferred over N separate ``GET /{node_id}/agent`` calls from the Settings
    page to avoid fanning out N concurrent requests at a single Uvicorn worker
    (see Phase-1 CR §5.4).
    """
    nodes_res = await db.execute(select(PanelNode).order_by(PanelNode.id))
    nodes = list(nodes_res.scalars().all())

    metas_res = await db.execute(select(NodeMeta))
    metas = {m.node_id: m for m in metas_res.scalars().all()}

    out: list[AgentConfigOut] = []
    for node in nodes:
        meta = metas.get(node.id)
        out.append(
            AgentConfigOut(
                nodeId=node.id,
                fqdn=node.fqdn,
                agentEndpoint=meta.agent_endpoint if meta else None,
                agentTokenSet=bool(meta and meta.agent_token_encrypted),
                updatedAt=meta.updated_at.isoformat() if meta and meta.updated_at else None,
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
    meta = await _get_meta(db, node_id)
    return AgentConfigOut(
        nodeId=node_id,
        fqdn=node.fqdn,
        agentEndpoint=meta.agent_endpoint if meta else None,
        agentTokenSet=bool(meta and meta.agent_token_encrypted),
        updatedAt=meta.updated_at.isoformat() if meta and meta.updated_at else None,
    )


@router.put("/{node_id}/agent", response_model=AgentConfigOut)
async def put_agent_config(
    node_id: int,
    body: AgentConfigIn,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentConfigOut:
    node = await _ensure_node(db, node_id)
    meta = await _get_meta(db, node_id)
    if not meta:
        meta = NodeMeta(node_id=node_id)
        db.add(meta)

    # Tri-state patching — see AgentConfigIn docstring.
    provided = body.model_fields_set

    if "agentEndpoint" in provided:
        ep = (body.agentEndpoint or "").strip()
        meta.agent_endpoint = ep or None

    if "agentToken" in provided:
        token = body.agentToken
        if token in (None, ""):
            meta.agent_token_encrypted = None
        else:
            meta.agent_token_encrypted = encrypt_value(
                token, get_settings().settings_encryption_key,
            )

    await db.commit()
    await db.refresh(meta)
    return AgentConfigOut(
        nodeId=node_id,
        fqdn=node.fqdn,
        agentEndpoint=meta.agent_endpoint,
        agentTokenSet=bool(meta.agent_token_encrypted),
        updatedAt=meta.updated_at.isoformat() if meta.updated_at else None,
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
        resp = await agent_client.ping(db, node_id, timeout=5.0)
    except agent_client.AgentNotConfigured as exc:
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
        return await agent_client.fetch_metrics(db, node_id, timeout=10.0)
    except agent_client.AgentNotConfigured as exc:
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
        return await agent_client.fetch_wings_config(db, node_id, timeout=8.0)
    except agent_client.AgentNotConfigured as exc:
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
        payload = await agent_client.fetch_metrics(db, node_id, timeout=10.0)
    except agent_client.AgentNotConfigured as exc:
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
