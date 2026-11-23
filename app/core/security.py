"""Security helpers for sessions and encrypted settings."""

from __future__ import annotations

import hmac
from base64 import urlsafe_b64encode
from collections.abc import MutableMapping
from hashlib import sha256
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

SESSION_USER_ID_KEY = "user_id"
SESSION_AUTH_FINGERPRINT_KEY = "auth_fp"


def compute_session_fingerprint(password_hash: str, secret: str) -> str:
    """Bind a cookie session to the user's current password hash so password changes invalidate old cookies."""
    return hmac.new(
        secret.encode("utf-8"),
        f"session-fp:{password_hash}".encode("utf-8"),
        sha256,
    ).hexdigest()[:32]


def set_user_session(
    session: MutableMapping[str, Any],
    user_id: int,
    password_hash: str,
    secret: str,
) -> None:
    session.clear()
    session[SESSION_USER_ID_KEY] = int(user_id)
    session[SESSION_AUTH_FINGERPRINT_KEY] = compute_session_fingerprint(password_hash, secret)


def verify_session_fingerprint(
    stored: Any,
    password_hash: str,
    secret: str,
) -> bool:
    if not isinstance(stored, str) or not stored:
        return False
    expected = compute_session_fingerprint(password_hash, secret)
    return hmac.compare_digest(stored, expected)


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
