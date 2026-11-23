"""Project-wide rate limiter (slowapi).

We sit behind an nginx reverse proxy that injects ``X-Real-IP`` from
``$remote_addr`` (the actual TCP peer). That header is therefore the
only client-IP source we can trust. ``X-Forwarded-For`` is built by
nginx from ``$proxy_add_x_forwarded_for``, which **appends** the trusted
remote address to whatever the client supplied — meaning the left-most
entry is attacker-controlled and must not be used as a rate-limit key.
"""

from __future__ import annotations

import ipaddress

from slowapi import Limiter
from starlette.requests import Request


def extract_client_ip(request: Request | None, *, fallback: str = "unknown") -> str:
    """Return the trusted client IP from nginx ``X-Real-IP`` (falling back to TCP peer).

    Never reads ``X-Forwarded-For`` because nginx appends to client-supplied values,
    making the left-most entry attacker-controlled.
    """
    if request is not None:
        real = request.headers.get("x-real-ip")
        if real:
            candidate = real.strip()
            if candidate:
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    pass

        if request.client and request.client.host:
            host = request.client.host.strip()
            try:
                return str(ipaddress.ip_address(host))
            except ValueError:
                if host:
                    return host[:64]

    return fallback


def _client_ip(request: Request) -> str:
    return extract_client_ip(request, fallback="unknown")


limiter = Limiter(key_func=_client_ip, headers_enabled=False)
