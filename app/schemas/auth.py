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
    has_owned_server: bool = False
    language: str = "zh"


class MeResponse(BaseModel):
    ok: bool
    username: str
    is_admin: bool
    has_owned_server: bool = False
    language: str = "zh"


class LogoutResponse(BaseModel):
    ok: bool
