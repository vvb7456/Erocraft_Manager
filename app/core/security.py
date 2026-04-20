"""Security helpers for sessions and encrypted settings."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

SESSION_USER_ID_KEY = "user_id"

_SENSITIVE_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


def is_sensitive_setting(key: str) -> bool:
    upper_key = key.upper()
    return any(marker in upper_key for marker in _SENSITIVE_MARKERS)


def _build_fernet(secret: str) -> Fernet:
    digest = sha256(secret.encode("utf-8")).digest()
    return Fernet(urlsafe_b64encode(digest))


def encrypt_value(value: str, secret: str) -> str:
    return _build_fernet(secret).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(value: str, secret: str) -> str:
    try:
        return _build_fernet(secret).decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Invalid encrypted value") from exc
