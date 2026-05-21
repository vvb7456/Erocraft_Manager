from __future__ import annotations
"""Monitoring collection task — Pull from per-node Erocraft Agent V2.

Each cycle (60s by default):
  1. For every enabled ``wings_node`` manager_host: GET /v1/metrics (parallel).
  2. Persist a complete HostMetrics row (system + wings + containers).
  3. Run the public-side reachability probe (Manager -> wings public).
  4. Evaluate alert rules and persist transitions.
  5. Cleanup data older than retention.

Per-host alert configuration lives in ``manager_host_alert_settings`` +
``manager_host_alert_rules`` and falls back to the hard-coded defaults in
``app.core.alert_defaults``. There is no longer any global ``ALERT_*`` or
``MONITOR_NODE_IDS`` runtime setting.
"""


import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import alert_defaults
from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.manager import (
    HostAlertRule,
    HostAlertSettings,
    ManagerActivityLog,
    ManagerHost,
)
from app.db.models.monitoring import HostAlert, HostMetrics, HostProbeResult
from app.db.session import get_session_factory
from app.services import agent_client, host_registry
from app.services.metrics_builder import build_metrics_row

logger = logging.getLogger(__name__)

MONITORING_JOB_ID = "monitoring_collect"

RETRY_BASE_DELAY = 3
RETRY_MAX_ATTEMPTS = 5
RETRY_BACKOFF_FACTOR = 2

# Agent /v1/metrics pull retry policy.
# Total worst case = 5 + 2 + 5 + 4 + 5 = 21 s, well within the 60 s cycle.
# Tighter than _probe_wings_public on purpose: a single missed pull must NOT
# fire an "agent offline" alert (see audit 2026-05-22), but we also must not
# delay a real-outage notification past the cycle window.
AGENT_PULL_TIMEOUT = 5.0
AGENT_PULL_ATTEMPTS = 3  # 1 initial + 2 retries
AGENT_PULL_RETRY_BASE_DELAY = 2.0
AGENT_PULL_RETRY_BACKOFF_FACTOR = 2.0


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

    async def _try() -> dict:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=True, trust_env=False) as client:
                resp = await client.get(url)
            latency = round((time.monotonic() - start) * 1000, 1)
            return {"ok": True, "latency_ms": latency}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error_msg": str(exc)[:200]}

    result = await _try()
    if result["ok"]:
        return result

    delay = RETRY_BASE_DELAY
    for attempt in range(RETRY_MAX_ATTEMPTS):
        await asyncio.sleep(delay)
        result = await _try()
        if result["ok"]:
            logger.info("wings public probe node %d recovered on retry #%d", node_id, attempt + 1)
            return result
        delay = min(delay * RETRY_BACKOFF_FACTOR, 60)

    logger.warning("wings public probe node %d failed after %d retries", node_id, RETRY_MAX_ATTEMPTS)
    return result


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Alert engine — per-host configuration
# ---------------------------------------------------------------------------


_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}


@dataclass(frozen=True, slots=True)
class HostAlertConfig:
    """Resolved per-host alert configuration (with defaults applied)."""

    host_id: int
    email_enabled: bool
    email_recipients: list[int]  # admin user ids; [] = use ALERT_DEFAULT_RECIPIENTS
    min_severity: str
    notify_resolve: bool
    cooldown_min: int
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)

    def rule(self, alert_type: str) -> dict[str, Any]:
        return self.rules.get(alert_type) or alert_defaults.default_rule(alert_type)

    def type_enabled(self, alert_type: str) -> bool:
        return bool(self.rule(alert_type).get("enabled", False))


