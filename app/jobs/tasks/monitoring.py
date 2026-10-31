"""Collect hosts independently, committing samples before evaluating alerts."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import alert_defaults
from app.core.runtime_settings import MONITORING_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import to_iso_z, utc_naive_now
from app.db.models.manager import (
    HostAlertRule,
    HostAlertSettings,
    ManagerActivityLog,
    ManagerHost,
)
from app.db.models.monitoring import HostAlert, HostMetrics, HostProbeResult
from app.db.models.pterodactyl import PanelNode
from app.db.session import get_session_factory
from app.services import host_registry
from app.services.metrics_builder import build_metrics_row

logger = logging.getLogger(__name__)

MONITORING_JOB_ID = "monitoring_collect"

PUBLIC_PROBE_TIMEOUT = 5.0
PUBLIC_PROBE_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0


# ---------------------------------------------------------------------------
# Public-side reachability probe (Manager -> Wings public endpoint)
# ---------------------------------------------------------------------------


async def _probe_wings_public(
    node_id: int,
    fqdn: str,
    scheme: str,
    port: int,
) -> dict:
    url = f"{scheme}://{fqdn}:{port}/api/system"

    error = ""
    async with httpx.AsyncClient(timeout=PUBLIC_PROBE_TIMEOUT, verify=True, trust_env=False) as client:
        for attempt in range(PUBLIC_PROBE_ATTEMPTS):
            if attempt:
                await asyncio.sleep(RETRY_BASE_DELAY * 2 ** (attempt - 1))
            start = time.monotonic()
            try:
                async with asyncio.timeout(PUBLIC_PROBE_TIMEOUT):
                    # An unauthenticated Wings response still proves reachability.
                    await client.get(url)
                return {"ok": True, "latency_ms": round((time.monotonic() - start) * 1000, 1)}
            except (httpx.HTTPError, TimeoutError) as exc:
                error = (str(exc) or type(exc).__name__)[:200]
    logger.warning("wings public probe node %d failed after %d attempts: %s", node_id, PUBLIC_PROBE_ATTEMPTS, error)
    return {"ok": False, "error_msg": error}


# ---------------------------------------------------------------------------
# Alert engine — per-host configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HostAlertConfig:
    """Resolved per-host alert configuration (with defaults applied)."""

    host_id: int
    cooldown_min: int
    agent_pull_timeout: float
    agent_pull_attempts: int
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)

    def rule(self, alert_type: str) -> dict[str, Any]:
        return self.rules.get(alert_type) or alert_defaults.default_rule(alert_type)

    def type_enabled(self, alert_type: str) -> bool:
        return bool(self.rule(alert_type).get("enabled", False))


async def _load_host_alert_config(
    db: AsyncSession,
    host: ManagerHost,
) -> HostAlertConfig:
    """Load + merge per-host alert configuration, falling back to defaults."""

    settings_row = (
        await db.execute(
            select(HostAlertSettings).where(HostAlertSettings.host_id == host.id)
        )
    ).scalar_one_or_none()

    from app.services.notifications.policy import monitoring_defaults
    defaults = await monitoring_defaults(db)
    cooldown_min = defaults["cooldown_min"]
    agent_pull_timeout = alert_defaults.DEFAULT_AGENT_PULL_TIMEOUT
    agent_pull_attempts = alert_defaults.DEFAULT_AGENT_PULL_ATTEMPTS

    if settings_row is not None:
        if settings_row.cooldown_min is not None:
            cooldown_min = int(settings_row.cooldown_min)
        if settings_row.agent_pull_timeout is not None:
            agent_pull_timeout = float(settings_row.agent_pull_timeout)
        if settings_row.agent_pull_attempts is not None:
            agent_pull_attempts = int(settings_row.agent_pull_attempts)

    rule_rows = (
        await db.execute(
            select(HostAlertRule).where(HostAlertRule.host_id == host.id)
        )
    ).scalars().all()

    rules: dict[str, dict[str, Any]] = {}
    for atype in alert_defaults.ALERT_TYPES:
        rules[atype] = defaults["rules"].get(atype, alert_defaults.default_rule(atype))
    for row in rule_rows:
        override: dict[str, Any] = {} if row.enabled is None else {"enabled": row.enabled}
        if row.threshold is not None:
            override["threshold"] = float(row.threshold)
        if row.warning_threshold is not None:
            override["warning_threshold"] = float(row.warning_threshold)
        if row.critical_threshold is not None:
            override["critical_threshold"] = float(row.critical_threshold)
        if row.sustain_min is not None:
            override["sustain_min"] = int(row.sustain_min)
        rules[row.alert_type] = {**rules.get(row.alert_type, {}), **override}

    disk_high = next((r for r in rule_rows if r.alert_type == "disk_high"), None)
    disk_critical = next((r for r in rule_rows if r.alert_type == "disk_critical"), None)
    if disk_high and disk_high.critical_threshold is not None and (not disk_critical or disk_critical.critical_threshold is None):
        rules["disk_critical"]["critical_threshold"] = disk_high.critical_threshold

    return HostAlertConfig(
        host_id=host.id,
        cooldown_min=cooldown_min,
        agent_pull_timeout=agent_pull_timeout,
        agent_pull_attempts=agent_pull_attempts,
        rules=rules,
    )


async def _maybe_notify(
    db: AsyncSession,
    config: HostAlertConfig,
    *,
    host_name: str,
    alert_obj: HostAlert,
    kind: str,  # 'fired' | 'resolved'
    now: datetime,
) -> None:
    """Apply rule, mute and cooldown gates before enqueueing a notification."""
    if not config.type_enabled(alert_obj.alert_type):
        return
    if kind == "fired" and alert_obj.muted_until and alert_obj.muted_until > now:
        return
    if kind == "fired" and alert_obj.last_notified_at and now - alert_obj.last_notified_at < timedelta(minutes=config.cooldown_min):
        return

    from app.services.notifications.events import monitoring_alert

    await monitoring_alert(db, alert=alert_obj, host_name=host_name, kind=kind, cooldown_min=config.cooldown_min)


async def _check_alerts(
    db: AsyncSession,
    metrics: HostMetrics,
    *,
    config: HostAlertConfig,
    host_name: str,
    is_wings: bool = False,
) -> None:
    host_id = config.host_id
    now = utc_naive_now()
    for alert_type in alert_defaults.ALERT_TYPES:
        if not config.type_enabled(alert_type):
            await _auto_resolve(db, host_id, alert_type, now, host_name=host_name)

    # --- reachability ---
    if is_wings:
        # Wings reachability is an INDEPENDENT signal from agent reachability.
        # Previously wings_online was derived solely from the agent payload's
        # wings sub-dict, so an agent pull timeout falsely marked wings down
        # too. Now the Manager's own public-side probe (public_reachable) is
        # treated as authoritative: when it succeeds we consider wings online
        # regardless of what the (possibly missing) agent payload says. This
        # stops a single cross-border pull timeout from escalating to
        # node_offline critical while wings is actually still serving users.
        wings_reachable = metrics.wings_online or metrics.public_reachable

        node_offline_rule = config.rule("node_offline")
        agent_down_rule = config.rule("agent_only_down")
        # max(1, ...) guards against negative sustain_min sneaking in via
        # hand-edited DB rows (API validates ge=1, but dirty data bypasses
        # it) - a negative window would put the cutoff in the future and
        # silently disable the alert (audit m8).
        node_offline_sustain = max(1, int(node_offline_rule.get("sustain_min") or alert_defaults.DEFAULT_OFFLINE_SUSTAIN_MIN))
        agent_down_sustain = max(1, int(agent_down_rule.get("sustain_min") or alert_defaults.DEFAULT_OFFLINE_SUSTAIN_MIN))

        # 3 mutually-exclusive states for wings nodes
        if not metrics.agent_online and not wings_reachable:
            if await _check_offline_sustained(db, host_id, field_name="node_offline", minutes=node_offline_sustain):
                await _raise_or_skip(db, host_id, "node_offline", "critical",
                                     f"Host {host_id} unreachable (agent + wings down) - sustained offline {node_offline_sustain}m window",
                                     now, config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "agent_only_down", now,
                                config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "wings_only_down", now,
                                config=config, host_name=host_name)
        elif not metrics.agent_online:
            if await _check_offline_sustained(db, host_id, field_name="agent_online", minutes=agent_down_sustain):
                await _raise_or_skip(db, host_id, "agent_only_down", "warning",
                                     f"Host {host_id} agent unreachable (wings still online) - sustained offline {agent_down_sustain}m window",
                                     now, config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "node_offline", now,
                                config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "wings_only_down", now,
                                config=config, host_name=host_name)
        elif not wings_reachable:
            await _raise_or_skip(db, host_id, "wings_only_down", "critical",
                                 f"Host {host_id} wings unreachable (agent still online)",
                                 now, config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "node_offline", now,
                                config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "agent_only_down", now,
                                config=config, host_name=host_name)
        else:
            await _auto_resolve(db, host_id, "node_offline", now,
                                config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "agent_only_down", now,
                                config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "wings_only_down", now,
                                config=config, host_name=host_name)
    else:
        # Non-wings: only agent matters, wings is intentionally offline.
        agent_down_rule = config.rule("agent_only_down")
        agent_down_sustain = max(1, int(agent_down_rule.get("sustain_min") or alert_defaults.DEFAULT_OFFLINE_SUSTAIN_MIN))
        if not metrics.agent_online:
            if await _check_offline_sustained(db, host_id, field_name="agent_online", minutes=agent_down_sustain):
                await _raise_or_skip(db, host_id, "agent_only_down", "critical",
                                     f"Host {host_id} agent unreachable - sustained offline {agent_down_sustain}m window",
                                     now, config=config, host_name=host_name)
        else:
            await _auto_resolve(db, host_id, "agent_only_down", now,
                                config=config, host_name=host_name)
        # Wings-specific alerts should never be active for non-wings hosts.
        await _auto_resolve(db, host_id, "node_offline", now,
                            config=config, host_name=host_name)
        await _auto_resolve(db, host_id, "wings_only_down", now,
                            config=config, host_name=host_name)

    # --- CPU ---
    cpu_rule = config.rule("cpu_high")
    cpu_threshold = float(cpu_rule.get("threshold") or 90)
    cpu_sustain = int(cpu_rule.get("sustain_min") or 5)
    if metrics.cpu_pct is not None and metrics.cpu_pct > cpu_threshold:
        if await _check_sustained_above(db, host_id, "cpu_pct", cpu_threshold, minutes=cpu_sustain):
            await _raise_or_skip(db, host_id, "cpu_high", "warning",
                                 f"CPU {metrics.cpu_pct}% > {cpu_threshold}% sustained",
                                 now, config=config, host_name=host_name)
    else:
        await _auto_resolve(db, host_id, "cpu_high", now,
                            config=config, host_name=host_name)

    # --- Memory ---
    mem_rule = config.rule("mem_high")
    mem_threshold = float(mem_rule.get("threshold") or 90)
    mem_sustain = int(mem_rule.get("sustain_min") or 5)
    if metrics.mem_pct is not None and metrics.mem_pct > mem_threshold:
        if await _check_sustained_above(db, host_id, "mem_pct", mem_threshold, minutes=mem_sustain):
            await _raise_or_skip(db, host_id, "mem_high", "warning",
                                 f"Memory {metrics.mem_pct}% > {mem_threshold}% sustained",
                                 now, config=config, host_name=host_name)
    else:
        await _auto_resolve(db, host_id, "mem_high", now,
                            config=config, host_name=host_name)

    # --- Swap ---
    swap_rule = config.rule("swap_high")
    swap_threshold = float(swap_rule.get("threshold") or 50)
    swap_pct: float | None = None
    if metrics.swap_total_mb and metrics.swap_total_mb > 0 and metrics.swap_used_mb is not None:
        swap_pct = round(metrics.swap_used_mb * 100.0 / metrics.swap_total_mb, 1)
    if swap_pct is not None and swap_pct > swap_threshold:
        if await _check_sustained_above(db, host_id, "swap_pct", swap_threshold, minutes=int(swap_rule.get("sustain_min") or 5)):
            await _raise_or_skip(db, host_id, "swap_high", "warning",
                                 f"Swap {swap_pct}% > {swap_threshold}%",
                                 now, config=config, host_name=host_name)
    else:
        await _auto_resolve(db, host_id, "swap_high", now,
                            config=config, host_name=host_name)

    # --- Load ---
    load_rule = config.rule("load_high")
    load_factor = float(load_rule.get("threshold") or 1.5)
    load_sustain = int(load_rule.get("sustain_min") or 5)
    load_limit: float | None = None
    if metrics.cpu_cores and metrics.cpu_cores > 0:
        load_limit = metrics.cpu_cores * load_factor
    if (metrics.load_1m is not None and load_limit is not None
            and metrics.load_1m > load_limit):
        if await _check_sustained_above(db, host_id, "load_1m", load_limit, minutes=load_sustain):
            await _raise_or_skip(db, host_id, "load_high", "warning",
                                 f"Load {metrics.load_1m} > {load_limit:.2f} ({metrics.cpu_cores} cores × {load_factor})",
                                 now, config=config, host_name=host_name)
    else:
        await _auto_resolve(db, host_id, "load_high", now,
                            config=config, host_name=host_name)

    # --- Disk ---
    disk_rule = config.rule("disk_high")
    disk_warn = float(disk_rule.get("warning_threshold") or 85)
    disk_crit = float(disk_rule.get("critical_threshold") or 95)
    critical_rule = config.rule("disk_critical")
    disk_crit = float(critical_rule.get("critical_threshold") or disk_crit)
    if metrics.disk_pct is not None:
        if metrics.disk_pct > disk_crit and config.type_enabled("disk_critical"):
            await _raise_or_skip(db, host_id, "disk_critical", "critical",
                                 f"Disk {metrics.disk_pct}% > {disk_crit}%",
                                 now, config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "disk_high", now, host_name=host_name)
        elif metrics.disk_pct > disk_warn:
            await _raise_or_skip(db, host_id, "disk_high", "warning",
                                 f"Disk {metrics.disk_pct}% > {disk_warn}%",
                                 now, config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "disk_critical", now,
                                config=config, host_name=host_name)
        else:
            await _auto_resolve(db, host_id, "disk_high", now,
                                config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "disk_critical", now,
                                config=config, host_name=host_name)


async def _check_sustained_above(
    db: AsyncSession, host_id: int, field_name: str, threshold: float, minutes: int,
) -> bool:
    col = (HostMetrics.swap_used_mb * 100.0 / func.nullif(HostMetrics.swap_total_mb, 0)) if field_name == "swap_pct" else getattr(HostMetrics, field_name)
    return await _condition_sustained(db, host_id, col > threshold, minutes)


async def _check_offline_sustained(
    db: AsyncSession, host_id: int, *, field_name: str, minutes: int,
) -> bool:
    condition: Any = HostMetrics.agent_online.is_not(True)
    if field_name == "node_offline":
        condition = condition & HostMetrics.wings_online.is_not(True) & HostMetrics.public_reachable.is_not(True)
    return await _condition_sustained(db, host_id, condition, minutes)


async def _condition_sustained(db: AsyncSession, host_id: int, condition: Any, minutes: int) -> bool:
    latest = await db.scalar(select(func.max(HostMetrics.ts)).where(HostMetrics.host_id == host_id))
    if latest is None:
        return False
    # Pull retries extend collection cycles; measure the window using samples,
    # including the closest preceding sample, rather than the scheduler interval.
    baseline = select(func.max(HostMetrics.ts)).where(
        HostMetrics.host_id == host_id, HostMetrics.ts <= latest - timedelta(minutes=minutes),
    ).scalar_subquery()
    values = (await db.scalars(select(condition).where(
        HostMetrics.host_id == host_id, HostMetrics.ts >= baseline,
    ))).all()
    return len(values) >= 2 and sum(bool(value) for value in values) / len(values) >= 0.8


def _audit_alert_event(
    db: AsyncSession,
    *,
    alert_obj: HostAlert,
    kind: str,  # 'fired' | 'resolved'
    host_name: str,
    duration_seconds: int | None = None,
) -> None:
    """Commit the audit event atomically with its alert and notification queue."""
    from app.core.contracts import OperationResult

    params: dict[str, Any] = {
        "operation": OperationResult(action=f"monitoring.alert.{kind}", phase="execution", outcome="success", target={"host_id": alert_obj.host_id} if alert_obj.host_id is not None else {}).model_dump(exclude_none=True, exclude_defaults=True),
        "alert_type": alert_obj.alert_type,
        "severity": alert_obj.severity,
        "host_id": alert_obj.host_id,
        "host_name": host_name,
        "message": alert_obj.message or "",
        "fired_at": to_iso_z(alert_obj.created_at),
    }
    if kind == "resolved":
        params["resolved_at"] = to_iso_z(alert_obj.resolved_at)
        if duration_seconds is not None:
            params["duration_seconds"] = duration_seconds

    db.add(
        ManagerActivityLog(
            actor="system",
            category="monitoring",
            status="success",
            detail_key=f"monitoring.alert.{kind}",
            detail_params=json.dumps(params, ensure_ascii=False, default=str),
        )
    )


async def _raise_or_skip(
    db: AsyncSession, host_id: int | None, alert_type: str, severity: str, message: str, now: datetime,
    *,
    config: HostAlertConfig | None = None,
    host_name: str = "",
) -> None:
    # Per-host rule gate: if this alert type is disabled, do not create a new
    # row, and clear any open rows so the UI matches the admin's intent.
    # Notifications for the implicit resolution are suppressed (config=None)
    # because the disable itself is the resolution.
    if config is not None and not config.type_enabled(alert_type):
        await _auto_resolve(db, host_id, alert_type, now, config=None, host_name=host_name)
        return

    existing = await db.execute(
        select(HostAlert).where(
            HostAlert.host_id == host_id,
            HostAlert.alert_type == alert_type,
            HostAlert.resolved_at.is_(None),
        )
    )
    open_row = existing.scalar_one_or_none()
    if open_row is not None:
        if config is not None:
            await _maybe_notify(
                db, config,
                host_name=host_name,
                alert_obj=open_row, kind="fired", now=now,
            )
        return

    alert = HostAlert(
        host_id=host_id, alert_type=alert_type, severity=severity,
        message=message, created_at=now,
    )
    db.add(alert)
    await db.flush()

    _audit_alert_event(db, alert_obj=alert, kind="fired", host_name=host_name)

    if config is not None:
        await _maybe_notify(
            db, config,
            host_name=host_name,
            alert_obj=alert, kind="fired", now=now,
        )


async def _auto_resolve(
    db: AsyncSession, host_id: int | None, alert_type: str, now: datetime,
    *,
    config: HostAlertConfig | None = None,
    host_name: str = "",
) -> None:
    open_q = await db.execute(
        select(HostAlert).where(
            HostAlert.host_id == host_id,
            HostAlert.alert_type == alert_type,
            HostAlert.resolved_at.is_(None),
        )
    )
    open_rows = open_q.scalars().all()
    if not open_rows:
        return

    for row in open_rows:
        row.resolved_at = now
        duration = None
        if row.created_at is not None:
            duration = max(0, int((now - row.created_at).total_seconds()))
        _audit_alert_event(
            db, alert_obj=row, kind="resolved",
            host_name=host_name, duration_seconds=duration,
        )
        if config is not None:
            await _maybe_notify(db, config, host_name=host_name,
                                alert_obj=row, kind="resolved", now=now)


async def _check_probe_alerts(
    db: AsyncSession,
    *,
    probes: list[HostProbeResult],
    config: HostAlertConfig,
    host_name: str,
) -> None:
    """Evaluate this host's current probes, grouping shared alert types."""
    now = utc_naive_now()
    probe_alert_map = {
        "clash_proxy": ("clash_down", "warning"),
        "wings_pub": ("network_down", "critical"),
    }

    for prefix, (alert_type, severity) in probe_alert_map.items():
        matching = [p for p in probes if p.probe_name.startswith(prefix)]
        if not matching:
            continue
        failed = [p.probe_name for p in matching if not p.ok]
        if failed:
            await _raise_or_skip(
                db, config.host_id, alert_type, severity,
                f"Probe {', '.join(failed)} failed"[:500], now,
                config=config, host_name=host_name,
            )
        else:
            await _auto_resolve(
                db, config.host_id, alert_type, now,
                config=config, host_name=host_name,
            )


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


