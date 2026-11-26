"""One-shot in-memory force-reinstall tokens consumed on GET /api/remote/servers/{uuid}/install."""

from __future__ import annotations

import time
import uuid

FORCE_REINSTALL_TTL_SECONDS: float = 120.0
_MAX_PENDING_TOKENS: int = 4096

# server_uuid -> (opaque_token, monotonic_deadline)
_pending_force_reinstall: dict[str, tuple[str, float]] = {}


def issue_force_reinstall_token(
    server_uuid: str,
    ttl_seconds: float = FORCE_REINSTALL_TTL_SECONDS,
) -> str:
    now = time.monotonic()
    for uid in [u for u, (_, deadline) in _pending_force_reinstall.items() if deadline <= now]:
        _pending_force_reinstall.pop(uid, None)
    if len(_pending_force_reinstall) >= _MAX_PENDING_TOKENS and server_uuid not in _pending_force_reinstall:
        overflow = len(_pending_force_reinstall) - _MAX_PENDING_TOKENS + 1
        for uid, _ in sorted(_pending_force_reinstall.items(), key=lambda item: item[1][1])[:overflow]:
            _pending_force_reinstall.pop(uid, None)
    token = uuid.uuid4().hex
    _pending_force_reinstall[server_uuid] = (token, now + ttl_seconds)
    return token


def revoke_force_reinstall_token(server_uuid: str, *, token: str | None = None) -> None:
    if token is None:
        _pending_force_reinstall.pop(server_uuid, None)
        return
    entry = _pending_force_reinstall.get(server_uuid)
    if entry is not None and entry[0] == token:
        _pending_force_reinstall.pop(server_uuid, None)


def consume_force_reinstall_token(server_uuid: str) -> bool:
    entry = _pending_force_reinstall.pop(server_uuid, None)
    return entry is not None and entry[1] > time.monotonic()


def clear_all_force_reinstall_tokens() -> None:
    _pending_force_reinstall.clear()


__all__ = [
    "FORCE_REINSTALL_TTL_SECONDS",
    "issue_force_reinstall_token",
    "revoke_force_reinstall_token",
    "consume_force_reinstall_token",
    "clear_all_force_reinstall_tokens",
]
