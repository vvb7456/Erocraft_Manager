"""Probe local Wings via loopback and aggregate container stats.

Uses daemon_token read from /etc/pterodactyl/config.yml (no separate config).

.. note::
   ``base_url`` is ALWAYS a loopback URL (``http(s)://127.0.0.1:<api.port>``)
   built by :func:`agent.collectors.wings_config.read_local_wings_url`. This
   collector MUST NOT be called with a remote URL; TLS ``verify=False`` below
   is safe only because the connection never leaves the host.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..schemas import ContainerAggregate, WingsStatus


async def probe_wings(base_url: str, token: str | None, timeout: float = 5.0) -> WingsStatus:
    """Probe Wings ``/api/system``.

    :param base_url: loopback URL only (see module docstring).
    """
    if not token:
        return WingsStatus(ok=False, error="no daemon_token in wings config")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        # verify=False: Wings uses a self-signed cert when ssl.enabled=true; the
        # connection is loopback-only so no MITM surface. Keep this in sync with
        # the module docstring — DO NOT pass a remote URL here.
        async with httpx.AsyncClient(verify=False, timeout=timeout) as client:
            r = await client.get(f"{base_url}/api/system", headers=headers)
            if r.status_code != 200:
                return WingsStatus(ok=False, error=f"http {r.status_code}")
            data = r.json()
            return WingsStatus(ok=True, version=data.get("version"))
    except Exception as e:
        return WingsStatus(ok=False, error=str(e)[:200])


async def collect_containers(base_url: str, token: str | None, timeout: float = 5.0) -> ContainerAggregate:
    """Aggregate ``/api/servers`` utilization into :class:`ContainerAggregate`.

    :param base_url: loopback URL only (see module docstring).
    """
    if not token:
        return ContainerAggregate()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        # verify=False: see probe_wings() — loopback-only.
        async with httpx.AsyncClient(verify=False, timeout=timeout) as client:
            r = await client.get(f"{base_url}/api/servers", headers=headers)
            if r.status_code != 200:
                return ContainerAggregate()
            servers = r.json()
            agg = ContainerAggregate(total=len(servers))
            for srv in servers:
                state = srv.get("state") or ""
                if state in ("running", "starting"):
                    agg.running += 1
                util = srv.get("utilization") or {}
                agg.cpu_pct_sum += float(util.get("cpu_absolute") or 0.0)
                agg.mem_used_mb_sum += int((util.get("memory_bytes") or 0) // (1024 * 1024))
                agg.disk_used_mb_sum += int((util.get("disk_bytes") or 0) // (1024 * 1024))
            agg.cpu_pct_sum = round(agg.cpu_pct_sum, 2)
            return agg
    except Exception:
        return ContainerAggregate()
