"""Pydantic schemas for agent HTTP API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------- collectors ----------

class SystemMetrics(BaseModel):
    cpu_pct: float
    cpu_count: int
    load_avg: List[float]
    mem_total_mb: int
    mem_used_mb: int
    mem_pct: float
    swap_total_mb: int
    swap_used_mb: int
    disk_total_mb: int
    disk_used_mb: int
    disk_pct: float
    net_rx_bytes_sec: Optional[int] = None
    net_tx_bytes_sec: Optional[int] = None
    disk_read_bytes_sec: Optional[int] = None
    disk_write_bytes_sec: Optional[int] = None
    uptime_sec: int


class WingsStatus(BaseModel):
    ok: bool
    version: Optional[str] = None
    error: Optional[str] = None


class ContainerAggregate(BaseModel):
    total: int = 0
    running: int = 0
    cpu_pct_sum: float = 0.0
    mem_used_mb_sum: int = 0
    disk_used_mb_sum: int = 0


class WingsConfigSummary(BaseModel):
    """Sanitized subset of /etc/pterodactyl/config.yml.

    Sensitive fields (token) are excluded.
    """

    api_host: Optional[str] = None
    api_port: Optional[int] = None
    api_ssl_enabled: Optional[bool] = None
    api_upload_limit_mb: Optional[int] = None
    sftp_bind_address: Optional[str] = None
    sftp_bind_port: Optional[int] = None
    system_data: Optional[str] = None
    docker_socket: Optional[str] = None
    debug: Optional[bool] = None


class ProbeResult(BaseModel):
    name: str
    ok: bool
    latency_ms: Optional[float] = None
    error_msg: Optional[str] = None


class MetricsSnapshot(BaseModel):
    taken_at: datetime
    node_id: Optional[int] = None
    system: SystemMetrics
    wings: WingsStatus
    containers: ContainerAggregate
    wings_config: Optional[WingsConfigSummary] = None
    probes: List[ProbeResult] = Field(default_factory=list)

    @field_validator("taken_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("taken_at must be timezone-aware")
        return v


# ---------- commands ----------

class CommandRequest(BaseModel):
    id: int
    type: str
    params: Optional[Dict[str, Any]] = None


class CommandResponse(BaseModel):
    id: int
    ok: bool
    # ``output`` is intentionally Any so handlers can return either a simple
    # string (e.g. ``ping`` -> "pong") or a structured payload (e.g.
    # ``wings.status`` -> systemd state dict). The wire format stays JSON.
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: int


# ---------- agent self status ----------

class AgentCapabilities(BaseModel):
    metrics_system: bool = False
    metrics_wings: bool = False
    cert_status: bool = False
    cert_expiry_warning: bool = False
    cert_install: bool = False
    cert_targets: bool = False
    wings_config: bool = False
    wings_restart: bool = False
    wings_service: bool = False
    wings_logs: bool = False


class AgentStatus(BaseModel):
    version: str
    started_at: datetime
    config_path: str
    wings_config_path: Optional[str] = None
    bind: str
    role: str
    capabilities: AgentCapabilities


# ---------- wings service control ----------

class WingsServiceStatus(BaseModel):
    """systemd unit state for the wings service."""

    service_name: str
    active_state: Optional[str] = None       # systemd ActiveState: active/inactive/failed/...
    sub_state: Optional[str] = None          # SubState: running/dead/failed/...
    main_pid: Optional[int] = None
    since: Optional[datetime] = None         # when the unit entered current state
    error: Optional[str] = None              # populated when probe fails entirely
