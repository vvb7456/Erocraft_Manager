from __future__ import annotations

import re

from fastapi import status

from app.core.api_errors import ApiError

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")


def normalize_username(raw: str) -> str:
    username = raw.strip()
    if not USERNAME_RE.match(username):
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "register.invalid_username")
    return username


def normalize_email(raw: str) -> str:
    return str(raw).strip().lower()
