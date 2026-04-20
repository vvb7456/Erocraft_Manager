"""Schemas for user-facing server routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class UserServerLimits(BaseModel):
    memory: int
    disk: int
    cpu: int


class UserServerAllocation(BaseModel):
    ip: str | None
    port: int | None


class UserServerNode(BaseModel):
    fqdn: str | None


class UserServerItem(BaseModel):
    id: int
    uuid: str
    uuidShort: str
    name: str
    description: str | None
    status: str | None
    isInstalling: bool
    isInstalled: bool
    isSuspended: bool
    nodeId: int
    eggId: int
    limits: UserServerLimits
    allocation: UserServerAllocation
    node: UserServerNode
    expirationDate: str | None
    daysLeft: int | None
    address: str | None


class UserServerDetail(UserServerItem):
    model_config = ConfigDict(title="UserServerDetail")


class ServerResourcesResponse(BaseModel):
    state: str
    isSuspended: bool
    resources: dict[str, Any]


class PowerActionRequest(BaseModel):
    action: Literal["start", "stop", "restart", "kill"]


class WingsTokenResponse(BaseModel):
    token: str
    wsUrl: str
    baseUrl: str
    serverUuid: str
    expiresAt: int


class StartupVariableItem(BaseModel):
    envVariable: str
    name: str
    description: str
    defaultValue: str
    value: str
    isEditable: bool
    rules: str | None


class FileContentResponse(BaseModel):
    content: str


class SignedUrlResponse(BaseModel):
    url: str


class WingsFileEntry(BaseModel):
    name: str
    mode: str | None = None
    mode_bits: str | None = None
    size: int = 0
    file: bool = False
    directory: bool = False
    symlink: bool = False
    mime: str | None = None
    created: str | None = None
    modified: str | None = None


class FileWriteRequest(BaseModel):
    content: str = ""


class FileRenameRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    root: str = "/"
    from_path: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)


class FileDeleteRequest(BaseModel):
    root: str = "/"
    files: list[str] = Field(min_length=1)


class FileCompressRequest(BaseModel):
    root: str = "/"
    files: list[str] = Field(min_length=1)


class FileDecompressRequest(BaseModel):
    root: str = "/"
    file: str = Field(min_length=1)


class FileCreateFolderRequest(BaseModel):
    name: str = Field(min_length=1)
    path: str = "/"



class StartupVariableUpdate(BaseModel):
    variables: dict[str, str]


class ReinstallRequest(BaseModel):
    force: bool = False


class STDefaultPasswordRequest(BaseModel):
    password: str = Field(min_length=0)


class STDefaultPasswordResponse(BaseModel):
    hasPassword: bool
