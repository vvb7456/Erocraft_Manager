"""Monitoring-related ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_naive_now as _utc_now
from app.db.base import Base


class HostMetrics(Base):
    __tablename__ = "manager_host_metrics"
    __table_args__ = (
        Index("idx_hm_host_ts", "host_id", "ts"),
        Index("idx_hm_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)

    # online status
    agent_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    wings_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_reachable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # host metrics (from agent)
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_cores: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    load_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_5m: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_15m: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mem_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    swap_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    swap_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uptime_sec: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_rx_bps: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_tx_bps: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_read_bps: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_write_bps: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # wings container aggregates
    wings_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    container_total: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    container_running: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    container_mem_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    container_cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    container_disk_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)


class HostProbeResult(Base):
    __tablename__ = "manager_host_probes"
    __table_args__ = (
        Index("idx_hp_ts", "ts"),
        Index("idx_hp_probe_ts", "probe_name", "ts"),
        Index("idx_hp_host_ts", "host_id", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    probe_name: Mapped[str] = mapped_column(String(50), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(String(200), nullable=True)


class HostAlert(Base):
    __tablename__ = "manager_host_alerts"
    __table_args__ = (
        Index("idx_ha_host_active", "host_id", "resolved_at"),
        Index("idx_ha_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    host_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="warning")
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
