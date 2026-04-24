"""System metrics via stdlib + /proc parsing.

Linux-only. Replaces psutil to keep agent dependencies pure-Python and
trivially installable on minimal hosts (NAS, low-spec generic_host).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from ..schemas import SystemMetrics


# Whole physical block devices only. Excludes partitions (e.g. sda1),
# loop (loop*), ram (ram*), device-mapper (dm-*), zram, and md-raid
# leaves — their IO would be double-counted against the underlying
# device. NVMe namespaces (nvme0n1) are included; their partitions
# (nvme0n1p1) are excluded.
_DISK_WHOLE_DEV_RE = re.compile(
    r"^(sd[a-z]+|nvme\d+n\d+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|mmcblk\d+)$"
)

# /proc/diskstats sector size is fixed at 512 bytes regardless of
# physical sector size (see Documentation/admin-guide/iostats.rst).
_DISK_SECTOR_BYTES = 512


# ---- /proc/stat CPU% running state ----

_prev_cpu_total: int | None = None
_prev_cpu_idle: int | None = None


def _read_cpu_times() -> tuple[int, int]:
    """Return (total_jiffies, idle_jiffies) from /proc/stat first line.

    /proc/stat first line: "cpu user nice system idle iowait irq softirq steal guest guest_nice"
    Idle component = idle + iowait (matches psutil's behavior).
    """
    with open("/proc/stat", "r", encoding="ascii") as f:
        line = f.readline()
    parts = line.split()
    # parts[0] == "cpu"
    nums = [int(x) for x in parts[1:]]
    # Pad in case kernel reports fewer fields (very old kernels)
    while len(nums) < 8:
        nums.append(0)
    user, nice, system, idle, iowait, irq, softirq, steal = nums[:8]
    idle_total = idle + iowait
    total = user + nice + system + idle + iowait + irq + softirq + steal
    return total, idle_total


def _cpu_percent_since_last_call() -> float:
    """Return CPU% over the interval since the previous call.

    First call returns 0.0 (no baseline).
    """
    global _prev_cpu_total, _prev_cpu_idle
    total, idle_total = _read_cpu_times()
    if _prev_cpu_total is None:
        _prev_cpu_total = total
        _prev_cpu_idle = idle_total
        return 0.0
    dt_total = total - _prev_cpu_total
    dt_idle = idle_total - (_prev_cpu_idle or 0)
    _prev_cpu_total = total
    _prev_cpu_idle = idle_total
    if dt_total <= 0:
        return 0.0
    return max(0.0, min(100.0, (dt_total - dt_idle) * 100.0 / dt_total))


# ---- /proc/meminfo ----

def _read_meminfo() -> dict[str, int]:
    """Return /proc/meminfo as {key: kB}."""
    out: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="ascii") as f:
        for line in f:
            key, _, rest = line.partition(":")
            value = rest.strip().split()
            if value:
                try:
                    out[key] = int(value[0])  # kB
                except ValueError:
                    continue
    return out


def _mem_swap_kib() -> tuple[int, int, int, int, int, int, float, float]:
    """Return (mem_total_kib, mem_used_kib, mem_avail_kib,
    swap_total_kib, swap_used_kib, swap_free_kib, mem_pct, swap_pct).

    Both ``mem_used`` and ``mem_pct`` follow ``psutil.virtual_memory()``
    semantics on Linux as referenced by historical metrics consumers:

        used    = total - available
        percent = (total - available) / total * 100

    where ``available`` is ``MemAvailable`` from /proc/meminfo (kernel's
    "how much can a new workload realistically allocate" estimate). This
    treats reclaimable page cache and slab as effectively free, which is
    what dashboard alert thresholds and historical curves were calibrated
    against. The ``free``-style formula ``total - free - buffers - cached -
    sreclaim`` reports a different absolute and would cause a step change
    in long-running series — don't use it here.
    """
    info = _read_meminfo()
    mem_total = info.get("MemTotal", 0)
    mem_free = info.get("MemFree", 0)
    mem_avail = info.get("MemAvailable", mem_free)
    mem_used = max(0, mem_total - mem_avail)
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    mem_pct = (mem_used * 100.0 / mem_total) if mem_total else 0.0
    swap_pct = (swap_used * 100.0 / swap_total) if swap_total else 0.0
    return mem_total, mem_used, mem_avail, swap_total, swap_used, swap_free, mem_pct, swap_pct


# ---- /proc/net/dev aggregate ----

def _read_net_totals() -> tuple[int, int]:
    """Return (rx_bytes_total, tx_bytes_total) summed across **all** ifaces.

    Loopback (``lo``) is intentionally included to match the legacy psutil
    semantics (``psutil.net_io_counters()`` aggregates every interface).
    Excluding it would systematically under-report throughput on hosts
    where the panel/wings/manager pipeline routes a non-trivial share of
    traffic over loopback.
    """
    rx = 0
    tx = 0
    with open("/proc/net/dev", "r", encoding="ascii") as f:
        # First two lines are headers
        for line in f.readlines()[2:]:
            iface, _, rest = line.partition(":")
            iface = iface.strip()
            if not rest or not iface:
                continue
            fields = rest.split()
            if len(fields) >= 9:
                try:
                    rx += int(fields[0])
                    tx += int(fields[8])
                except ValueError:
                    continue
    return rx, tx


_prev_net_rx: int | None = None
_prev_net_tx: int | None = None
_prev_net_ts: float | None = None


# ---- /proc/diskstats aggregate ----

def _read_disk_io_totals() -> tuple[int, int]:
    """Return (read_bytes_total, write_bytes_total) across whole block devs.

    /proc/diskstats columns (kernel >= 2.6, plenty of headroom):
      1 major, 2 minor, 3 device_name,
      4 reads_completed, 5 reads_merged, 6 sectors_read, 7 ms_reading,
      8 writes_completed, 9 writes_merged, 10 sectors_written, ...

    We pick sectors_read (col 6, index 5) and sectors_written (col 10,
    index 9), multiply by 512 (``_DISK_SECTOR_BYTES``), and sum across
    devices matching ``_DISK_WHOLE_DEV_RE``. Partitions are filtered
    out so their IO isn't double-counted against the underlying disk.
    """
    read_bytes = 0
    write_bytes = 0
    try:
        with open("/proc/diskstats", "r", encoding="ascii") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10:
                    continue
                dev = parts[2]
                if not _DISK_WHOLE_DEV_RE.match(dev):
                    continue
                try:
                    read_bytes += int(parts[5]) * _DISK_SECTOR_BYTES
                    write_bytes += int(parts[9]) * _DISK_SECTOR_BYTES
                except ValueError:
                    continue
    except OSError:
        return 0, 0
    return read_bytes, write_bytes


_prev_disk_read: int | None = None
_prev_disk_write: int | None = None
_prev_disk_ts: float | None = None


# ---- /proc/uptime ----

def _read_uptime() -> int:
    try:
        with open("/proc/uptime", "r", encoding="ascii") as f:
            return int(float(f.readline().split()[0]))
    except (OSError, ValueError):
        return 0


# ---- public collector ----

def collect_system() -> SystemMetrics:
    """Collect a single system snapshot.

    First call's CPU% is 0 (no baseline). Caller is responsible for cadence:
    call once at startup to warm up, then on the regular interval.
    """
    global _prev_net_rx, _prev_net_tx, _prev_net_ts
    global _prev_disk_read, _prev_disk_write, _prev_disk_ts

    cpu_pct = _cpu_percent_since_last_call()
    cpu_count = os.cpu_count() or 0
    try:
        load_avg = list(os.getloadavg())
    except (OSError, AttributeError):
        load_avg = [0.0, 0.0, 0.0]

    (
        mem_total_kib,
        mem_used_kib,
        _mem_avail_kib,
        swap_total_kib,
        swap_used_kib,
        _swap_free_kib,
        mem_pct,
        _swap_pct,
    ) = _mem_swap_kib()

    try:
        st = os.statvfs("/")
        # Match psutil.disk_usage("/") semantics:
        #   total = f_blocks * f_frsize  (full size, includes reserved)
        #   used  = (f_blocks - f_bfree) * f_frsize  (NOT free for ANY user)
        #   avail = f_bavail * f_frsize  (free for non-superuser)
        #   percent = used / (used + avail)  — reserved blocks are NOT
        #     counted as "used" for the percentage, otherwise ext4's
        #     default 5% reserved blocks would inflate disk_pct on every
        #     freshly formatted filesystem and break continuity with the
        #     legacy psutil-based metrics.
        disk_total = st.f_blocks * st.f_frsize
        disk_avail = st.f_bavail * st.f_frsize
        disk_used = (st.f_blocks - st.f_bfree) * st.f_frsize
        disk_used = max(0, disk_used)
        denom = disk_used + disk_avail
        disk_pct = (disk_used * 100.0 / denom) if denom else 0.0
    except OSError:
        disk_total = disk_used = 0
        disk_pct = 0.0

    rx_total, tx_total = _read_net_totals()
    now = time.monotonic()
    rx_bps: int | None = None
    tx_bps: int | None = None
    if _prev_net_rx is not None and _prev_net_ts is not None:
        dt = now - _prev_net_ts
        if dt > 0:
            # Clamp to >= 0: /proc/net/dev sum can DROP between samples on
            # wings hosts, because veth pairs for stopped containers are
            # destroyed and their accumulated counters disappear from the
            # aggregate. A negative bps value is meaningless to dashboards;
            # report 0 for the interval so the chart stays continuous.
            rx_delta = rx_total - _prev_net_rx
            rx_bps = max(0, int(rx_delta / dt))
            if _prev_net_tx is not None:
                tx_delta = tx_total - _prev_net_tx
                tx_bps = max(0, int(tx_delta / dt))
    _prev_net_rx = rx_total
    _prev_net_tx = tx_total
    _prev_net_ts = now

    # Disk IO delta. Same rate-over-interval logic as net; first call
    # returns None (no baseline). Counters in /proc/diskstats can wrap
    # on 32-bit kernels or reset on device hot-swap — clamp negatives
    # to 0 so dashboard curves stay continuous.
    dr_total, dw_total = _read_disk_io_totals()
    dr_bps: int | None = None
    dw_bps: int | None = None
    if _prev_disk_read is not None and _prev_disk_ts is not None:
        dt = now - _prev_disk_ts
        if dt > 0:
            dr_bps = max(0, int((dr_total - _prev_disk_read) / dt))
            if _prev_disk_write is not None:
                dw_bps = max(0, int((dw_total - _prev_disk_write) / dt))
    _prev_disk_read = dr_total
    _prev_disk_write = dw_total
    _prev_disk_ts = now

    return SystemMetrics(
        cpu_pct=round(cpu_pct, 1),
        cpu_count=cpu_count,
        load_avg=[round(x, 2) for x in load_avg],
        mem_total_mb=mem_total_kib // 1024,
        mem_used_mb=mem_used_kib // 1024,
        mem_pct=round(mem_pct, 1),
        swap_total_mb=swap_total_kib // 1024,
        swap_used_mb=swap_used_kib // 1024,
        disk_total_mb=disk_total // (1024 * 1024),
        disk_used_mb=disk_used // (1024 * 1024),
        disk_pct=round(disk_pct, 1),
        net_rx_bytes_sec=rx_bps,
        net_tx_bytes_sec=tx_bps,
        disk_read_bytes_sec=dr_bps,
        disk_write_bytes_sec=dw_bps,
        uptime_sec=_read_uptime(),
    )
