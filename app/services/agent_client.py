"""HTTP client for talking to a node's Erocraft Agent V2."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_value
from app.db.models.manager import NodeMeta
from app.services.agent_endpoint import (
    AgentEndpointError,
    validate_agent_endpoint,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0


class AgentClientError(Exception):
    """Raised when an agent call fails."""


class AgentNotConfigured(AgentClientError):
    """Raised when no agent_endpoint/agent_token is configured for the node."""


async def _load_meta(db: AsyncSession, node_id: int) -> tuple[str, str]:
    """Load (endpoint, plaintext_token) for a node, raising AgentNotConfigured if missing."""
    result = await db.execute(select(NodeMeta).where(NodeMeta.node_id == node_id))
    meta = result.scalar_one_or_none()
    if not meta or not meta.agent_endpoint or not meta.agent_token_encrypted:
        raise AgentNotConfigured(f"agent not configured for node {node_id}")
    try:
        endpoint = validate_agent_endpoint(meta.agent_endpoint)
    except AgentEndpointError as exc:
        raise AgentClientError(f"invalid agent endpoint: {exc}") from exc
    try:
        token = decrypt_value(meta.agent_token_encrypted, get_settings().settings_encryption_key)
    except ValueError as exc:
        raise AgentClientError(f"agent token decrypt failed: {exc}") from exc
    return endpoint, token


async def _request(
    method: str,
    endpoint: str,
    token: str,
    path: str,
    *,
    json: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    url = f"{endpoint}{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=True, trust_env=False) as client:
            resp = await client.request(method, url, json=json, headers=headers)
    except httpx.HTTPError as exc:
        # Keep the raised message minimal — no full endpoint URL, no stack of
        # httpx internals — so callers that log ``str(e)`` won't leak the
        # node's private ingress into application logs (CR §2.9). The full
        # URL is still available on the ``debug`` channel for operators.
        logger.debug("agent %s %s transport error: %r", method, url, exc)
        raise AgentClientError(
            f"{method} {path} transport error: {type(exc).__name__}"
        ) from exc
    if resp.status_code >= 400:
        # Same rationale: exception message carries only status + a short
        # body hint; full URL + full body go to debug. Body truncated to 80
        # chars (was 200) so stray data never dominates logs.
        body_hint = resp.text[:80].replace("\n", " ") if resp.text else ""
        logger.debug(
            "agent %s %s -> HTTP %d body=%r",
            method, url, resp.status_code, resp.text[:500],
        )
        raise AgentClientError(
            f"{method} {path} -> HTTP {resp.status_code}"
            + (f": {body_hint}" if body_hint else "")
        )
    return resp.json()


async def fetch_metrics(db: AsyncSession, node_id: int, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    endpoint, token = await _load_meta(db, node_id)
    return await _request("GET", endpoint, token, "/v1/metrics", timeout=timeout)


async def fetch_wings_config(db: AsyncSession, node_id: int, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    endpoint, token = await _load_meta(db, node_id)
    return await _request("GET", endpoint, token, "/v1/wings/config", timeout=timeout)


async def fetch_status(db: AsyncSession, node_id: int, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    endpoint, token = await _load_meta(db, node_id)
    return await _request("GET", endpoint, token, "/v1/status", timeout=timeout)


async def ping(db: AsyncSession, node_id: int, *, timeout: float = 5.0) -> dict:
    endpoint, token = await _load_meta(db, node_id)
    return await _request(
        "POST", endpoint, token, "/v1/commands",
        json={"id": 0, "type": "ping", "params": {}},
        timeout=timeout,
    )


async def healthz(endpoint: str, *, timeout: float = 3.0) -> bool:
    """Unauthenticated health check (used during initial config to verify reachability)."""
    url = f"{endpoint.rstrip('/')}/healthz"
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=True, trust_env=False) as client:
            resp = await client.get(url)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False
