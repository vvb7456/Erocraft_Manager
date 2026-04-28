"""Build cloudflared ingress lists.

The ingress list is reconstructed deterministically from the current set of
``manager_server_tunnels`` rows for a given host and pushed to Cloudflare via
``PUT /accounts/{aid}/cfd_tunnel/{tid}/configurations``. cloudflared then
receives the new config via long-poll and applies it in-process (no restart).

Per ``docs/CF_REMOTE_MANAGED_TUNNEL_REFACTOR.md``, the **last** rule must be
a catch-all ``http_status:404`` so requests for unknown hostnames are
rejected without a 502.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .schemas import IngressRule

# RFC 1035-ish hostname check: each label 1-63 chars of [a-z0-9-], no leading
# or trailing hyphen. Total length capped at 253. We accept lower-case only
# because CF normalises everything to lower-case anyway.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$"
)


def _validate_hostname(hostname: str) -> str:
    if not _HOSTNAME_RE.fullmatch(hostname):
        raise ValueError(f"invalid hostname for ingress: {hostname!r}")
    return hostname


def _validate_port(port: int) -> int:
    if not (1 <= port <= 65535):
        raise ValueError(f"upstream_port out of range (1-65535): {port}")
    return port


def build_ingress(server_tunnels: Iterable, *, host_lan_ip: str) -> list[IngressRule]:
    """Build the ingress list for one host.

    Parameters
    ----------
    server_tunnels:
        Iterable of :class:`app.db.models.manager.ManagerServerTunnel` rows
        whose ``status`` is ``"active"`` (suspended/disabled rows must be
        filtered out by the caller).
    host_lan_ip:
        The LAN IP of the wings host (e.g. ``"127.0.0.1"`` for same-box,
        ``"10.0.0.23"`` for a remote node). Used as the upstream host.

    Each ``hostname`` and ``upstream_port`` is validated before being
    written into the YAML so a bad DB row never reaches cloudflared
    where it would either crash the daemon or accept malicious input.
    """
    rules: list[IngressRule] = []
    for st in server_tunnels:
        scheme = (getattr(st, "upstream_scheme", "http") or "http").lower()
        port = _validate_port(int(st.upstream_port))
        hostname = _validate_hostname(str(st.hostname))
        rules.append(IngressRule(
            hostname=hostname,
            service=f"{scheme}://{host_lan_ip}:{port}",
            originRequest={
                "noTLSVerify": True,
                # CF REST API expects connectTimeout as an integer number of
                # seconds (NOT a Go duration string like "10s" — that form is
                # only valid in cloudflared's local YAML config).
                "connectTimeout": 10,
            },
        ))
    # Mandatory catch-all
    rules.append(IngressRule(hostname=None, service="http_status:404"))
    return rules
