"""Authentication schema models."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        return value.strip()


class LoginResponse(BaseModel):
    ok: bool
    username: str
    is_admin: bool
    language: str = "en"


class MeResponse(BaseModel):
    ok: bool
    username: str
    is_admin: bool
    language: str = "en"


class LogoutResponse(BaseModel):
    ok: bool
