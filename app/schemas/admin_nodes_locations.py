"""Pydantic schemas for admin Location & Node management routes."""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_DAEMON_BASE_RE = re.compile(r"^/[\d\w.\-/]+$")


class LocationOut(BaseModel):
    id: int
    short: str
    long: str | None = None
    nodes_count: int = 0
    servers_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class LocationListResponse(BaseModel):
    locations: list[LocationOut]


class LocationCreateIn(BaseModel):
    short: str = Field(min_length=1, max_length=60)
    long: str | None = Field(default=None, max_length=191)

    @field_validator("short")
    @classmethod
    def _validate_short(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("地域简码不能为空")
        if len(s) > 60:
            raise ValueError("地域简码长度不能超过 60")
        return s

    @field_validator("long")
    @classmethod
    def _validate_long(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        if len(s) > 191:
            raise ValueError("地域描述长度不能超过 191")
        return s


class LocationUpdateIn(BaseModel):
    short: str | None = Field(default=None, max_length=60)
    long: str | None = Field(default=None, max_length=191)

    @model_validator(mode="after")
    def _check_fields(self) -> "LocationUpdateIn":
        if "short" in self.model_fields_set:
            if self.short is None or not self.short.strip():
                raise ValueError("地域简码不能为空")
            self.short = self.short.strip()
            if len(self.short) > 60:
                raise ValueError("地域简码长度不能超过 60")
        if "long" in self.model_fields_set and self.long is not None:
            s = self.long.strip()
            if len(s) > 191:
                raise ValueError("地域描述长度不能超过 191")
            self.long = s or None
        return self


class NodeLocationBrief(BaseModel):
    id: int
    short: str
    long: str | None = None


class NodeOut(BaseModel):
    id: int
    uuid: str
    public: bool
    name: str
    description: str | None = None
    location_id: int
    location: NodeLocationBrief | None = None
    fqdn: str
    scheme: str
    behind_proxy: bool
    maintenance_mode: bool
    memory: int
    memory_overallocate: int
    disk: int
    disk_overallocate: int
    upload_size: int
    daemon_token_id: str
    daemon_listen: int
    daemon_sftp: int
    daemon_base: str
    servers_count: int = 0
    plans_count: int = 0
    host_id: int | None = None
    host_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class NodeListResponse(BaseModel):
    nodes: list[NodeOut]


class NodeCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=191)
    description: str | None = None
    location_id: int = Field(ge=1)
    fqdn: str = Field(min_length=1, max_length=191)
    scheme: Literal["http", "https"] = "https"
    public: bool = True
    behind_proxy: bool = False
    maintenance_mode: bool = False
    memory: int = Field(ge=1)
    memory_overallocate: int = Field(default=0, ge=-1)
    disk: int = Field(ge=1)
    disk_overallocate: int = Field(default=0, ge=-1)
    upload_size: int = Field(default=100, ge=1, le=1024 * 1024)
    daemon_listen: int = Field(default=8080, ge=1, le=65535)
    daemon_sftp: int = Field(default=2022, ge=1, le=65535)
    daemon_base: str = Field(default="/var/lib/pterodactyl/volumes", max_length=191)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("节点名称不能为空")
        return s

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("fqdn")
    @classmethod
    def _validate_fqdn(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("节点 FQDN 不能为空")
        if "://" in s or "/" in s or any(ch.isspace() for ch in s):
            raise ValueError("节点 FQDN 只需填写域名或 IP，不能包含协议或路径")
        return s

    @field_validator("daemon_base")
    @classmethod
    def _validate_daemon_base(cls, v: str) -> str:
        s = v.strip()
        if not _DAEMON_BASE_RE.match(s):
            raise ValueError("daemon_base 必须以 / 开头且仅包含合法路径字符")
        return s

    @model_validator(mode="after")
    def _check_https_bare_ip(self) -> "NodeCreateIn":
        # Mirrors Panel Fqdn rule: direct HTTPS without reverse proxy cannot use a bare IP
        # because Wings/Let's Encrypt certificates are issued against domain names.
        if self.scheme == "https" and not self.behind_proxy:
            try:
                ipaddress.ip_address(self.fqdn.strip("[]"))
            except ValueError:
                pass
            else:
                raise ValueError("启用 HTTPS 且未处于反向代理后时，FQDN 不能为裸 IP 地址")
        return self


class NodeConfigurationOut(BaseModel):
    node_id: int
    node_name: str
    remote: str
    config: dict[str, Any]
    yaml: str
    warnings: list[str] = Field(default_factory=list)


class AdminMessageResponse(BaseModel):
    message: str
