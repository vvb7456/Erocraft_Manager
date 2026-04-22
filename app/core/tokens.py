"""Shared token hashing utilities for password reset and email change."""

from __future__ import annotations

import asyncio
import hashlib

import bcrypt


def hash_token(raw: str) -> str:
    """Hash a raw token using bcrypt with $2y$ prefix for PHP compatibility."""
    h = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=10)).decode()
    if h.startswith("$2b$"):
        h = "$2y$" + h[4:]
    return h


def verify_token(raw: str, hashed: str) -> bool:
    """Verify a raw token against a bcrypt hash."""
    check_hash = hashed
    if check_hash.startswith("$2y$"):
        check_hash = "$2b$" + check_hash[4:]
    return bcrypt.checkpw(raw.encode(), check_hash.encode())


async def hash_token_async(raw: str) -> str:
    """Async wrapper that runs bcrypt off the event loop."""
    return await asyncio.to_thread(hash_token, raw)


async def verify_token_async(raw: str, hashed: str) -> bool:
    """Async wrapper that runs bcrypt off the event loop."""
    return await asyncio.to_thread(verify_token, raw, hashed)


def compute_lookup_hash(raw: str) -> str:
    """Deterministic, indexable SHA-256 of a raw token.

    Allows O(1) DB lookup without exposing raw tokens in the database. The
    actual authorization decision still uses the bcrypt-hashed ``token``
    column (via ``verify_token``), so a DB dump alone cannot forge a valid
    verification request.
    """
    return hashlib.sha256(raw.encode()).hexdigest()