async def _load_host_alert_config(
    db: AsyncSession,
    host: ManagerHost,
    *,
    global_default_recipients: list[int],
) -> HostAlertConfig:
    """Load + merge per-host alert configuration, falling back to defaults."""

    settings_row = (
        await db.execute(
            select(HostAlertSettings).where(HostAlertSettings.host_id == host.id)
        )
    ).scalar_one_or_none()

    email_enabled = alert_defaults.DEFAULT_EMAIL_ENABLED
    recipients: list[int] = list(global_default_recipients)
    min_severity = alert_defaults.DEFAULT_MIN_SEVERITY
    notify_resolve = alert_defaults.DEFAULT_NOTIFY_RESOLVE
    cooldown_min = alert_defaults.DEFAULT_COOLDOWN_MIN

    if settings_row is not None:
        if settings_row.email_enabled is not None:
            email_enabled = bool(settings_row.email_enabled)
        if settings_row.email_recipients is not None:
            # None on the column means "inherit global default"; an
            # explicit empty list [] means "override to empty — send
            # to no one". The admin UI should surface this distinction
            # (design doc §4.4): clearing the field clears the
            # override; saving an empty list saves an empty list.
            raw = settings_row.email_recipients
            if isinstance(raw, list):
                recipients = [int(x) for x in raw if isinstance(x, (int, str)) and str(x).isdigit()]
        if settings_row.min_severity:
            min_severity = settings_row.min_severity
        if settings_row.notify_resolve is not None:
            notify_resolve = bool(settings_row.notify_resolve)
        if settings_row.cooldown_min is not None:
            cooldown_min = int(settings_row.cooldown_min)

    rule_rows = (
        await db.execute(
            select(HostAlertRule).where(HostAlertRule.host_id == host.id)
        )
    ).scalars().all()

    rules: dict[str, dict[str, Any]] = {}
    for atype in alert_defaults.ALERT_TYPES:
        rules[atype] = alert_defaults.default_rule(atype)
    for row in rule_rows:
        override: dict[str, Any] = {"enabled": row.enabled}
        if row.threshold is not None:
            override["threshold"] = float(row.threshold)
        if row.warning_threshold is not None:
            override["warning_threshold"] = float(row.warning_threshold)
        if row.critical_threshold is not None:
            override["critical_threshold"] = float(row.critical_threshold)
        if row.sustain_min is not None:
            override["sustain_min"] = int(row.sustain_min)
        rules[row.alert_type] = alert_defaults.merge_rule(row.alert_type, override)

    return HostAlertConfig(
        host_id=host.id,
        email_enabled=email_enabled,
        email_recipients=recipients,
        min_severity=min_severity,
        notify_resolve=notify_resolve,
        cooldown_min=cooldown_min,
        rules=rules,
    )


async def _load_global_default_recipients(db: AsyncSession) -> list[int]:
    """Read ``ALERT_DEFAULT_RECIPIENTS`` (comma-separated admin ids) from settings."""

    store = get_settings_store()
    raw = await store.get(db, "ALERT_DEFAULT_RECIPIENTS", "") or ""
    return [int(x) for x in str(raw).split(",") if x.strip().isdigit()]


async def _resolve_admin_emails(db: AsyncSession, admin_ids: list[int]) -> list[tuple[int, str]]:
    """Resolve admin user IDs to (id, email) pairs. Empty list -> all admins."""
    from app.db.models.pterodactyl import PteroUser

    if admin_ids:
        stmt = select(PteroUser.id, PteroUser.email).where(
            PteroUser.id.in_(admin_ids), PteroUser.root_admin.is_(True),
        )
    else:
        stmt = select(PteroUser.id, PteroUser.email).where(PteroUser.root_admin.is_(True))
    result = await db.execute(stmt)
    return [(rid, email) for rid, email in result.all() if email]


def _severity_passes(config: HostAlertConfig, severity: str) -> bool:
    min_rank = _SEVERITY_RANK.get(config.min_severity, 1)
    cur_rank = _SEVERITY_RANK.get(severity, 1)
    return cur_rank >= min_rank


