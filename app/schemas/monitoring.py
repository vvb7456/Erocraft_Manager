"""Pydantic schemas for the monitoring system."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Monitoring API responses (admin)
# ---------------------------------------------------------------------------


class NodeOverview(BaseModel):
    id: int
    name: str
    fqdn: str
    kind: str = "wings_node"
    agentOnline: bool = False
    wingsOnline: bool = False
    publicReachable: bool | None = None
    lastSeen: datetime | None = None
    wingsVersion: str | None = None
    cpuPct: float | None = None
    cpuCores: int | None = None
    loadAvg: list[float] | None = None
    memUsedMb: int | None = None
    memTotalMb: int | None = None
    memPct: float | None = None
    swapUsedMb: int | None = None
    swapTotalMb: int | None = None
    uptimeSec: int | None = None
    diskUsedMb: int | None = None
    diskTotalMb: int | None = None
    diskPct: float | None = None
    netRxBps: int | None = None
    netTxBps: int | None = None
    containerTotal: int | None = None
    containerRunning: int | None = None
    containerMemMb: int | None = None
    containerCpuPct: float | None = None
    containerDiskMb: int | None = None
    activeAlerts: int = 0


class ProbeOverview(BaseModel):
    name: str
    ok: bool
    latencyMs: float | None = None
    source: str
    ts: datetime | None = None


class AlertSummary(BaseModel):
    active: int = 0
    todayTotal: int = 0


class MonitoringOverviewResponse(BaseModel):
    nodes: list[NodeOverview]
    probes: list[ProbeOverview]
    alerts: AlertSummary


class AlertItem(BaseModel):
    id: int
    hostId: int | None = None
    alertType: str
    severity: str
    message: str | None = None
    createdAt: datetime
    resolvedAt: datetime | None = None
    notified: bool = False


class AlertListResponse(BaseModel):
    items: list[AlertItem]
    total: int


class HistoryPoint(BaseModel):
    ts: datetime
    cpuPct: float | None = None
    memPct: float | None = None
    diskPct: float | None = None
    loadAvg1m: float | None = None
    containerRunning: int | None = None
    netRxBps: int | None = None
    netTxBps: int | None = None


class NodeHistoryResponse(BaseModel):
    hostId: int
    interval: str
    points: list[HistoryPoint]
