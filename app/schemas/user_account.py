"""Schemas for user account self-service routes."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class UserAccountProfileResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool


class UpdateUserAccountRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(min_length=8, max_length=72)


class UpdateUserAccountResponse(BaseModel):
    message: str
    user: UserAccountProfileResponse