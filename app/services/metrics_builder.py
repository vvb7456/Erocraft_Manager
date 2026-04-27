"""Shared helper: convert an agent metrics payload into a HostMetrics row.

Extracted from ``app.jobs.tasks.monitoring`` so that both the periodic
pull loop (jobs) and the admin "refresh now" endpoint (API) can build
identical rows without one module reaching into the other's private
functions.

Keep this module side-effect free: it must not touch the database, log,
or call network services.  Just: payload -> ORM instance.
"""

from __future__ import annotations

from datetime import datetime

from app.db.models.monitoring import HostMetrics


def build_metrics_row(
    host_id: int,
    ts: datetime,
    agent_payload: dict | None,
) -> HostMetrics:
    """Map a `/v1/metrics` agent payload into a `HostMetrics` ORM instance.

    A missing / falsy `agent_payload` yields a row with `agent_online=False`
    and `wings_online=False`, preserving the invariant that every pull
    cycle produces exactly one row per monitored node (see design §6.4).
    """
    if not agent_payload:
        return HostMetrics(
            host_id=host_id,
            ts=ts,
            agent_online=False,
            wings_online=False,
        )

    sys_data = agent_payload.get("system") or {}
    wings = agent_payload.get("wings") or {}
    containers = agent_payload.get("containers") or {}
    load_avg = sys_data.get("load_avg") or []

    return HostMetrics(
        host_id=host_id,
        ts=ts,
        agent_online=True,
        wings_online=bool(wings.get("ok")),
        cpu_pct=sys_data.get("cpu_pct"),
        cpu_cores=sys_data.get("cpu_count"),
        load_1m=load_avg[0] if len(load_avg) > 0 else None,
        load_5m=load_avg[1] if len(load_avg) > 1 else None,
        load_15m=load_avg[2] if len(load_avg) > 2 else None,
        mem_total_mb=sys_data.get("mem_total_mb"),
        mem_used_mb=sys_data.get("mem_used_mb"),
        mem_pct=sys_data.get("mem_pct"),
        swap_total_mb=sys_data.get("swap_total_mb"),
        swap_used_mb=sys_data.get("swap_used_mb"),
        uptime_sec=sys_data.get("uptime_sec"),
        disk_total_mb=sys_data.get("disk_total_mb"),
        disk_used_mb=sys_data.get("disk_used_mb"),
        disk_pct=sys_data.get("disk_pct"),
        net_rx_bps=sys_data.get("net_rx_bytes_sec"),
        net_tx_bps=sys_data.get("net_tx_bytes_sec"),
        disk_read_bps=sys_data.get("disk_read_bytes_sec"),
        disk_write_bps=sys_data.get("disk_write_bytes_sec"),
        wings_version=wings.get("version"),
        container_total=containers.get("total"),
        container_running=containers.get("running"),
        container_mem_mb=containers.get("mem_used_mb_sum"),
        container_cpu_pct=round(containers.get("cpu_pct_sum") or 0.0, 1),
        container_disk_mb=containers.get("disk_used_mb_sum"),
    )
