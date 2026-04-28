"""Cloudflare Tunnel orchestration package — see ``docs/CLOUDFLARE_TUNNEL_DESIGN.md``.

Submodules:

* :mod:`cf_client` — typed httpx wrapper around the Cloudflare API
  (account-scoped operations: tunnels + DNS records + zone listing).
* :mod:`ingress_builder` — pure function that builds the cloudflared
  ``config.yml`` ingress list from current ``manager_server_tunnels`` rows.
* :mod:`dispatcher` — high-level orchestration: bind/install/sync/uninstall
  on the admin side and (Phase 2) enable/disable/refresh on the user side.
  All flows enforce the "CF resources >= DB resources" invariant via
  CF-first / DB-second writes with rollback (see design §8b).
* :mod:`schemas` — Pydantic models for API responses + agent payloads.
* :mod:`exceptions` — typed exception hierarchy for HTTP router translation.
"""

from .exceptions import (
    TunnelManagerError,
    CloudflareAPIError,
    CloudflareAuthError,
    CloudflareNotFound,
    CloudflareRateLimited,
    HostnameConflict,
    HostTunnelNotConfigured,
    HostTunnelNotReady,
    InvalidSubdomain,
)

__all__ = [
    "TunnelManagerError",
    "CloudflareAPIError",
    "CloudflareAuthError",
    "CloudflareNotFound",
    "CloudflareRateLimited",
    "HostnameConflict",
    "HostTunnelNotConfigured",
    "HostTunnelNotReady",
    "InvalidSubdomain",
]
