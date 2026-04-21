"""Command handlers. Phase 1 only ping."""

from __future__ import annotations


async def ping(params: dict) -> str:
    return "pong"
