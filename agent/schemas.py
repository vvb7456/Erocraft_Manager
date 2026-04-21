"""Pydantic schemas for agent HTTP API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------- collectors ----------

class SystemMetrics(BaseModel):
    cpu_pct: float
    cpu_count: int
    load_avg: list[float]
    mem_total_mb: int
    mem_used_mb: int
    mem_pct: float
    swap_total_mb: int
    swap_used_mb: int
    disk_total_mb: int
    disk_used_mb: int
    disk_pct: float
    net_rx_bytes_sec: int | None = None
    net_tx_bytes_sec: int | None = None
    uptime_sec: int


class WingsStatus(BaseModel):
    ok: bool
    version: str | None = None
    error: str | None = None


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

    api_host: str | None = None
    api_port: int | None = None
    api_ssl_enabled: bool | None = None
    api_upload_limit_mb: int | None = None
    sftp_bind_address: str | None = None
    sftp_bind_port: int | None = None
    system_data: str | None = None
    docker_socket: str | None = None
    debug: bool | None = None


class ProbeResult(BaseModel):
    name: str
    ok: bool
    latency_ms: float | None = None
    error_msg: str | None = None


class MetricsSnapshot(BaseModel):
    taken_at: datetime
    node_id: int
    system: SystemMetrics
    wings: WingsStatus
    containers: ContainerAggregate
    wings_config: WingsConfigSummary | None = None
    probes: list[ProbeResult] = Field(default_factory=list)


# ---------- commands ----------

class CommandRequest(BaseModel):
    id: int
    type: str
    params: dict | None = None


class CommandResponse(BaseModel):
    id: int
    ok: bool
    output: str | None = None
    error: str | None = None
    duration_ms: int


# ---------- agent self status ----------

class AgentStatus(BaseModel):
    version: str
    started_at: datetime
    config_path: str
    wings_config_path: str
    bind: str