async def _pull_agent_metrics(
    endpoint: str, token: str, *, config: HostAlertConfig, budget: float,
) -> dict | None:
    last_error = ""
    try:
        async with asyncio.timeout(budget), httpx.AsyncClient(
            timeout=config.agent_pull_timeout, verify=True, trust_env=False,
        ) as client:
            for attempt in range(config.agent_pull_attempts):
                if attempt:
                    await asyncio.sleep(RETRY_BASE_DELAY * 2 ** (attempt - 1))
                try:
                    response = await client.get(f"{endpoint}/v1/metrics", headers={"Authorization": f"Bearer {token}"})
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPError as exc:
                    last_error = str(exc) or type(exc).__name__
                    logger.warning(
                        "agent pull host %d failed (attempt %d/%d): %s",
                        config.host_id, attempt + 1, config.agent_pull_attempts, last_error,
                    )
    except TimeoutError:
        last_error = f"cycle budget exceeded ({budget:g}s)"
    logger.warning("agent pull host %d unavailable: %s", config.host_id, last_error)
    return None


async def _collect_host(host: ManagerHost, *, interval: int) -> None:
    try:
        endpoint, token = host_registry.decrypt_credentials(host)
    except host_registry.AgentNotConfigured:
        return

    session_factory = get_session_factory()
    # Leave time to commit/evaluate alerts, then finish before the next scheduler tick.
    cycle_budget = interval - 5.0
    async with asyncio.timeout(cycle_budget):
        async with session_factory() as db:
            config = await _load_host_alert_config(db, host)
            node = None
            if host.kind == host_registry.KIND_WINGS_NODE and host.pterodactyl_node_id:
                node = await db.get(PanelNode, host.pterodactyl_node_id)

        async with asyncio.TaskGroup() as tasks:
            agent_task = tasks.create_task(_pull_agent_metrics(
                endpoint, token, config=config, budget=cycle_budget - 5.0,
            ))
            public_task = tasks.create_task(_probe_wings_public(
                node.id, node.fqdn, node.scheme, node.daemon_listen,
            )) if node else None

        now = utc_naive_now()
        payload = agent_task.result()
        metrics = build_metrics_row(host.id, now, payload)
        probes = [
            HostProbeResult(
                host_id=host.id, ts=now, source=f"agent:{host.id}",
                probe_name=p.get("name", "?"), ok=bool(p.get("ok")),
                latency_ms=p.get("latency_ms"), error_msg=p.get("error_msg"),
            ) for p in (payload or {}).get("probes", [])
        ]
        if public_task:
            public = public_task.result()
            metrics.public_reachable = public["ok"]
            probes.append(HostProbeResult(
                host_id=host.id, ts=now, source="manager", probe_name=f"wings_pub_{host.id}",
                ok=public["ok"], latency_ms=public.get("latency_ms"), error_msg=public.get("error_msg"),
            ))

        async with session_factory() as db:
            db.add(metrics)
            db.add_all(probes)
            if payload:
                await db.execute(update(ManagerHost).where(ManagerHost.id == host.id).values(last_seen_at=now))
            await db.commit()

        # Alert failures can roll back their own changes, but never an accepted sample.
        async with session_factory() as db:
            await _check_alerts(
                db, metrics, config=config, host_name=host.name,
                is_wings=host.kind == host_registry.KIND_WINGS_NODE,
            )
            await _check_probe_alerts(db, probes=probes, config=config, host_name=host.name)
            await db.commit()


async def run_monitoring_collect() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        hosts = list((await db.scalars(select(ManagerHost).where(ManagerHost.enabled.is_(True)))).all())
        default_interval = MONITORING_SPECS["MONITOR_INTERVAL_SEC"].default_factory()
        interval = int(await get_settings_store().get(db, "MONITOR_INTERVAL_SEC", default_interval))

    results = await asyncio.gather(
        *(_collect_host(host, interval=interval) for host in hosts), return_exceptions=True,
    )
    errors = []
    for host, result in zip(hosts, results):
        if isinstance(result, Exception):
            logger.error("monitoring host %d failed", host.id, exc_info=result)
            errors.append(result)
    if errors:
        raise RuntimeError(f"Monitoring failed for {len(errors)} host(s)") from errors[0]
    logger.debug("agent-pull cycle completed for %d hosts", len(hosts))
