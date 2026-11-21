"""Schemas for user account self-service routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.services.user.validation import NewPassword


class UserAccountProfileResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    language: str = "zh"


class UpdateUserAccountRequest(BaseModel):
    currentPassword: str
    newPassword: NewPassword


class UpdateUserAccountResponse(BaseModel):
    message: str
    user: UserAccountProfileResponse


class UpdateLanguageRequest(BaseModel):
    language: Literal["en", "zh"]