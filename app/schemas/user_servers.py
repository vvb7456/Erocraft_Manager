"""Schemas for user-facing server routes."""

from __future__ import annotations

from datetime import datetime
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
    name: str | None = None
    sftpPort: int | None = None


class UserServerTunnelInfo(BaseModel):
    status: str
    hostname: str
    customSubdomain: str | None
    lastError: str | None = None


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
    eggName: str
    limits: UserServerLimits
    allocation: UserServerAllocation
    node: UserServerNode
    expirationDate: str | None
    daysLeft: int | None
    address: str | None
    planId: int | None = None
    planCode: str | None = None
    planName: str | None = None
    hasUpgradeOptions: bool = False
    isTrial: bool = False
    llmEnabled: bool = False
    llmStatus: str | None = None


class UpgradeOption(BaseModel):
    planCode: str
    planName: str
    displayOrder: int
    categoryLabel: str | None
    descriptionMd: str | None
    cpu: int
    memoryMb: int
    diskMb: int
    diffFen: int
    priceFen: int


class UpgradeOptionsResponse(BaseModel):
    serverId: int
    serverName: str
    currentPlanName: str | None
    remainingDays: int
    options: list[UpgradeOption]


class UserServerDetail(UserServerItem):
    model_config = ConfigDict(title="UserServerDetail")
    tunnel: UserServerTunnelInfo | None = None
    hostTunnelReady: bool = False


class ServerResourcesResponse(BaseModel):
    state: str
    isSuspended: bool
    resources: dict[str, Any]


class PowerActionRequest(BaseModel):
    action: Literal["start", "stop", "restart", "kill"]


class UserActivityReportRequest(BaseModel):
    event: Literal["server:console.command", "server:file.uploaded"]
    properties: dict[str, Any] = Field(default_factory=dict)


class WingsTokenResponse(BaseModel):
    token: str
    wsUrl: str
    baseUrl: str
    serverUuid: str
    expiresAt: int
    # Per-file upload limit in MiB, sourced from panel.nodes.upload_size.
    # Frontend uses this to short-circuit oversize uploads client-side
    # (wings would otherwise stream the whole file before rejecting).
    uploadSize: int


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


class UserActivityActor(BaseModel):
    id: int
    uuid: str
    username: str
    email: str


class UserActivityLogItem(BaseModel):
    id: int
    batch: str | None
    event: str
    ip: str
    description: str | None
    actorType: str | None
    actorId: int | None
    apiKeyId: int | None
    properties: dict[str, Any] | list[Any]
    timestamp: datetime
    actor: UserActivityActor | None = None


class UserActivityLogsResponse(BaseModel):
    logs: list[UserActivityLogItem]
    total: int
    page: int
    perPage: int
