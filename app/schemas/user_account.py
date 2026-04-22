"""Schemas for user account self-service routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserAccountProfileResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    language: str = "en"


class UpdateUserAccountRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(min_length=8, max_length=72)


class UpdateUserAccountResponse(BaseModel):
    message: str
    user: UserAccountProfileResponse


class UpdateLanguageRequest(BaseModel):
    language: Literal["en", "zh"]