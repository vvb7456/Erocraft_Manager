"""Typed exceptions for tunnel_manager.

All non-trivial failures should surface as one of these so the router layer
can translate them to HTTP status codes consistently. Anything else bubbles
as a 500.
"""

from __future__ import annotations


class TunnelManagerError(Exception):
    """Base for all tunnel_manager errors."""


# ---------------------------------------------------------------------------
# Cloudflare API errors
# ---------------------------------------------------------------------------


class CloudflareAPIError(TunnelManagerError):
    """Generic CF API failure (non-2xx with no more specific subclass)."""

    def __init__(self, message: str, *, status_code: int = 0, cf_errors: list | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.cf_errors = cf_errors or []


class CloudflareAuthError(CloudflareAPIError):
    """CF API returned 401/403 — token invalid or insufficient scope."""


class CloudflareNotFound(CloudflareAPIError):
    """CF API returned 404 — resource doesn't exist (treat as success on delete)."""


class CloudflareRateLimited(CloudflareAPIError):
    """CF API returned 429 after retries — caller should back off."""


# ---------------------------------------------------------------------------
# Domain logic errors
# ---------------------------------------------------------------------------


class HostnameConflict(TunnelManagerError):
    """The requested hostname is already in use on the CF zone (live check)."""


class HostTunnelNotConfigured(TunnelManagerError):
    """The host has no manager_host_tunnels row (admin hasn't bound CF yet)."""


class HostTunnelNotReady(TunnelManagerError):
    """The host_tunnel exists but cloudflared isn't ready (status != ready)."""


class InvalidSubdomain(TunnelManagerError):
    """User-supplied subdomain failed the format/RESERVED check."""
