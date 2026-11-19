"""Daemon Bearer authentication and Pterodactyl-native error model for /api/remote/*."""

from __future__ import annotations

import hmac
import logging
import time
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.db.models.pterodactyl import PanelNode
from app.services.wings import wings_service

logger = logging.getLogger(__name__)

_DECRYPT_CACHE_TTL_SECONDS = 30.0
_DECRYPT_CACHE_MAX_SIZE = 256
# Keyed by ciphertext so token rotation in DB immediately misses without stale-token windows.
_decrypt_cache: dict[str, tuple[str, float]] = {}


def clear_remote_auth_cache() -> None:
    _decrypt_cache.clear()


class WingsRemoteError(Exception):
    """Error formatted in Pterodactyl Panel's native ``{"errors": [...]}`` schema."""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str = "",
        *,
        headers: dict[str, str] | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail or code)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.headers = headers
        self.errors = errors

    def to_payload(self) -> dict[str, list[dict[str, Any]]]:
        if self.errors is not None:
            return {"errors": self.errors}
        return {
            "errors": [
                {
                    "code": self.code,
                    "status": str(self.status_code),
                    "detail": self.detail,
                }
            ]
        }


def remote_validation_error(
    field_errors: list[tuple[str, str, str]],
) -> WingsRemoteError:
    """Build a 422 ValidationException matching Laravel's ``meta: {source_field, rule}``."""
    return WingsRemoteError(
        422,
        "ValidationException",
        errors=[
            {
                "code": "ValidationException",
                "status": "422",
                "detail": detail,
                "meta": {
                    "source_field": source_field,
                    "rule": rule,
                },
            }
            for source_field, rule, detail in field_errors
        ],
    )


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _decrypt_node_token(ciphertext: str) -> str | None:
    now = time.monotonic()
    cached = _decrypt_cache.get(ciphertext)
    if cached is not None and cached[1] > now:
        return cached[0]
    try:
        plaintext = wings_service._decrypt_laravel(ciphertext)
    except Exception:
        logger.warning("Failed to decrypt node daemon_token during remote auth", exc_info=True)
        return None
    if len(_decrypt_cache) >= _DECRYPT_CACHE_MAX_SIZE:
        _decrypt_cache.clear()
    _decrypt_cache[ciphertext] = (plaintext, now + _DECRYPT_CACHE_TTL_SECONDS)
    return plaintext


async def require_wings_node(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PanelNode:
    """Authenticate a Wings daemon request (mirrors ``DaemonAuthenticate.php``)."""
    bearer = _extract_bearer_token(request)
    if bearer is None:
        raise WingsRemoteError(
            401,
            "HttpException",
            "Access to this endpoint must include an Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = bearer.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise WingsRemoteError(
            400,
            "BadRequestHttpException",
            "The Authorization header provided was not in a valid format.",
        )

    token_id, secret = parts
    node = (
        await db.execute(select(PanelNode).where(PanelNode.daemon_token_id == token_id))
    ).scalar_one_or_none()
    if node is not None:
        expected = _decrypt_node_token(node.daemon_token)
        if expected is not None and hmac.compare_digest(expected, secret):
            return node

    raise WingsRemoteError(
        403,
        "AccessDeniedHttpException",
        "You are not authorized to access this resource.",
    )
