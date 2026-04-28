"""Pydantic schemas for tunnel_manager API + agent payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Cloudflare API response shapes (only fields we care about)
# ---------------------------------------------------------------------------


class CFZone(BaseModel):
    id: str
    name: str
    status: str | None = None


class CFTunnel(BaseModel):
    id: str
    name: str
    account_tag: str | None = None
    deleted_at: datetime | None = None
    connections: list[dict] | None = None


class CFDNSRecord(BaseModel):
    id: str
    type: str
    name: str
    content: str
    proxied: bool = False


# ---------------------------------------------------------------------------
# Admin API responses
# ---------------------------------------------------------------------------


class HostTunnelDetail(BaseModel):
    """Returned by ``GET /api/admin/hosts/{id}/tunnel``."""

    host_id: int
    cf_account_id: str
    cf_zone_id: str
    cf_zone_name: str
    cf_tunnel_id: str | None
    cf_tunnel_name: str | None
    cloudflared_version: str | None
    cf_config_version: int | None
    last_synced_at: datetime | None
    last_error: str | None
    # Live signals from agent (best-effort; null when probe failed).
    cloudflared_live_active: bool | None = None
    cloudflared_live_unit_present: bool | None = None
    cloudflared_live_version: str | None = None
    cloudflared_live_error: str | None = None
    server_tunnel_count: int = 0
    created_at: datetime
    updated_at: datetime


class HostTunnelBindRequest(BaseModel):
    """Body for ``PUT /api/admin/hosts/{id}/tunnel``."""

    cf_account_id: str = Field(min_length=1, max_length=64)
    cf_api_token: str = Field(min_length=20, max_length=512)
    cf_zone_id: str = Field(min_length=1, max_length=64)
    cf_zone_name: str = Field(min_length=1, max_length=255)


class CFZoneListResponse(BaseModel):
    zones: list[CFZone]


# ---------------------------------------------------------------------------
# Agent payloads
# ---------------------------------------------------------------------------


class IngressRule(BaseModel):
    hostname: str | None = None  # None = catch-all
    service: str
    originRequest: dict | None = None


class CloudflaredConfigMinimalPayload(BaseModel):
    """Payload sent via agent ``cloudflared.write_config_minimal`` command.

    Only writes credentials JSON + a minimal ``config.yml`` (no ingress).
    Ingress is managed remotely by Cloudflare; cloudflared fetches it on
    startup and receives push updates thereafter.
    """

    tunnel_id: str
    credentials_b64: str
    protocol: str = "http2"


class CloudflaredStatus(BaseModel):
    """Returned by agent ``cloudflared.status`` command."""

    installed: bool
    version: str | None = None
    active: bool = False
    last_log_ts: datetime | None = None