async def _maybe_notify(
    db: AsyncSession,
    config: HostAlertConfig,
    *,
    host_name: str,
    host_id: int | None,
    alert_obj: HostAlert,
    kind: str,  # 'fired' | 'resolved'
    now: datetime,
) -> None:
    """Apply gating (channel enabled / type / severity / cooldown) then send."""
    if not config.email_enabled:
        return
    if kind == "resolved" and not config.notify_resolve:
        return
    if not config.type_enabled(alert_obj.alert_type):
        return
    if not _severity_passes(config, alert_obj.severity):
        return

    if kind == "fired":
        last_at = alert_obj.last_notified_at
        if last_at and (now - last_at) < timedelta(minutes=config.cooldown_min):
            return

    recipients = await _resolve_admin_emails(db, config.email_recipients)
    if not recipients:
        return

    from app.services.email import send_alert_email
    sent_any = False
    for _uid, email in recipients:
        ok, err = await send_alert_email(
            db,
            recipient_email=email,
            host_name=host_name,
            host_id=host_id,
            alert_type=alert_obj.alert_type,
            severity=alert_obj.severity,
            message=alert_obj.message or "",
            fired_at=alert_obj.created_at,
            resolved_at=alert_obj.resolved_at,
            kind=kind,
        )
        if ok:
            sent_any = True
        else:
            logger.warning(
                "alert email send failed (node=%s type=%s kind=%s recipient=%s): %s",
                host_id, alert_obj.alert_type, kind, email, err,
            )

    if sent_any and kind == "fired":
        alert_obj.notified = True
        alert_obj.last_notified_at = now


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

    # --- reachability ---
    if is_wings:
        # 3 mutually-exclusive states for wings nodes
        if not metrics.agent_online and not metrics.wings_online:
            await _raise_or_skip(db, host_id, "node_offline", "critical",
                                 f"Host {host_id} unreachable (agent + wings down)",
                                 now, config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "agent_only_down", now,
                                config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "wings_only_down", now,
                                config=config, host_name=host_name)
        elif not metrics.agent_online:
            await _raise_or_skip(db, host_id, "agent_only_down", "warning",
                                 f"Host {host_id} agent unreachable (wings still online)",
                                 now, config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "node_offline", now,
                                config=config, host_name=host_name)
            await _auto_resolve(db, host_id, "wings_only_down", now,
                                config=config, host_name=host_name)
        elif not metrics.wings_online:
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
        if not metrics.agent_online:
            await _raise_or_skip(db, host_id, "agent_only_down", "critical",
                                 f"Host {host_id} agent unreachable",
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
    if metrics.disk_pct is not None:
        if metrics.disk_pct > disk_crit:
            await _raise_or_skip(db, host_id, "disk_critical", "critical",
                                 f"Disk {metrics.disk_pct}% > {disk_crit}%",
                                 now, config=config, host_name=host_name)
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
    """Return True if the field has been sustainedly above threshold.

    New semantics (see CR M5 / 2.6):
      - Look back `minutes` minutes.
      - Require at least 3 non-null samples to avoid cold-start false positives.
      - Require >= 80% of samples to be > threshold (allows brief dips).
      - The previous `(rows[-1] - rows[0]) >= (minutes-1)*60s` span guard is
        removed: it caused alert delay whenever the pull loop drifted a few
        seconds, while adding no real safety (the sample-count gate already
        prevents firing on a single spike).
    """
    col = getattr(HostMetrics, field_name)
    cutoff = utc_naive_now() - timedelta(minutes=minutes)
    result = await db.execute(
        select(col, HostMetrics.ts)
        .where(HostMetrics.host_id == host_id, col.isnot(None), HostMetrics.ts >= cutoff)
        .order_by(HostMetrics.ts.asc())
    )
    rows = result.all()
    if len(rows) < 3:
        return False
    above = sum(1 for v, _ts in rows if v > threshold)
    return (above / len(rows)) >= 0.8


_SEVERITY_TO_AUDIT_STATUS = {"critical": "failed", "warning": "partial", "info": "info"}


def _audit_alert_event(
    db: AsyncSession,
    *,
    alert_obj: HostAlert,
    kind: str,  # 'fired' | 'resolved'
    host_name: str,
    duration_seconds: int | None = None,
) -> None:
    """Persist a `monitoring.alert.{fired,resolved}` row in `manager_activity_logs`.

    Uses the caller's session so the audit row is committed atomically with the
    rest of the monitoring cycle (no separate transaction, no early commit).
    """
    if kind == "resolved":
        status = "success"
    else:
        status = _SEVERITY_TO_AUDIT_STATUS.get(alert_obj.severity, "info")

    params: dict[str, Any] = {
        "alert_type": alert_obj.alert_type,
        "severity": alert_obj.severity,
        "host_id": alert_obj.host_id,
        "host_name": host_name,
        "message": alert_obj.message or "",
        "fired_at": alert_obj.created_at.isoformat() if alert_obj.created_at else None,
    }
    if kind == "resolved":
        params["resolved_at"] = alert_obj.resolved_at.isoformat() if alert_obj.resolved_at else None
        if duration_seconds is not None:
            params["duration_seconds"] = duration_seconds

    db.add(
        ManagerActivityLog(
            actor="system",
            category="monitoring",
            status=status,
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
                host_name=host_name, host_id=host_id,
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
            host_name=host_name, host_id=host_id,
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

    if config is not None and config.notify_resolve:
        for row in open_rows:
            if row.notified:
                await _maybe_notify(
                    db, config,
                    host_name=host_name, host_id=host_id,
                    alert_obj=row, kind="resolved", now=now,
                )


async def _check_probe_alerts(
    db: AsyncSession,
    *,
    host_configs: dict[int, HostAlertConfig],
    host_names: dict[int, str],
) -> None:
    """Per-node probe alerting.

    ``HostProbeResult`` rows carry two orthogonal identifiers:

    * ``source`` — ``"manager"`` for the public-side Wings probe, or
      ``"agent:<host_id>"`` for agent-reported probes.
    * ``probe_name`` — user-defined or ``wings_pub_<host_id>``.

    We look at the latest row for each ``(source, probe_name)`` pair and
    raise / auto-resolve one alert per node, using the corresponding
    host's alert configuration.
    """
    now = utc_naive_now()
    probe_alert_map = {
        "clash_proxy": ("clash_down", "warning"),
        "wings_pub": ("network_down", "critical"),
    }

    cutoff = now - timedelta(minutes=5)
    latest_ts_subq = (
        select(
            HostProbeResult.source,
            HostProbeResult.probe_name,
            func.max(HostProbeResult.ts).label("max_ts"),
        )
        .where(HostProbeResult.ts >= cutoff)
        .group_by(HostProbeResult.source, HostProbeResult.probe_name)
        .subquery()
    )
    latest_rows = await db.execute(
        select(HostProbeResult).join(
            latest_ts_subq,
            (HostProbeResult.source == latest_ts_subq.c.source)
            & (HostProbeResult.probe_name == latest_ts_subq.c.probe_name)
            & (HostProbeResult.ts == latest_ts_subq.c.max_ts),
        )
    )

    for probe in latest_rows.scalars().all():
        matched: tuple[str, str] | None = None
        for prefix, spec in probe_alert_map.items():
            if probe.probe_name.startswith(prefix):
                matched = spec
                break
        if matched is None:
            continue
        alert_type, severity = matched

        host_id: int | None = None
        if probe.source and probe.source.startswith("agent:"):
            try:
                host_id = int(probe.source.split(":", 1)[1])
            except ValueError:
                host_id = None
        elif probe.probe_name.startswith("wings_pub_"):
            try:
                host_id = int(probe.probe_name.rsplit("_", 1)[-1])
            except ValueError:
                host_id = None

        host_name = host_names.get(host_id or -1, "") if host_id is not None else ""
        config = host_configs.get(host_id) if host_id is not None else None

        if not probe.ok:
            await _raise_or_skip(
                db, host_id, alert_type, severity,
                f"Probe {probe.probe_name} failed", now,
                config=config, host_name=host_name,
            )
        else:
            await _auto_resolve(
                db, host_id, alert_type, now,
                config=config, host_name=host_name,
            )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def _cleanup_old_data(db: AsyncSession) -> None:
    store = get_settings_store()
    days = int(await store.get(db, "MONITOR_RETENTION_DAYS", 30))
    cutoff = utc_naive_now() - timedelta(days=days)
    await db.execute(sa_delete(HostMetrics).where(HostMetrics.ts < cutoff))
    await db.execute(sa_delete(HostProbeResult).where(HostProbeResult.ts < cutoff))
    await db.execute(
        sa_delete(HostAlert).where(
            HostAlert.resolved_at.isnot(None),
            HostAlert.created_at < cutoff,
        )
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_monitoring_collect() -> None:
    """One full pull cycle. Called every 60 s by the scheduler.

    Iterates all enabled manager_hosts, pulls /v1/metrics from each agent,
    stores metrics + probes keyed by host_id, and evaluates alert rules.
    Wings hosts additionally get a public-side wings reachability probe.
    """
    session_factory = get_session_factory()
    async with session_factory() as db:
        now = utc_naive_now()

        from app.db.models.pterodactyl import PanelNode

        # All enabled hosts participate in the pull loop.
        host_result = await db.execute(
            select(ManagerHost).where(ManagerHost.enabled.is_(True))
        )
        hosts = host_result.scalars().all()
        if not hosts:
            return

        # Pre-load panel nodes for wings hosts (public probe needs fqdn/scheme/port).
        wings_hosts = [h for h in hosts if h.kind == host_registry.KIND_WINGS_NODE
                       and h.pterodactyl_node_id is not None]
        wings_nodes: dict[int, PanelNode] = {}
        if wings_hosts:
            nids = [h.pterodactyl_node_id for h in wings_hosts]
            nresult = await db.execute(select(PanelNode).where(PanelNode.id.in_(nids)))
            wings_nodes = {n.id: n for n in nresult.scalars().all()}

        global_recipients = await _load_global_default_recipients(db)

        # Resolve credentials + alert config per host.
        host_metas: list[tuple[ManagerHost, str, str]] = []
        host_configs: dict[int, HostAlertConfig] = {}
        for host in hosts:
            config = await _load_host_alert_config(
                db, host, global_default_recipients=global_recipients,
            )
            host_configs[host.id] = config
            try:
                endpoint, token = host_registry.decrypt_credentials(host)
            except host_registry.AgentNotConfigured:
                continue
            host_metas.append((host, endpoint, token))

        async def _pull(host: ManagerHost, endpoint: str, token: str) -> tuple[int, dict | None]:
            url = f"{endpoint}/v1/metrics"
            headers = {"Authorization": f"Bearer {token}"}
            last_err: str | None = None
            delay = AGENT_PULL_RETRY_BASE_DELAY
            for attempt in range(1, AGENT_PULL_ATTEMPTS + 1):
                try:
                    async with httpx.AsyncClient(
                        timeout=AGENT_PULL_TIMEOUT, verify=True, trust_env=False
                    ) as client:
                        resp = await client.get(url, headers=headers)
                    if resp.status_code >= 400:
                        last_err = f"HTTP {resp.status_code}"
                        logger.warning(
                            "agent pull host %d -> HTTP %d (attempt %d/%d)",
                            host.id, resp.status_code, attempt, AGENT_PULL_ATTEMPTS,
                        )
                    else:
                        if attempt > 1:
                            logger.info(
                                "agent pull host %d recovered on retry #%d",
                                host.id, attempt - 1,
                            )
                        return host.id, resp.json()
                except httpx.HTTPError as exc:
                    last_err = str(exc) or exc.__class__.__name__
                    logger.warning(
                        "agent pull host %d transport: %s (attempt %d/%d)",
                        host.id, last_err, attempt, AGENT_PULL_ATTEMPTS,
                    )
                if attempt < AGENT_PULL_ATTEMPTS:
                    await asyncio.sleep(delay)
                    delay *= AGENT_PULL_RETRY_BACKOFF_FACTOR
            logger.warning(
                "agent pull host %d failed after %d attempts: %s",
                host.id, AGENT_PULL_ATTEMPTS, last_err,
            )
            return host.id, None

        async def _collect(host: ManagerHost, endpoint: str, token: str) -> tuple[int, dict | None, dict | None]:
            public_task = None
            node = None
            if host.kind == host_registry.KIND_WINGS_NODE and host.pterodactyl_node_id:
                node = wings_nodes.get(host.pterodactyl_node_id)
                if node:
                    public_task = asyncio.create_task(
                        _probe_wings_public(host.pterodactyl_node_id, node.fqdn, node.scheme, node.daemon_listen)
                    )
            host_id, agent_payload = await _pull(host, endpoint, token)
            pub_result = await public_task if public_task else None
            return host_id, agent_payload, pub_result

        raw_results = await asyncio.gather(
            *[_collect(h, ep, tok) for h, ep, tok in host_metas],
            return_exceptions=True,
        )

        results: list[tuple[int, dict | None, dict | None]] = []
        for item in raw_results:
            if isinstance(item, BaseException):
                logger.warning("monitoring _collect failed: %r", item)
            else:
                results.append(item)

        seen_host_ids: list[int] = []
        for host_id, agent_payload, pub_result in results:
            # Public probe (wings only).
            if pub_result is not None:
                db.add(HostProbeResult(
                    host_id=host_id, ts=now, source="manager",
                    probe_name=f"wings_pub_{host_id}",
                    ok=pub_result["ok"],
                    latency_ms=pub_result.get("latency_ms"),
                    error_msg=pub_result.get("error_msg"),
                ))

            metrics_row = build_metrics_row(host_id, now, agent_payload)
            if pub_result is not None:
                metrics_row.public_reachable = pub_result["ok"]
            db.add(metrics_row)

            if agent_payload:
                seen_host_ids.append(host_id)
                for p in agent_payload.get("probes", []):
                    db.add(HostProbeResult(
                        host_id=host_id, ts=now,
                        source=f"agent:{host_id}",
                        probe_name=p.get("name", "?"),
                        ok=bool(p.get("ok")),
                        latency_ms=p.get("latency_ms"),
                        error_msg=p.get("error_msg"),
                    ))

            config = host_configs.get(host_id)
            if config is not None:
                host = next((h for h in hosts if h.id == host_id), None)
                host_name = host.name if host else f"host-{host_id}"
                host_is_wings = host.kind == host_registry.KIND_WINGS_NODE if host else False
                await _check_alerts(db, metrics_row, config=config, host_name=host_name, is_wings=host_is_wings)

        await _check_probe_alerts(db, host_configs=host_configs, host_names={h.id: h.name for h in hosts})
        await _cleanup_old_data(db)

        if seen_host_ids:
            await db.execute(
                ManagerHost.__table__.update()
                .where(ManagerHost.id.in_(seen_host_ids))
                .values(last_seen_at=now)
            )

        await db.commit()
        logger.debug("agent-pull cycle committed for %d hosts", len(results))
