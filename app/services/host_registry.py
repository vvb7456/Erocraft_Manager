"""Manager host registry — see ``docs/HOST_MANAGEMENT_DESIGN.md`` §4.1.

Owns the full lifecycle of ``manager_hosts`` rows: lookup, create, update,
delete, agent token rotation, and inbound probe. All credential decryption
happens here so the rest of the codebase never touches Fernet directly for
agent tokens.

The only side-effect surface is the database; HTTP transport to the agent
lives in :mod:`app.services.agent_client`. The two collaborate via the
``(endpoint, token)`` pair returned by :func:`get_credentials` /
:func:`get_credentials_for_node`.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value
from app.db.models.manager import ManagerHost
from app.services.agent_endpoint import (
    AgentEndpointError,
    validate_agent_endpoint,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HostRegistryError(Exception):
    """Base for host_registry errors."""


class HostNotFound(HostRegistryError):
    """No manager_hosts row matches the requested identifier."""


class AgentNotConfigured(HostRegistryError):
    """The host exists but has no usable agent_url / token (or decryption failed)."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Recognised values for ``manager_hosts.kind``. ``wings_node`` is the only
#: kind that ties back to a Pterodactyl node row; the rest are generic
#: agent-managed boxes (a sibling field ``kind`` is the UI's icon hint).
KIND_WINGS_NODE = "wings_node"
KIND_GENERIC_LINUX = "generic_linux"
KIND_SYNOLOGY_DSM = "synology_dsm"
ALLOWED_KINDS: frozenset[str] = frozenset({
    KIND_WINGS_NODE,
    KIND_GENERIC_LINUX,
    KIND_SYNOLOGY_DSM,
})

#: Length of the random Bearer token created on host registration / rotation.
#: Matches the agent's existing token format (URL-safe base64-ish, 43 chars
#: from 32 random bytes).
_AGENT_TOKEN_BYTES = 32


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _generate_agent_token() -> str:
    """Return a fresh URL-safe Bearer token suitable for the agent.

    Uses :func:`secrets.token_urlsafe` so the token only contains characters
    that are safe in HTTP headers and YAML files (operators paste this into
    the agent's ``config.yaml``).
    """
    return secrets.token_urlsafe(_AGENT_TOKEN_BYTES)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


async def get_host_by_id(db: AsyncSession, host_id: int) -> ManagerHost | None:
    """Return the row for ``host_id`` or ``None``."""
    result = await db.execute(select(ManagerHost).where(ManagerHost.id == host_id))
    return result.scalar_one_or_none()


async def require_host_by_id(db: AsyncSession, host_id: int) -> ManagerHost:
    """Like :func:`get_host_by_id` but raises :class:`HostNotFound`."""
    host = await get_host_by_id(db, host_id)
    if host is None:
        raise HostNotFound(f"manager_host id={host_id} not found")
    return host


async def get_host_by_node_id(db: AsyncSession, node_id: int) -> ManagerHost | None:
    """Return the wings_node host wired to ``panel.nodes.id == node_id``, or ``None``.

    Convenience for legacy ``/admin/nodes/{id}/*`` endpoints that key on the
    Pterodactyl node id rather than the manager_hosts surrogate id.
    """
    result = await db.execute(
        select(ManagerHost).where(
            ManagerHost.pterodactyl_node_id == node_id,
            ManagerHost.kind == KIND_WINGS_NODE,
        )
    )
    return result.scalar_one_or_none()


async def list_hosts(
    db: AsyncSession,
    *,
    kind: str | None = None,
    enabled: bool | None = None,
) -> list[ManagerHost]:
    """Return matching hosts, ordered by id."""
    stmt = select(ManagerHost).order_by(ManagerHost.id)
    if kind is not None:
        stmt = stmt.where(ManagerHost.kind == kind)
    if enabled is not None:
        stmt = stmt.where(ManagerHost.enabled == enabled)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def _decrypt_token(host: ManagerHost) -> str:
    try:
        return decrypt_value(
            host.agent_token_enc, get_settings().settings_encryption_key,
        )
    except ValueError as exc:
        raise AgentNotConfigured(
            f"agent token decrypt failed for host {host.id}"
        ) from exc


def _validated_endpoint(host: ManagerHost) -> str:
    try:
        return validate_agent_endpoint(host.agent_url)
    except AgentEndpointError as exc:
        raise AgentNotConfigured(
            f"invalid agent_url for host {host.id}: {exc}"
        ) from exc


async def get_credentials(db: AsyncSession, host_id: int) -> tuple[str, str]:
    """Return ``(validated_endpoint, plaintext_token)`` for ``host_id``.

    Raises :class:`HostNotFound` when the row doesn't exist, or
    :class:`AgentNotConfigured` when the row is disabled / has bad creds.
    """
    host = await require_host_by_id(db, host_id)
    if not host.enabled:
        raise AgentNotConfigured(f"host {host_id} is disabled")
    return _validated_endpoint(host), _decrypt_token(host)


