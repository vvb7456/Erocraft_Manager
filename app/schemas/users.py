"""Schemas for admin user management routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserListItem(BaseModel):
    id: int
    uuid: str | None
    username: str
    email: str
    first_name: str | None
    last_name: str | None
    root_admin: bool
    language: str | None
    created_at: str | None
    updated_at: str | None
    server_count: int


class UsersListResponse(BaseModel):
    users: list[UserListItem]


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=1)
    username: str = Field(min_length=1)
    firstName: str = ""
    lastName: str = ""
    sendWelcome: bool = True


class UpdateUserRequest(BaseModel):
    username: str = Field(min_length=1)
    email: str = Field(min_length=1)
    firstName: str = ""
    lastName: str = ""
    password: str | None = None


class BatchUsersRequest(BaseModel):
    action: Literal["email", "delete"]
    userIds: list[int] = Field(min_length=1)


class UserRef(BaseModel):
    id: int
    username: str


class UserMessageResponse(BaseModel):
    message: str


class CreateUserResponse(UserMessageResponse):
    emailSent: bool | None = None
    user: UserRef


class BatchUsersResponse(UserMessageResponse):
    success: int
    failed: int
