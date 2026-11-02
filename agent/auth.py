"""FastAPI dependencies: Bearer token auth + optional IP allowlist."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status

from .config import AgentConfig


def make_auth_dependency(cfg: AgentConfig):
    expected = cfg.agent.token
    expected_bytes = expected.encode("utf-8")
    allow_ips = set(cfg.agent.allow_ips or [])

    async def _auth(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        if allow_ips:
            client_ip = request.client.host if request.client else None
            if client_ip not in allow_ips:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="ip not allowed",
                )
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
            )
        token = authorization[len("Bearer ") :].strip()
        # Constant-time comparison to defeat remote timing oracles that could
        # otherwise leak the token byte-by-byte through response-time deltas.
        if not hmac.compare_digest(token.encode("utf-8"), expected_bytes):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid token",
            )

    return _auth
