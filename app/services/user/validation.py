from __future__ import annotations

import re
from typing import Annotated

from fastapi import status
from pydantic import AfterValidator, Field

from app.core.api_errors import ApiError

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")


def normalize_username(raw: str) -> str:
    username = raw.strip()
    if not USERNAME_RE.match(username):
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "register.invalid_username")
    return username


def normalize_email(raw: str) -> str:
    return str(raw).strip().lower()


def validate_password(password: str) -> str:
    if any(char.isspace() for char in password):
        raise ValueError("密码不能包含空白字符")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")
    return password


NewPassword = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(validate_password)]
