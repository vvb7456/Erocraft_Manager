"""Security helpers for sessions and encrypted settings."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

SESSION_USER_ID_KEY = "user_id"


def is_sensitive_setting(key: str) -> bool:
    """Return True if a setting key is declared sensitive in its spec.

    Looked up against the explicit registry built from SettingSpec.sensitive
    flags. Imported lazily to avoid a circular import with runtime_settings.
    """
    from app.core.runtime_settings import SENSITIVE_KEYS
    return key in SENSITIVE_KEYS


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
