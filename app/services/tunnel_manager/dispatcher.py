"""High-level orchestration for Cloudflare Tunnel admin operations.

This module enforces the **CF-resources >= DB-resources** invariant from
``docs/CLOUDFLARE_TUNNEL_DESIGN.md`` §8b: every flow that creates resources
writes to CF first and DB second; every flow that destroys resources writes
to DB-status first (``disabling``), CF second, then removes the DB row. On
any partial failure we either rollback the CF side or leave a row in
``disabling`` for the reconciler to retry.

Phase 1 scope (admin only):
    * :func:`bind_account` — store CF credentials on a host
    * :func:`install_tunnel` — create CF tunnel + push initial config + start cloudflared
    * :func:`sync_host` — recompute ingress and push to agent
    * :func:`uninstall_tunnel` — stop cloudflared and delete CF tunnel + DB row

Phase 2 (server-level enable/disable + lifecycle hooks) lives in this same
file as additional functions added later.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value
from app.core.time import utc_naive_now
from app.db.models.manager import (
    ManagerHost,
    ManagerHostTunnel,
    ManagerOrphanResource,
    ManagerServerTunnel,
)
from app.services import host_registry

from .cf_client import CloudflareClient
from .exceptions import (
    CloudflareAPIError,
    HostnameConflict,
    HostTunnelNotConfigured,
    HostTunnelNotReady,
    InvalidSubdomain,
    TunnelManagerError,
)
from .ingress_builder import build_ingress

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CF_ID_RE = re.compile(r"^[0-9a-f]{32,64}$")
_CF_TUNNEL_UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


def _get_encryption_secret() -> str:
    return get_settings().settings_encryption_key


async def _get_host_tunnel(db: AsyncSession, host_id: int) -> ManagerHostTunnel | None:
    res = await db.execute(
        select(ManagerHostTunnel).where(ManagerHostTunnel.host_id == host_id)
    )
    return res.scalar_one_or_none()


async def _require_host_tunnel(db: AsyncSession, host_id: int) -> ManagerHostTunnel:
    ht = await _get_host_tunnel(db, host_id)
    if ht is None:
        raise HostTunnelNotConfigured(
            f"host {host_id} has no Cloudflare Tunnel binding"
        )
    return ht


def _build_cf_client(host_tunnel: ManagerHostTunnel) -> CloudflareClient:
    token = decrypt_value(host_tunnel.cf_api_token_enc, _get_encryption_secret())
    return CloudflareClient(host_tunnel.cf_account_id, token)


def _tunnel_name_for_host(host: ManagerHost) -> str:
    """Deterministic CF tunnel name for a host.

    Format ``erocraft-host-{id}-{name}`` (CF allows up to 120 chars). We trim
    the host name to keep things readable in the CF dashboard.
    """
    suffix = (host.name or "").strip().lower().replace(" ", "-")
    suffix = "".join(c for c in suffix if c.isalnum() or c in "-_")[:32]
    return f"erocraft-host-{host.id}-{suffix}" if suffix else f"erocraft-host-{host.id}"


# ---------------------------------------------------------------------------
# Bind / unbind
# ---------------------------------------------------------------------------


async def bind_account(
    db: AsyncSession,
    host: ManagerHost,
    *,
    cf_account_id: str,
    cf_api_token: str,
    cf_zone_id: str,
    cf_zone_name: str,
) -> ManagerHostTunnel:
    """Verify the CF token, then upsert the host_tunnel binding row.

    Does **not** create the CF tunnel — that happens in :func:`install_tunnel`.

    Behaviour on rebind (existing row):
      * If the **account or zone changed** → the existing CF tunnel is
        bound to a different account/zone and is no longer reachable from
        the new credentials. Reset to ``status=pending`` and clear the
        ``cf_tunnel_id`` / secret / version so the admin is forced to
        re-install. (See B4 in CF_TUNNEL_LOGIC_AUDIT.md.)
      * If only the **token rotated** (same account + zone) → preserve
        ``cf_tunnel_id``, secret and ``status=ready``. The new token must
        still grant access to the same tunnel.
    """
    # Verify token + account before persisting
    client = CloudflareClient(cf_account_id, cf_api_token)
    await client.verify_token()
    await client.verify_account_access()

    secret = _get_encryption_secret()
    token_enc = encrypt_value(cf_api_token, secret)

    # Concurrency-safe upsert: try INSERT first; if uk_host_tunnel_host
    # collides because another admin request raced ahead, fall back to UPDATE.
    ht = await _get_host_tunnel(db, host.id)
    if ht is None:
        ht = ManagerHostTunnel(
            host_id=host.id,
            cf_account_id=cf_account_id,
            cf_api_token_enc=token_enc,
            cf_zone_id=cf_zone_id,
            cf_zone_name=cf_zone_name,
        )
        db.add(ht)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            ht = await _get_host_tunnel(db, host.id)
            if ht is None:  # pragma: no cover — unreachable race window
                raise

    # Detect account/zone change → drop CF tunnel association.
    account_or_zone_changed = (
        ht.cf_account_id != cf_account_id
        or ht.cf_zone_id != cf_zone_id
    )
    ht.cf_account_id = cf_account_id
    ht.cf_api_token_enc = token_enc
    ht.cf_zone_id = cf_zone_id
    ht.cf_zone_name = cf_zone_name
    ht.last_error = None
    if account_or_zone_changed:
        # Old CF tunnel is bound to the old account/zone and is no longer
        # reachable with the new credentials. Wipe it from our record;
        # admin must run install again to create a fresh CF tunnel.
        ht.cf_tunnel_id = None
        ht.cf_tunnel_name = None
        ht.cf_tunnel_secret_enc = None
        ht.cf_config_version = None
        ht.cloudflared_version = None
        ht.last_synced_at = None

    await db.commit()
    await db.refresh(ht)
    return ht


# ---------------------------------------------------------------------------
# Install / uninstall (Phase 1 main entry points)
# ---------------------------------------------------------------------------


async def install_tunnel(
    db: AsyncSession, host: ManagerHost, *, host_lan_ip: str | None = None,
) -> ManagerHostTunnel:
    """Create the CF tunnel (if needed) and push initial config to the agent.

    Idempotent: if ``cf_tunnel_id`` is already set we skip CF creation and
    only re-push config. ``host_lan_ip`` defaults to the host's stored LAN
    address (resolved from agent_endpoint host part).

    Order of operations:
        1. **CF**: create remote-managed tunnel (POST cfd_tunnel)
        2. **DB**: persist tunnel_id + secret immediately
        3. **Agent**: install cloudflared, write minimal config (no ingress)
        4. **CF**: PUT initial empty ingress (or current rebuild) so source=cloudflare
        5. **DB**: mark status=ready, persist cf_config_version

    On any failure we set ``last_error``; admin can retry. There is no
    persistent ``status`` field — readiness is recomputed live from the
    agent on every read.
    """
    ht = await _require_host_tunnel(db, host.id)
    cf = _build_cf_client(ht)

    # Step 1: create CF tunnel if absent. The tunnel name is deterministic
    # (``erocraft-host-{id}-{name}``) so concurrent install attempts
    # collide on CF — we detect the collision by listing tunnels with the
    # same name. Adoption is unsafe (CF only returns the tunnel secret on
    # the original create call), so on collision we DELETE the existing
    # tunnel and re-raise; the next retry will create a fresh one with a
    # usable secret. (See audit C1 + AUDIT_REVIEW_20260428.md.)
    if not ht.cf_tunnel_id:
        tunnel_name = _tunnel_name_for_host(host)
        try:
            tunnel, secret_b64 = await cf.create_tunnel(tunnel_name)
        except CloudflareAPIError as exc:
            existing = await _find_existing_tunnel_by_name(cf, tunnel_name)
            if existing is not None:
                # Adoption is unsafe: CF only returns the tunnel secret on
                # the original create call, so an adopted tunnel can never
                # produce valid credentials. Rather than persisting a half-
                # broken cf_tunnel_id (which makes every retry skip create
                # and fail at build_credentials_payload), we DELETE the
                # remote tunnel and re-raise so the next retry creates a
                # fresh one. This requires the CF API token to have
                # cfd_tunnel:edit, which is the same scope used for create.
                # (Audit C1.)
                try:
                    await cf.delete_tunnel(existing.id)
                    ht.last_error = (
                        "stale CF tunnel with the same name was deleted; "
                        "please retry install"
                    )
                except CloudflareAPIError as del_exc:
                    # Could not delete (tunnel has active connections, or
                    # token lacks delete scope) — record orphan + tell admin
                    # to remove it from the CF Dashboard, which IS now safe
                    # because we never persisted cf_tunnel_id.
                    await _record_orphan_tunnel(
                        db,
                        cf_account_id=ht.cf_account_id,
                        cf_resource_id=existing.id,
                        cf_resource_name=existing.name,
                        notes=f"adoption rollback failed: {del_exc}",
                    )
                    ht.last_error = (
                        f"a CF tunnel named {existing.name!r} already exists "
                        f"and could not be auto-deleted ({del_exc}); "
                        "please remove it manually in the Cloudflare "
                        "Dashboard, then retry install"
                    )
                await db.commit()
            else:
                ht.last_error = f"create_tunnel failed: {exc}"
                await db.commit()
            raise

        # Step 2: persist immediately so we never have a CF tunnel without a DB row
        ht.cf_tunnel_id = tunnel.id
        ht.cf_tunnel_name = tunnel.name
        ht.cf_tunnel_secret_enc = encrypt_value(secret_b64, _get_encryption_secret())
        ht.last_error = None
        await db.commit()
        await db.refresh(ht)

    # Step 3+: agent install + minimal config + initial CF ingress push are
    # orchestrated by the admin router because they require agent_client
    # (which lives outside the pure service). The router calls
    # :func:`build_credentials_payload`, then `mark_install_complete`.
    return ht


def build_credentials_payload(
    host_tunnel: ManagerHostTunnel,
) -> dict[str, Any]:
    """Return the payload for the ``cloudflared.write_config_minimal`` agent command.

    Builds the credentials JSON cloudflared needs to authenticate to CF.
    Ingress is **not** included — it lives on CF in remote-managed mode.
    """
    if not host_tunnel.cf_tunnel_id or not host_tunnel.cf_tunnel_secret_enc:
        raise HostTunnelNotReady("tunnel has not been created on Cloudflare yet")

    secret_b64 = decrypt_value(host_tunnel.cf_tunnel_secret_enc, _get_encryption_secret())
    credentials_b64 = _build_credentials_b64(
        account_tag=host_tunnel.cf_account_id,
        tunnel_id=host_tunnel.cf_tunnel_id,
        tunnel_secret_b64=secret_b64,
    )
    return {
        "tunnel_id": host_tunnel.cf_tunnel_id,
        "credentials_b64": credentials_b64,
        "protocol": "http2",
    }


async def push_remote_ingress(
    db: AsyncSession,
    host_tunnel: ManagerHostTunnel,
    *,
    host_lan_ip: str,
) -> int:
    """Rebuild ingress from current ``manager_server_tunnels`` and PUT to CF.

    Returns the new ``cf_config_version`` (CF's monotonically-incrementing
    config version). Persists it on ``host_tunnel.cf_config_version`` and
    bumps ``last_synced_at``.

    cloudflared receives the new config via long-poll within ~1s and applies
    it in-process — no restart, no connection drops.
    """
    if not host_tunnel.cf_tunnel_id:
        raise HostTunnelNotReady("tunnel has not been created on Cloudflare yet")

    # Active server tunnels — order_by id for deterministic ingress order.
    res = await db.execute(
        select(ManagerServerTunnel)
        .where(
            ManagerServerTunnel.host_tunnel_id == host_tunnel.id,
            ManagerServerTunnel.status == "active",
        )
        .order_by(ManagerServerTunnel.id)
    )
    active = list(res.scalars())
    ingress = build_ingress(active, host_lan_ip=host_lan_ip)
    payload = [r.model_dump(exclude_none=True) for r in ingress]

    cf = _build_cf_client(host_tunnel)
    result = await cf.put_tunnel_configuration(
        host_tunnel.cf_tunnel_id, ingress=payload,
    )
    version = int(result.get("version") or 0)

    host_tunnel.cf_config_version = version
    host_tunnel.last_synced_at = utc_naive_now()
    host_tunnel.last_error = None
    await db.commit()
    return version


def _build_credentials_b64(
    *, account_tag: str, tunnel_id: str, tunnel_secret_b64: str,
) -> str:
    """Build the base64-encoded cloudflared credentials JSON.

    All three components are validated against tight regexes before being
    serialised so a corrupted DB row produces a clear error instead of a
    silent malformed credentials file.

    cloudflared expects a file with shape::

        {"AccountTag":"...","TunnelID":"...","TunnelSecret":"..."}

    where ``TunnelSecret`` is the base64 secret returned by CF on creation.
    """
    if not _CF_ID_RE.fullmatch(account_tag):
        raise ValueError(f"invalid CF account_tag format: {account_tag!r}")
    if not _CF_TUNNEL_UUID_RE.fullmatch(tunnel_id):
        raise ValueError(f"invalid CF tunnel_id format: {tunnel_id!r}")
    if len(tunnel_secret_b64) < 40 or len(tunnel_secret_b64) > 256:
        raise ValueError("tunnel_secret length out of range")

    blob = json.dumps({
        "AccountTag": account_tag,
        "TunnelID": tunnel_id,
        "TunnelSecret": tunnel_secret_b64,
    }, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(blob).decode("ascii")


async def mark_install_complete(
    db: AsyncSession,
    host_tunnel: ManagerHostTunnel,
    *,
    cloudflared_version: str | None,
    cf_config_version: int | None = None,
) -> None:
    """Called by the router after the install pipeline succeeds.

    Records the version cloudflared reported, the CF config version we
    last pushed, and clears ``last_error``. There is no persistent
    "ready" flag — readiness is read live from the agent.
    """
    host_tunnel.cloudflared_version = cloudflared_version
    if cf_config_version is not None:
        host_tunnel.cf_config_version = cf_config_version
    host_tunnel.last_synced_at = utc_naive_now()
    host_tunnel.last_error = None
    await db.commit()


async def mark_install_failed(
    db: AsyncSession, host_tunnel: ManagerHostTunnel, error: str,
) -> None:
    """Record the install failure reason. No persistent status flag."""
    host_tunnel.last_error = error[:1024]
    await db.commit()


async def _find_existing_tunnel_by_name(
    cf: CloudflareClient, name: str,
):
    """Return the live (non-deleted) CF tunnel matching ``name`` or None."""
    try:
        tunnels = await cf.list_tunnels(name=name, is_deleted=False)
    except CloudflareAPIError:
        return None
    return tunnels[0] if tunnels else None


# ---------------------------------------------------------------------------
# Phase 2: per-server enable / disable / change subdomain
# ---------------------------------------------------------------------------


_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")


def _generated_subdomain(server_uuid_short: str) -> str:
    """Default subdomain derived from server uuid_short (8 chars)."""
    return f"s-{server_uuid_short.lower()}"


def _normalize_subdomain(value: str | None, fallback: str) -> str:
    if not value or not value.strip():
        return fallback
    v = value.strip().lower()
    if not _SUBDOMAIN_RE.fullmatch(v):
        raise InvalidSubdomain(f"invalid subdomain format: {value!r}")
    return v


async def _get_server_tunnel(
    db: AsyncSession, server_id: int,
) -> ManagerServerTunnel | None:
    res = await db.execute(
        select(ManagerServerTunnel).where(
            ManagerServerTunnel.server_id == server_id,
        )
    )
    return res.scalar_one_or_none()


async def get_server_tunnel(
    db: AsyncSession, server_id: int,
) -> ManagerServerTunnel | None:
    """Public accessor for routers to look up a per-server tunnel row."""
    return await _get_server_tunnel(db, server_id)


async def enable_server_tunnel(
    db: AsyncSession,
    *,
    server_id: int,
    server_uuid_short: str,
    upstream_port: int,
    host_tunnel: ManagerHostTunnel,
    custom_subdomain: str | None = None,
) -> ManagerServerTunnel:
    """Create CF DNS + DB row for a per-server tunnel.

    Caller must:
        * Ensure ``host_tunnel.cf_tunnel_id is not None`` (CF tunnel exists).
        * After this returns, push the rebuilt ingress to CF
          (``push_remote_ingress``).

    Idempotent: if a row already exists in ``active`` state for the same
    server, returns it unchanged.
    """
    if not host_tunnel.cf_tunnel_id:
        raise HostTunnelNotReady("host tunnel not installed")

    existing = await _get_server_tunnel(db, server_id)
    if existing is not None and existing.status == "active":
        return existing

    subdomain = _normalize_subdomain(
        custom_subdomain, _generated_subdomain(server_uuid_short),
    )
    hostname = f"{subdomain}.{host_tunnel.cf_zone_name}"

    # Pre-check for hostname collision so we don't create CF DNS in vain.
    res = await db.execute(
        select(ManagerServerTunnel).where(
            ManagerServerTunnel.hostname == hostname,
        )
    )
    other = res.scalar_one_or_none()
    if other is not None and other.server_id != server_id:
        raise HostnameConflict(f"hostname {hostname!r} is already in use")

    cf = _build_cf_client(host_tunnel)
    cname_target = f"{host_tunnel.cf_tunnel_id}.cfargotunnel.com"
    record = await cf.create_dns_record(
        host_tunnel.cf_zone_id,
        name=hostname,
        content=cname_target,
        type="CNAME",
        proxied=True,
    )

    custom_norm = (
        (custom_subdomain or "").strip().lower() or None
    )

    if existing is None:
        st = ManagerServerTunnel(
            server_id=server_id,
            host_tunnel_id=host_tunnel.id,
            hostname=hostname,
            custom_subdomain=custom_norm,
            upstream_port=upstream_port,
            upstream_scheme="http",
            cf_dns_record_id=record.id,
            status="active",
            enabled_at=utc_naive_now(),
            last_synced_at=utc_naive_now(),
        )
        db.add(st)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            # Rollback CF side
            try:
                await cf.delete_dns_record(host_tunnel.cf_zone_id, record.id)
            except Exception:  # noqa: BLE001
                pass
            raise HostnameConflict(
                f"hostname {hostname!r} just got taken (race)"
            )
    else:
        existing.hostname = hostname
        existing.custom_subdomain = custom_norm
        existing.upstream_port = upstream_port
        existing.cf_dns_record_id = record.id
        existing.status = "active"
        existing.last_error = None
        existing.enabled_at = utc_naive_now()
        existing.last_synced_at = utc_naive_now()
        st = existing

    await db.commit()
    await db.refresh(st)
    return st


async def change_server_subdomain(
    db: AsyncSession,
    *,
    server_tunnel: ManagerServerTunnel,
    host_tunnel: ManagerHostTunnel,
    new_subdomain: str,
) -> ManagerServerTunnel:
    """Change a server tunnel's subdomain.

    Order: create new DNS → swap DB → delete old DNS (best-effort).
    Caller must push the rebuilt ingress to CF afterward.
    """
    if not host_tunnel.cf_tunnel_id:
        raise HostTunnelNotReady("host tunnel not installed")

    new_norm = _normalize_subdomain(new_subdomain, "")
    if not new_norm:
        raise InvalidSubdomain("subdomain cannot be empty")
    new_hostname = f"{new_norm}.{host_tunnel.cf_zone_name}"

    if new_hostname == server_tunnel.hostname:
        return server_tunnel

    res = await db.execute(
        select(ManagerServerTunnel).where(
            ManagerServerTunnel.hostname == new_hostname,
        )
    )
    other = res.scalar_one_or_none()
    if other is not None and other.id != server_tunnel.id:
        raise HostnameConflict(f"hostname {new_hostname!r} is already in use")

    cf = _build_cf_client(host_tunnel)
    cname_target = f"{host_tunnel.cf_tunnel_id}.cfargotunnel.com"
    new_record = await cf.create_dns_record(
        host_tunnel.cf_zone_id,
        name=new_hostname,
        content=cname_target,
        type="CNAME",
        proxied=True,
    )

    old_record_id = server_tunnel.cf_dns_record_id
    old_hostname = server_tunnel.hostname
    server_tunnel.hostname = new_hostname
    server_tunnel.custom_subdomain = new_norm
    server_tunnel.cf_dns_record_id = new_record.id
    server_tunnel.status = "active"
    server_tunnel.last_synced_at = utc_naive_now()
    server_tunnel.last_error = None
    try:
        await db.commit()
    except IntegrityError:
        # Rollback the failed transaction so the session is reusable for the
        # subsequent CF cleanup + caller's later DB ops. Without rollback the
        # AsyncSession stays in "transaction failed" state and any later
        # query raises PendingRollbackError. (See audit H4.)
        await db.rollback()
        try:
            await cf.delete_dns_record(host_tunnel.cf_zone_id, new_record.id)
        except Exception as exc:  # noqa: BLE001
            # Cleanup failed → record orphan so admin can intervene instead
            # of silently leaving a stray DNS record on Cloudflare. (Audit M10.)
            try:
                await _record_orphan_dns(
                    db,
                    cf_account_id=host_tunnel.cf_account_id,
                    cf_resource_id=new_record.id,
                    cf_resource_name=new_hostname,
                    notes=f"rename rollback DNS cleanup failed: {exc}",
                )
                await db.commit()
            except Exception:  # noqa: BLE001
                await db.rollback()
        raise HostnameConflict(
            f"hostname {new_hostname!r} just got taken (race)"
        )
    await db.refresh(server_tunnel)

    if old_record_id:
        try:
            await cf.delete_dns_record(host_tunnel.cf_zone_id, old_record_id)
        except CloudflareAPIError as exc:
            await _record_orphan_dns(
                db,
                cf_account_id=host_tunnel.cf_account_id,
                cf_resource_id=old_record_id,
                cf_resource_name=old_hostname,
                notes=f"old DNS during subdomain change: {exc}",
            )
            await db.commit()

    return server_tunnel


async def disable_server_tunnel(
    db: AsyncSession,
    *,
    server_tunnel: ManagerServerTunnel,
    host_tunnel: ManagerHostTunnel,
) -> None:
    """Delete CF DNS + DB row for a server tunnel.

    Caller must push the rebuilt ingress to CF afterward.
    If the CF DNS deletion fails we record an orphan and proceed with
    DB deletion (so the user-facing flow still completes).
    """
    if server_tunnel.cf_dns_record_id:
        cf = _build_cf_client(host_tunnel)
        try:
            await cf.delete_dns_record(
                host_tunnel.cf_zone_id, server_tunnel.cf_dns_record_id,
            )
        except CloudflareAPIError as exc:
            await _record_orphan_dns(
                db,
                cf_account_id=host_tunnel.cf_account_id,
                cf_resource_id=server_tunnel.cf_dns_record_id,
                cf_resource_name=server_tunnel.hostname,
                notes=f"disable: {exc}",
            )

    await db.delete(server_tunnel)
    await db.commit()


async def rollback_server_tunnel_after_push_failure(
    db: AsyncSession,
    *,
    server_tunnel: ManagerServerTunnel,
    host_tunnel: ManagerHostTunnel,
) -> None:
    """Undo a freshly created (or just-renamed) server tunnel after the CF
    ingress PUT failed.

    Removes CF DNS + DB row so the user can safely retry without leaving
    behind an orphaned hostname that resolves to nowhere (CF Error 1033).
    See B7 in CF_TUNNEL_LOGIC_AUDIT.md.
    """
    await disable_server_tunnel(
        db, server_tunnel=server_tunnel, host_tunnel=host_tunnel,
    )


async def _record_orphan_dns(
    db: AsyncSession,
    *,
    cf_account_id: str,
    cf_resource_id: str,
    cf_resource_name: str,
    notes: str | None = None,
) -> None:
    res = await db.execute(
        select(ManagerOrphanResource).where(
            ManagerOrphanResource.resource_type == "dns",
            ManagerOrphanResource.cf_resource_id == cf_resource_id,
        )
    )
    if res.scalar_one_or_none() is not None:
        return
    db.add(ManagerOrphanResource(
        resource_type="dns",
        cf_account_id=cf_account_id,
        cf_resource_id=cf_resource_id,
        cf_resource_name=cf_resource_name,
        notes=notes,
    ))


async def on_server_pre_delete(db: AsyncSession, server_id: int) -> None:
    """Hook called by ``app.services.server_lifecycle.delete_server`` before
    the panel server row is removed.

    Best-effort cleanup: removes CF DNS + DB row. Failures are logged but
    must not block server deletion (the reconciler will catch leftovers).
    """
    st = await _get_server_tunnel(db, server_id)
    if st is None:
        return
    res = await db.execute(
        select(ManagerHostTunnel).where(
            ManagerHostTunnel.id == st.host_tunnel_id,
        )
    )
    ht = res.scalar_one_or_none()
    if ht is None:
        await db.delete(st)
        await db.commit()
        return
    try:
        await disable_server_tunnel(db, server_tunnel=st, host_tunnel=ht)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "on_server_pre_delete: failed to disable server tunnel "
            "for server %s: %s",
            server_id, exc,
        )
        st.status = "deleted"
        st.last_error = str(exc)[:1024]
        await db.commit()


async def uninstall_tunnel(
    db: AsyncSession, host: ManagerHost, *, force: bool = False,
) -> dict[str, Any]:
    """Tear down the host's CF tunnel + DB row.

    Order (design §8b):
        1. **DB**: refuse if any active server_tunnels (unless ``force``).
        2. **DB**: mark status=disabling.
        3. **Agent**: stop & remove cloudflared (caller's responsibility,
           because it requires agent_client).
        4. **CF**: delete tunnel.
        5. **DB**: delete row.

    If the agent is unreachable we still delete on CF + DB (the agent will
    eventually come back with stale config, and the next sync will clean up).
    Returns metadata for the caller to log + decide on agent step.
    """
    ht = await _get_host_tunnel(db, host.id)
    if ht is None:
        return {"ok": True, "noop": True}

    if not force:
        res = await db.execute(
            select(ManagerServerTunnel).where(
                ManagerServerTunnel.host_tunnel_id == ht.id,
                ManagerServerTunnel.status == "active",
            ).limit(1)
        )
        if res.scalar_one_or_none() is not None:
            raise TunnelManagerError(
                "cannot uninstall: host has active server tunnels (use force=True)"
            )

    ht.last_error = None
    await db.commit()
    return {
        "ok": True,
        "host_tunnel_id": ht.id,
        "cf_tunnel_id": ht.cf_tunnel_id,
    }


async def finalize_uninstall(
    db: AsyncSession, host_tunnel: ManagerHostTunnel,
) -> None:
    """Step 4-5 of uninstall: delete from CF, then delete DB row.

    Called by the router after the agent has stopped cloudflared.
    """
    if host_tunnel.cf_tunnel_id:
        cf = _build_cf_client(host_tunnel)
        try:
            await cf.delete_tunnel(host_tunnel.cf_tunnel_id)
        except CloudflareAPIError as exc:
            # Record orphan and rethrow — admin must intervene
            await _record_orphan_tunnel(
                db,
                cf_account_id=host_tunnel.cf_account_id,
                cf_resource_id=host_tunnel.cf_tunnel_id,
                cf_resource_name=host_tunnel.cf_tunnel_name or "",
                notes=f"uninstall failed: {exc}",
            )
            await db.commit()
            raise

    await db.delete(host_tunnel)
    await db.commit()


async def _record_orphan_tunnel(
    db: AsyncSession,
    *,
    cf_account_id: str,
    cf_resource_id: str,
    cf_resource_name: str,
    notes: str | None = None,
) -> None:
    """Insert an orphan-resource row, ignoring duplicates."""
    res = await db.execute(
        select(ManagerOrphanResource).where(
            ManagerOrphanResource.resource_type == "tunnel",
            ManagerOrphanResource.cf_resource_id == cf_resource_id,
        )
    )
    if res.scalar_one_or_none() is not None:
        return
    db.add(ManagerOrphanResource(
        resource_type="tunnel",
        cf_account_id=cf_account_id,
        cf_resource_id=cf_resource_id,
        cf_resource_name=cf_resource_name,
        notes=notes,
    ))


# ---------------------------------------------------------------------------
# CF token helpers (used by zone-listing endpoint pre-bind)
# ---------------------------------------------------------------------------


async def list_zones_for_token(
    *, cf_account_id: str, cf_api_token: str,
) -> list[dict[str, Any]]:
    """Return zones visible to the given token (pre-bind UI helper).

    Also verifies the ``cf_account_id`` is accessible to the token — the
    token-verify endpoint alone doesn't catch a wrong account_id, but the
    install flow needs ``/accounts/{id}/cfd_tunnel`` so we must validate
    here or the user gets a confusing 502 later.
    """
    client = CloudflareClient(cf_account_id, cf_api_token)
    await client.verify_token()
    await client.verify_account_access()
    zones = await client.list_zones()
    return [z.model_dump() for z in zones]