def decrypt_credentials(host: ManagerHost) -> tuple[str, str]:
    """Synchronously resolve ``(endpoint, token)`` for an in-memory host row.

    The async :func:`get_credentials` is the right call when you only have
    a host id and need a DB round-trip anyway. This helper exists for the
    monitoring scheduler which pre-loads every wings_node host in a single
    query (to avoid N+1 fetches inside ``asyncio.gather``) and just needs
    to decrypt each one without re-touching the session.

    Raises :class:`AgentNotConfigured` for either invalid endpoint or
    bad ciphertext — callers typically log + skip.
    """
    return _validated_endpoint(host), _decrypt_token(host)


async def get_credentials_for_node(
    db: AsyncSession, node_id: int,
) -> tuple[str, str]:
    """Look up the wings_node host for ``panel.nodes.id == node_id`` and
    return its credentials.

    Raises :class:`AgentNotConfigured` when no host is wired to this node
    (operator hasn't enabled the integration yet) — the same exception
    type used elsewhere so callers can treat "no node binding" and
    "host disabled / bad creds" uniformly.
    """
    host = await get_host_by_node_id(db, node_id)
    if host is None:
        raise AgentNotConfigured(
            f"no manager_host wired to panel node {node_id}"
        )
    if not host.enabled:
        raise AgentNotConfigured(f"host for node {node_id} is disabled")
    return _validated_endpoint(host), _decrypt_token(host)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create_host(
    db: AsyncSession,
    *,
    name: str,
    kind: str,
    hostname: str,
    agent_url: str,
    agent_token: str,
    pterodactyl_node_id: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
    enabled: bool = True,
) -> ManagerHost:
    """Insert a new manager_hosts row.

    ``agent_token`` is the plaintext Bearer token that the operator will
    place into the agent's ``config.yaml``; it is Fernet-encrypted before
    being persisted. The plaintext is **not** stored anywhere by manager.

    ``agent_url`` is validated via :func:`validate_agent_endpoint` before
    insertion; rejection raises :class:`HostRegistryError`.
    """
    if kind not in ALLOWED_KINDS:
        raise HostRegistryError(f"unknown host kind: {kind!r}")
    if (kind == KIND_WINGS_NODE) != (pterodactyl_node_id is not None):
        raise HostRegistryError(
            "pterodactyl_node_id must be set iff kind == 'wings_node'"
        )
    try:
        validated_url = validate_agent_endpoint(agent_url)
    except AgentEndpointError as exc:
        raise HostRegistryError(f"invalid agent_url: {exc}") from exc

    secret = get_settings().settings_encryption_key
    host = ManagerHost(
        name=name.strip(),
        kind=kind,
        hostname=hostname.strip(),
        agent_url=validated_url,
        agent_token_enc=encrypt_value(agent_token, secret),
        pterodactyl_node_id=pterodactyl_node_id,
        extra_metadata=extra_metadata,
        enabled=enabled,
        # ``inbound_reachable`` defaults to True at the column level; the
        # /probe endpoint is the canonical way to flip it after creation.
    )
    db.add(host)
    await db.commit()
    await db.refresh(host)
    return host


async def update_host(
    db: AsyncSession,
    host: ManagerHost,
    *,
    name: str | None = None,
    hostname: str | None = None,
    agent_url: str | None = None,
    agent_token: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
    enabled: bool | None = None,
    inbound_reachable: bool | None = None,
) -> ManagerHost:
    """Patch the mutable fields of a host.

    Pass ``None`` (default) for any field you don't want to change. The
    ``agent_token`` parameter accepts a plaintext Bearer (typically minted
    client-side); when supplied, it is re-encrypted and persisted to
    ``agent_token_enc``.
    """
    if name is not None:
        host.name = name.strip()
    if hostname is not None:
        host.hostname = hostname.strip()
    if agent_url is not None:
        try:
            host.agent_url = validate_agent_endpoint(agent_url)
        except AgentEndpointError as exc:
            raise HostRegistryError(f"invalid agent_url: {exc}") from exc
    if agent_token is not None:
        host.agent_token_enc = encrypt_value(
            agent_token, get_settings().settings_encryption_key,
        )
    if extra_metadata is not None:
        host.extra_metadata = extra_metadata
    if enabled is not None:
        host.enabled = enabled
    if inbound_reachable is not None:
        host.inbound_reachable = inbound_reachable
    await db.commit()
    await db.refresh(host)
    return host


async def delete_host(db: AsyncSession, host: ManagerHost) -> None:
    """Hard-delete a host. Cascades to dependent rows defined by FKs."""
    await db.delete(host)
    await db.commit()


