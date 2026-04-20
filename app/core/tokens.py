"""Shared token hashing utilities for password reset and email change."""

from __future__ import annotations

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
