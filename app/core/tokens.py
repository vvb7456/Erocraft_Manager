"""Shared token and email verification code hashing utilities."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from hmac import compare_digest

import bcrypt

VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_EXPIRY_MINUTES = 30
VERIFICATION_CODE_COOLDOWN_SECONDS = 60


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


def generate_verification_code() -> str:
    return f"{secrets.randbelow(10 ** VERIFICATION_CODE_LENGTH):0{VERIFICATION_CODE_LENGTH}d}"


def code_digest(purpose: str, email: str, code: str) -> str:
    # 绑定用途与归一化邮箱后再计算摘要，避免跨场景或跨邮箱复用。
    normalized = f"{purpose}:{email.strip().lower()}:{code.strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def verify_verification_code(purpose: str, email: str, code: str, digest: str) -> bool:
    return compare_digest(code_digest(purpose, email, code), digest)