async def upsert_wings_node_credentials(
    db: AsyncSession,
    node_id: int,
    *,
    name: str,
    hostname: str,
    agent_url: str | None,
    agent_token: str | None,
) -> ManagerHost | None:
    """Compatibility helper for the legacy ``PUT /admin/nodes/{id}/agent``.

    Tri-state semantics matching the old ``AgentConfigIn``:

    * ``agent_url`` / ``agent_token`` both ``None`` AND no existing host
      → no-op, returns ``None``.
    * Existing host present
      → update non-``None`` fields. Either field passed as the literal
        sentinel ``""`` (empty string) means "clear" — but clearing
        ``agent_url`` or ``agent_token`` would leave the host unusable, so
        we delete the host row instead (mirrors the old behaviour where
        clearing both fields effectively decommissioned the integration).
    * No existing host AND both fields populated
      → create a fresh ``kind='wings_node'`` row.

    The frontend currently sends "" to clear, full strings to set, and
    omits the field to leave alone.
    """
    host = await get_host_by_node_id(db, node_id)

    # Normalise: treat empty-string as "clear" sentinel.
    url_clear = agent_url == ""
    tok_clear = agent_token == ""

    if host is None:
        # Nothing to update; nothing to create unless both fields set.
        if not agent_url or not agent_token or url_clear or tok_clear:
            return None
        return await create_host(
            db,
            name=name,
            kind=KIND_WINGS_NODE,
            hostname=hostname,
            agent_url=agent_url,
            agent_token=agent_token,
            pterodactyl_node_id=node_id,
        )

    # Existing host. If the operator is clearing creds, drop the row
    # entirely — leaving an unusable host around would just clutter the
    # /admin/hosts list and confuse the monitoring scheduler.
    if url_clear or tok_clear:
        await delete_host(db, host)
        return None

    if agent_url is not None:
        try:
            host.agent_url = validate_agent_endpoint(agent_url)
        except AgentEndpointError as exc:
            raise HostRegistryError(f"invalid agent_url: {exc}") from exc
    if agent_token is not None:
        host.agent_token_enc = encrypt_value(
            agent_token, get_settings().settings_encryption_key,
        )
    await db.commit()
    await db.refresh(host)
    return host


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


async def probe(db: AsyncSession, host: ManagerHost, *, timeout: float = 5.0) -> dict[str, Any]:
    """Call ``GET {agent_url}/v1/status`` and update the cached reachability.

    On success: sets ``inbound_reachable=True`` and ``last_status_at=now()``,
    returns the agent's status payload as a dict.
    On failure: sets ``inbound_reachable=False``, raises :class:`AgentNotConfigured`
    when creds are bad, or returns ``{"ok": False, "error": "..."}`` for
    transport / HTTP errors (the row is still updated so the UI can display
    "unreachable").
    """
    try:
        endpoint = _validated_endpoint(host)
        token = _decrypt_token(host)
    except AgentNotConfigured:
        # Persist the unreachable flag so the UI doesn't keep showing a
        # stale green dot for a host whose agent_url / token went bad.
        if host.inbound_reachable:
            host.inbound_reachable = False
            await db.commit()
        raise

    return await _probe_with_credentials(db, host, endpoint, token, timeout=timeout)


async def probe_credentials(
    endpoint: str, token: str, *, timeout: float = 5.0,
) -> dict[str, Any]:
    """Lightweight ``/v1/status`` probe that doesn't touch the database.

    Used by ``POST /admin/hosts`` to validate credentials *before* the
    host row is inserted (probe-on-create requirement, design doc §5.3).
    Returns the same shape as :func:`probe` minus the side-effects.
    """
    try:
        validated = validate_agent_endpoint(endpoint)
    except AgentEndpointError as exc:
        return {"ok": False, "error": f"invalid endpoint: {exc}"}
    return await _do_probe(validated, token, timeout)


async def _do_probe(endpoint: str, token: str, timeout: float) -> dict[str, Any]:
    url = f"{endpoint}/v1/status"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=timeout, verify=True, trust_env=False,
        ) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"transport: {type(exc).__name__}"}
    latency_ms = round((time.monotonic() - started) * 1000)
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}
    return {
        "ok": True,
        "response": resp.json() if resp.content else {},
        "latency_ms": latency_ms,
    }


async def _probe_with_credentials(
    db: AsyncSession,
    host: ManagerHost,
    endpoint: str,
    token: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    result = await _do_probe(endpoint, token, timeout)
    if result.get("ok"):
        host.inbound_reachable = True
        host.last_status_at = _utc_now()
    else:
        host.inbound_reachable = False
    await db.commit()
    return result


async def mark_seen(db: AsyncSession, host: ManagerHost) -> None:
    """Record a successful agent metrics pull (called by the monitoring scheduler)."""
    host.last_seen_at = _utc_now()
    await db.commit()
