"""Project-wide rate limiter (slowapi).

We sit behind an nginx reverse proxy that injects ``X-Real-IP`` from
``$remote_addr`` (the actual TCP peer). That header is therefore the
only client-IP source we can trust. ``X-Forwarded-For`` is built by
nginx from ``$proxy_add_x_forwarded_for``, which **appends** the trusted
remote address to whatever the client supplied — meaning the left-most
entry is attacker-controlled and must not be used as a rate-limit key.
"""

from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request


def _client_ip(request: Request) -> str:
    real = request.headers.get("x-real-ip")
    if real:
        ip = real.strip()
        if ip:
            return ip
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_client_ip, headers_enabled=False)
