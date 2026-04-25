"""Schemas for admin server detail routes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ServerOwnerSummary(CamelModel):
    id: int
    uuid: str
    username: str
    email: str


class ServerNodeSummary(CamelModel):
    id: int
    name: str
    fqdn: str
    scheme: str
    daemon_listen: int = Field(alias="daemonListen")
    daemon_sftp: int = Field(alias="daemonSftp")


class ServerNestSummary(CamelModel):
    id: int
    name: str


class DockerImageOption(CamelModel):
    label: str
    value: str


class ServerEggSummary(CamelModel):
    id: int
    name: str
    nest_id: int = Field(alias="nestId")
    startup: str | None
    docker_images: list[DockerImageOption] = Field(alias="dockerImages")


class ManagerHostSummary(CamelModel):
    id: int
    name: str
    agent_url: str = Field(alias="agentUrl")
    enabled: bool
    inbound_reachable: bool = Field(alias="inboundReachable")


class ServerAllocationSummary(CamelModel):
    id: int
    node_id: int = Field(alias="nodeId")
    ip: str
    ip_alias: str | None = Field(alias="ipAlias")
    port: int
    notes: str | None
    is_primary: bool = Field(alias="isPrimary")


class ServerVariableSummary(CamelModel):
    id: int
    name: str
    description: str
    env_variable: str = Field(alias="envVariable")
    default_value: str = Field(alias="defaultValue")
    value: str
    rules: str | None
    user_viewable: bool = Field(alias="userViewable")
    user_editable: bool = Field(alias="userEditable")


class AdminServerSummary(CamelModel):
    id: int
    uuid: str
    uuid_short: str = Field(alias="uuidShort")
    external_id: str | None = Field(alias="externalId")
    name: str
    description: str
    status: str | None
    is_suspended: bool = Field(alias="isSuspended")
    is_installing: bool = Field(alias="isInstalling")
    owner_id: int = Field(alias="ownerId")
    node_id: int = Field(alias="nodeId")
    nest_id: int = Field(alias="nestId")
    egg_id: int = Field(alias="eggId")
    allocation_id: int = Field(alias="allocationId")
    memory: int
    swap: int
    disk: int
    io: int
    cpu: int
    threads: str | None
    oom_disabled: bool = Field(alias="oomDisabled")
    allocation_limit: int | None = Field(alias="allocationLimit")
    database_limit: int | None = Field(alias="databaseLimit")
    backup_limit: int = Field(alias="backupLimit")
    image: str
    startup: str
    skip_scripts: bool = Field(alias="skipScripts")
    created_at: datetime | None = Field(alias="createdAt")
    updated_at: datetime | None = Field(alias="updatedAt")
    installed_at: datetime | None = Field(alias="installedAt")
    expiration_date: str | None = Field(alias="expirationDate")


class AdminServerDetailResponse(CamelModel):
    server: AdminServerSummary
    owner: ServerOwnerSummary
    node: ServerNodeSummary
    nest: ServerNestSummary | None
    egg: ServerEggSummary
    manager_host: ManagerHostSummary | None = Field(alias="managerHost")
    allocations: list[ServerAllocationSummary]
    variables: list[ServerVariableSummary]
    hidden_variable_count: int = Field(alias="hiddenVariableCount")


class ServerRuntimeResponse(CamelModel):
    state: str | None = None
    is_suspended: bool | None = Field(default=None, alias="isSuspended")
    resources: dict | None = None
    raw: dict


class UpdateServerDetailsRequest(CamelModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    external_id: str | None = Field(default=None, alias="externalId")


class UpdateServerOwnerRequest(CamelModel):
    owner_id: int = Field(alias="ownerId")


class UpdateServerBuildRequest(CamelModel):
    memory: int | None = Field(default=None, ge=0)
    swap: int | None = None
    disk: int | None = Field(default=None, ge=0)
    io: int | None = Field(default=None, ge=10)
    cpu: int | None = Field(default=None, ge=0)
    threads: str | None = None
    oom_disabled: bool | None = Field(default=None, alias="oomDisabled")
    allocation_limit: int | None = Field(default=None, alias="allocationLimit", ge=0)
    database_limit: int | None = Field(default=None, alias="databaseLimit", ge=0)
    backup_limit: int | None = Field(default=None, alias="backupLimit", ge=0)


class AllocationIdsRequest(CamelModel):
    allocation_ids: list[int] = Field(alias="allocationIds", min_length=1)


class PrimaryAllocationRequest(CamelModel):
    allocation_id: int = Field(alias="allocationId")


class UpdateStartupRequest(CamelModel):
    image: str | None = Field(default=None, min_length=1)
    startup: str | None = Field(default=None, min_length=1)
    skip_scripts: bool | None = Field(default=None, alias="skipScripts")


class SwitchEggRequest(CamelModel):
    nest_id: int = Field(alias="nestId")
    egg_id: int = Field(alias="eggId")
    environment: dict[str, str] = Field(default_factory=dict)
    image: str | None = Field(default=None, min_length=1)
    startup: str | None = Field(default=None, min_length=1)
    skip_scripts: bool | None = Field(default=None, alias="skipScripts")


class UpdateVariablesRequest(CamelModel):
    variables: dict[str, str] = Field(min_length=1)


class AvailableAllocationsResponse(CamelModel):
    allocations: list[ServerAllocationSummary]


class MutationWarningResponse(CamelModel):
    message: str
    warning: str | None = None
