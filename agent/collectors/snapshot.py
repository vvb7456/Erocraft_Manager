"""Aggregate snapshot collector with TTL caching."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from ..config import AgentConfig
from ..schemas import MetricsSnapshot, WingsConfigSummary
from . import system as system_collector
from . import wings as wings_collector
from . import wings_config as wings_config_collector
from ..probes import run_probe


class SnapshotProvider:
    def __init__(self, cfg: AgentConfig) -> None:
        self._cfg = cfg
        self._cache: MetricsSnapshot | None = None
        self._cache_ts: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self, force: bool = False) -> MetricsSnapshot:
        async with self._lock:
            ttl = self._cfg.collect.cache_ttl_sec
            if (
                not force
                and self._cache is not None
                and (time.monotonic() - self._cache_ts) < ttl
            ):
                return self._cache
            self._cache = await self._collect()
            self._cache_ts = time.monotonic()
            return self._cache

    async def _collect(self) -> MetricsSnapshot:
        wings_path = self._cfg.wings.config_path

        # Wings config + token (read once)
        wings_config_summary: WingsConfigSummary | None = None
        token: str | None = None
        wings_url = "http://127.0.0.1:8080"
        try:
            wings_config_summary = wings_config_collector.read_summary(wings_path)
            token = wings_config_collector.read_daemon_token(wings_path)
            wings_url = wings_config_collector.read_local_wings_url(wings_path)
        except wings_config_collector.WingsConfigError:
            wings_config_summary = None

        system = system_collector.collect_system()
        wings_task = asyncio.create_task(wings_collector.probe_wings(wings_url, token))
        containers_task = asyncio.create_task(wings_collector.collect_containers(wings_url, token))
        probe_tasks = [run_probe(p) for p in self._cfg.probes]

        wings_status, containers, *probe_results = await asyncio.gather(
            wings_task, containers_task, *probe_tasks
        )

        return MetricsSnapshot(
            taken_at=datetime.now(timezone.utc),
            node_id=self._cfg.manager.node_id,
            system=system,
            wings=wings_status,
            containers=containers,
            wings_config=wings_config_summary,
            probes=list(probe_results),
        )
