"""Validate / normalize Erocraft Agent endpoint URLs (SSRF guard).

Used by:
  - admin_nodes router on write (reject bad input at API boundary)
  - monitoring pull loop on read (defence-in-depth: reject DB rows with
    historically-stored bad values, e.g. inserted before this guard existed)
"""

from __future__ import annotations

from ipaddress import AddressValueError, IPv4Address, IPv6Address, ip_address
from urllib.parse import urlsplit


class AgentEndpointError(ValueError):
    """Raised when an agent endpoint URL fails validation."""


# Cloud / virtualization metadata services & similar magic IPs.  We refuse to
# let the manager process talk to these — even an authenticated admin must not
# be able to point the manager at arbitrary internal infra.
_BLOCKED_HOSTS: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata",  # short-form some clouds accept
        "instance-data",
        "instance-data.ec2.internal",
    }
)

_BLOCKED_IPS: frozenset[str] = frozenset(
    {
        "169.254.169.254",   # AWS / GCP / Azure / DigitalOcean / Aliyun ECS
        "100.100.100.200",   # Aliyun ECS metadata (alternate)
        "100.100.100.100",
        "fd00:ec2::254",     # AWS IPv6 metadata
    }
)


def _is_blocked_ip(host: str) -> bool:
    try:
        ip = ip_address(host)
    except (ValueError, AddressValueError):
        return False
    if str(ip) in _BLOCKED_IPS:
        return True
    # Block link-local entirely — covers 169.254.0.0/16 and IPv6 fe80::/10
    if ip.is_link_local:
        return True
    # Block multicast / unspecified (defensive; agent should never legitimately
    # live there).  Note: we deliberately do NOT block `is_reserved` because
    # IPv6 loopback `::1` flags as reserved in Python's ipaddress lib.
    if ip.is_multicast or ip.is_unspecified:
        return True
    return False


def validate_agent_endpoint(raw: str) -> str:
    """Validate a user-supplied agent endpoint and return a normalized base URL.

    Rules:
      * scheme must be http or https
      * netloc must be present, no userinfo (no `user:pass@`)
      * port (if specified) must be 1..65535
      * path/query/fragment forbidden (only base URL allowed)
      * host must not match cloud metadata hostnames or magic IPs
      * link-local / multicast / unspecified / reserved IPs are rejected

    Returns the cleaned base URL (scheme://host[:port]).
    """
    if not raw or not raw.strip():
        raise AgentEndpointError("endpoint is empty")
    raw = raw.strip().rstrip("/")

    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise AgentEndpointError(f"invalid URL: {exc}") from exc

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise AgentEndpointError("scheme must be http or https")

    if "@" in (parts.netloc or ""):
        raise AgentEndpointError("userinfo (user:pass@) is not allowed in endpoint")

    host = (parts.hostname or "").lower()
    if not host:
        raise AgentEndpointError("missing host")

    if host in _BLOCKED_HOSTS:
        raise AgentEndpointError(f"host '{host}' is blocked (metadata service)")

    if _is_blocked_ip(host):
        raise AgentEndpointError(f"host '{host}' is blocked (metadata / link-local / reserved)")

    try:
        port = parts.port
    except ValueError as exc:
        raise AgentEndpointError(f"invalid port: {exc}") from exc
    if port is not None and not (1 <= port <= 65535):
        raise AgentEndpointError("port out of range")

    if parts.path and parts.path != "/":
        raise AgentEndpointError("endpoint must be a base URL (no path)")
    if parts.query:
        raise AgentEndpointError("endpoint must not contain query string")
    if parts.fragment:
        raise AgentEndpointError("endpoint must not contain fragment")

    netloc_host = f"[{host}]" if ":" in host else host
    netloc = netloc_host if port is None else f"{netloc_host}:{port}"
    return f"{scheme}://{netloc}"
