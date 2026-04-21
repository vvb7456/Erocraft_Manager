"""System metrics via psutil + /proc/uptime.

Uses /proc/uptime as authoritative uptime source (not psutil.boot_time
which depends on /proc/stat btime and drifts with clock adjustments).
"""

from __future__ import annotations

import time
from typing import Any

import psutil

from ..schemas import SystemMetrics


_prev_net_rx: int | None = None
_prev_net_tx: int | None = None
_prev_net_ts: float | None = None


def _read_uptime() -> int:
    try:
        with open("/proc/uptime", "r", encoding="ascii") as f:
            return int(float(f.readline().split()[0]))
    except (OSError, ValueError):
        return int(time.time() - psutil.boot_time())


def collect_system() -> SystemMetrics:
    """Collect a single system snapshot.

    Note: psutil.cpu_percent(interval=None) returns the value since the
    previous call (or 0 on first call). The first invocation should be
    treated as a warm-up; subsequent calls give the real cpu% over the
    interval since the last call. Caller is responsible for cadence.
    """
    global _prev_net_rx, _prev_net_tx, _prev_net_ts

    cpu_pct = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True) or 0
    load_avg = list(psutil.getloadavg())

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")

    net = psutil.net_io_counters()
    now = time.monotonic()
    rx_bps: int | None = None
    tx_bps: int | None = None
    if _prev_net_rx is not None and _prev_net_ts is not None:
        dt = now - _prev_net_ts
        if dt > 0:
            rx_bps = int((net.bytes_recv - _prev_net_rx) / dt)
            tx_bps = int((net.bytes_sent - _prev_net_tx) / dt) if _prev_net_tx is not None else None
    _prev_net_rx = net.bytes_recv
    _prev_net_tx = net.bytes_sent
    _prev_net_ts = now

    return SystemMetrics(
        cpu_pct=round(cpu_pct, 1),
        cpu_count=cpu_count,
        load_avg=[round(x, 2) for x in load_avg],
        mem_total_mb=mem.total // (1024 * 1024),
        mem_used_mb=mem.used // (1024 * 1024),
        mem_pct=round(mem.percent, 1),
        swap_total_mb=swap.total // (1024 * 1024),
        swap_used_mb=swap.used // (1024 * 1024),
        disk_total_mb=disk.total // (1024 * 1024),
        disk_used_mb=disk.used // (1024 * 1024),
        disk_pct=round(disk.percent, 1),
        net_rx_bytes_sec=rx_bps,
        net_tx_bytes_sec=tx_bps,
        uptime_sec=_read_uptime(),
    )
