from __future__ import annotations
"""Monitoring collection task — Pull from per-node Erocraft Agent V2.

Each cycle (60s by default):
  1. For every enabled ``wings_node`` manager_host: GET /v1/metrics (parallel).
  2. Persist a complete NodeMetrics row (system + wings + containers).
  3. Run the public-side reachability probe (Manager -> wings public).
  4. Evaluate alert rules and persist transitions.
  5. Cleanup data older than retention.

Per-host alert configuration lives in ``manager_host_alert_settings`` +
``manager_host_alert_rules`` and falls back to the hard-coded defaults in
``app.core.alert_defaults``. There is no longer any global ``ALERT_*`` or
``MONITOR_NODE_IDS`` runtime setting.
"""


import asyncio
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
from app.db.models.manager import HostAlertRule, HostAlertSettings, ManagerHost
from app.db.models.monitoring import NodeAlert, NodeMetrics, ProbeResult
from app.db.session import get_session_factory
from app.services import agent_client, host_registry
from app.services.metrics_builder import build_metrics_row

logger = logging.getLogger(__name__)

MONITORING_JOB_ID = "monitoring_collect"

RETRY_BASE_DELAY = 3
RETRY_MAX_ATTEMPTS = 5
RETRY_BACKOFF_FACTOR = 2


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
# Convert agent payload -> NodeMetrics row
# ---------------------------------------------------------------------------
#
# The actual builder lives in app.services.metrics_builder so that the admin
# "refresh now" endpoint can reuse it without reaching into this private
# module.  Kept here as a thin alias so the rest of this file reads the same
# way it did before the extraction.
_build_metrics_row = build_metrics_row


# ---------------------------------------------------------------------------
# Alert engine — per-host configuration
# ---------------------------------------------------------------------------


_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}


@dataclass(frozen=True, slots=True)
class HostAlertConfig:
    """Resolved per-host alert configuration (with defaults applied)."""

    host_id: int
    node_id: int | None
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
        node_id=host.pterodactyl_node_id,
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
    node_name: str,
    node_id: int | None,
    alert_obj: NodeAlert,
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
            node_name=node_name,
            node_id=node_id,
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
                node_id, alert_obj.alert_type, kind, email, err,
            )

    if sent_any and kind == "fired":
        alert_obj.notified = True
        alert_obj.last_notified_at = now


async def _check_alerts(
    db: AsyncSession,
    metrics: NodeMetrics,
    *,
    config: HostAlertConfig,
    node_name: str,
) -> None:
    node_id = config.node_id
    now = utc_naive_now()

    # --- reachability: 3 mutually-exclusive states ---
    if not metrics.agent_online and not metrics.wings_online:
        await _raise_or_skip(db, node_id, "node_offline", "critical",
                             f"Node {node_id} unreachable (agent + wings down)",
                             now, config=config, node_name=node_name)
        await _auto_resolve(db, node_id, "agent_only_down", now,
                            config=config, node_name=node_name)
        await _auto_resolve(db, node_id, "wings_only_down", now,
                            config=config, node_name=node_name)
    elif not metrics.agent_online:
        await _raise_or_skip(db, node_id, "agent_only_down", "warning",
                             f"Node {node_id} agent unreachable (wings still online)",
                             now, config=config, node_name=node_name)
        await _auto_resolve(db, node_id, "node_offline", now,
                            config=config, node_name=node_name)
        await _auto_resolve(db, node_id, "wings_only_down", now,
                            config=config, node_name=node_name)
    elif not metrics.wings_online:
        await _raise_or_skip(db, node_id, "wings_only_down", "critical",
                             f"Node {node_id} wings unreachable (agent still online)",
                             now, config=config, node_name=node_name)
        await _auto_resolve(db, node_id, "node_offline", now,
                            config=config, node_name=node_name)
        await _auto_resolve(db, node_id, "agent_only_down", now,
                            config=config, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "node_offline", now,
                            config=config, node_name=node_name)
        await _auto_resolve(db, node_id, "agent_only_down", now,
                            config=config, node_name=node_name)
        await _auto_resolve(db, node_id, "wings_only_down", now,
                            config=config, node_name=node_name)

    # --- CPU ---
    cpu_rule = config.rule("cpu_high")
    cpu_threshold = float(cpu_rule.get("threshold") or 90)
    cpu_sustain = int(cpu_rule.get("sustain_min") or 5)
    if metrics.cpu_pct is not None and metrics.cpu_pct > cpu_threshold:
        if await _check_sustained_above(db, node_id, "cpu_pct", cpu_threshold, minutes=cpu_sustain):
            await _raise_or_skip(db, node_id, "cpu_high", "warning",
                                 f"CPU {metrics.cpu_pct}% > {cpu_threshold}% sustained",
                                 now, config=config, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "cpu_high", now,
                            config=config, node_name=node_name)

    # --- Memory ---
    mem_rule = config.rule("mem_high")
    mem_threshold = float(mem_rule.get("threshold") or 90)
    mem_sustain = int(mem_rule.get("sustain_min") or 5)
    if metrics.mem_pct is not None and metrics.mem_pct > mem_threshold:
        if await _check_sustained_above(db, node_id, "mem_pct", mem_threshold, minutes=mem_sustain):
            await _raise_or_skip(db, node_id, "mem_high", "warning",
                                 f"Memory {metrics.mem_pct}% > {mem_threshold}% sustained",
                                 now, config=config, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "mem_high", now,
                            config=config, node_name=node_name)

    # --- Swap ---
    swap_rule = config.rule("swap_high")
    swap_threshold = float(swap_rule.get("threshold") or 50)
    swap_pct: float | None = None
    if metrics.swap_total_mb and metrics.swap_total_mb > 0 and metrics.swap_used_mb is not None:
        swap_pct = round(metrics.swap_used_mb * 100.0 / metrics.swap_total_mb, 1)
    if swap_pct is not None and swap_pct > swap_threshold:
        await _raise_or_skip(db, node_id, "swap_high", "warning",
                             f"Swap {swap_pct}% > {swap_threshold}%",
                             now, config=config, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "swap_high", now,
                            config=config, node_name=node_name)

    # --- Load ---
    load_rule = config.rule("load_high")
    load_factor = float(load_rule.get("threshold") or 1.5)
    load_sustain = int(load_rule.get("sustain_min") or 5)
    load_limit: float | None = None
    if metrics.cpu_cores and metrics.cpu_cores > 0:
        load_limit = metrics.cpu_cores * load_factor
    if (metrics.load_1m is not None and load_limit is not None
            and metrics.load_1m > load_limit):
        if await _check_sustained_above(db, node_id, "load_1m", load_limit, minutes=load_sustain):
            await _raise_or_skip(db, node_id, "load_high", "warning",
                                 f"Load {metrics.load_1m} > {load_limit:.2f} ({metrics.cpu_cores} cores × {load_factor})",
                                 now, config=config, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "load_high", now,
                            config=config, node_name=node_name)

    # --- Disk ---
    disk_rule = config.rule("disk_high")
    disk_warn = float(disk_rule.get("warning_threshold") or 85)
    disk_crit = float(disk_rule.get("critical_threshold") or 95)
    if metrics.disk_pct is not None:
        if metrics.disk_pct > disk_crit:
            await _raise_or_skip(db, node_id, "disk_critical", "critical",
                                 f"Disk {metrics.disk_pct}% > {disk_crit}%",
                                 now, config=config, node_name=node_name)
        elif metrics.disk_pct > disk_warn:
            await _raise_or_skip(db, node_id, "disk_high", "warning",
                                 f"Disk {metrics.disk_pct}% > {disk_warn}%",
                                 now, config=config, node_name=node_name)
            await _auto_resolve(db, node_id, "disk_critical", now,
                                config=config, node_name=node_name)
        else:
            await _auto_resolve(db, node_id, "disk_high", now,
                                config=config, node_name=node_name)
            await _auto_resolve(db, node_id, "disk_critical", now,
                                config=config, node_name=node_name)


async def _check_sustained_above(
    db: AsyncSession, node_id: int, field_name: str, threshold: float, minutes: int,
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
    col = getattr(NodeMetrics, field_name)
    cutoff = utc_naive_now() - timedelta(minutes=minutes)
    result = await db.execute(
        select(col, NodeMetrics.ts)
        .where(NodeMetrics.node_id == node_id, col.isnot(None), NodeMetrics.ts >= cutoff)
        .order_by(NodeMetrics.ts.asc())
    )
    rows = result.all()
    if len(rows) < 3:
        return False
    above = sum(1 for v, _ts in rows if v > threshold)
    return (above / len(rows)) >= 0.8


async def _raise_or_skip(
    db: AsyncSession, node_id: int | None, alert_type: str, severity: str, message: str, now: datetime,
    *,
    config: HostAlertConfig | None = None,
    node_name: str = "",
) -> None:
    existing = await db.execute(
        select(NodeAlert).where(
            NodeAlert.node_id == node_id,
            NodeAlert.alert_type == alert_type,
            NodeAlert.resolved_at.is_(None),
        )
    )
    open_row = existing.scalar_one_or_none()
    if open_row is not None:
        if config is not None:
            await _maybe_notify(
                db, config,
                node_name=node_name, node_id=node_id,
                alert_obj=open_row, kind="fired", now=now,
            )
        return

    alert = NodeAlert(
        node_id=node_id, alert_type=alert_type, severity=severity,
        message=message, created_at=now,
    )
    db.add(alert)
    await db.flush()

    if config is not None:
        await _maybe_notify(
            db, config,
            node_name=node_name, node_id=node_id,
            alert_obj=alert, kind="fired", now=now,
        )


async def _auto_resolve(
    db: AsyncSession, node_id: int | None, alert_type: str, now: datetime,
    *,
    config: HostAlertConfig | None = None,
    node_name: str = "",
) -> None:
    open_q = await db.execute(
        select(NodeAlert).where(
            NodeAlert.node_id == node_id,
            NodeAlert.alert_type == alert_type,
            NodeAlert.resolved_at.is_(None),
        )
    )
    open_rows = open_q.scalars().all()
    if not open_rows:
        return

    for row in open_rows:
        row.resolved_at = now

    if config is not None and config.notify_resolve:
        for row in open_rows:
            if row.notified:
                await _maybe_notify(
                    db, config,
                    node_name=node_name, node_id=node_id,
                    alert_obj=row, kind="resolved", now=now,
                )


async def _check_probe_alerts(
    db: AsyncSession,
    *,
    host_configs: dict[int, HostAlertConfig],
    node_names: dict[int, str],
) -> None:
    """Per-node probe alerting.

    ``ProbeResult`` rows carry two orthogonal identifiers:

    * ``source`` — ``"manager"`` for the public-side Wings probe, or
      ``"agent:<node_id>"`` for agent-reported probes.
    * ``probe_name`` — user-defined or ``wings_pub_<node_id>``.

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
            ProbeResult.source,
            ProbeResult.probe_name,
            func.max(ProbeResult.ts).label("max_ts"),
        )
        .where(ProbeResult.ts >= cutoff)
        .group_by(ProbeResult.source, ProbeResult.probe_name)
        .subquery()
    )
    latest_rows = await db.execute(
        select(ProbeResult).join(
            latest_ts_subq,
            (ProbeResult.source == latest_ts_subq.c.source)
            & (ProbeResult.probe_name == latest_ts_subq.c.probe_name)
            & (ProbeResult.ts == latest_ts_subq.c.max_ts),
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

        node_id: int | None = None
        if probe.source and probe.source.startswith("agent:"):
            try:
                node_id = int(probe.source.split(":", 1)[1])
            except ValueError:
                node_id = None
        elif probe.probe_name.startswith("wings_pub_"):
            try:
                node_id = int(probe.probe_name.rsplit("_", 1)[-1])
            except ValueError:
                node_id = None

        node_name = node_names.get(node_id or -1, "") if node_id is not None else ""
        config = host_configs.get(node_id) if node_id is not None else None

        if not probe.ok:
            await _raise_or_skip(
                db, node_id, alert_type, severity,
                f"Probe {probe.probe_name} failed", now,
                config=config, node_name=node_name,
            )
        else:
            await _auto_resolve(
                db, node_id, alert_type, now,
                config=config, node_name=node_name,
            )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def _cleanup_old_data(db: AsyncSession) -> None:
    store = get_settings_store()
    days = int(await store.get(db, "MONITOR_RETENTION_DAYS", 30))
    cutoff = utc_naive_now() - timedelta(days=days)
    await db.execute(sa_delete(NodeMetrics).where(NodeMetrics.ts < cutoff))
    await db.execute(sa_delete(ProbeResult).where(ProbeResult.ts < cutoff))
    await db.execute(
        sa_delete(NodeAlert).where(
            NodeAlert.resolved_at.isnot(None),
            NodeAlert.created_at < cutoff,
        )
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_monitoring_collect() -> None:
    """One full pull cycle. Called every 60 s by the scheduler."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        now = utc_naive_now()

        from app.db.models.pterodactyl import PanelNode

        # Enabled wings_node manager_hosts drive the pull loop.
        host_result = await db.execute(
            select(ManagerHost).where(
                ManagerHost.kind == host_registry.KIND_WINGS_NODE,
                ManagerHost.enabled.is_(True),
                ManagerHost.pterodactyl_node_id.isnot(None),
            )
        )
        hosts = host_result.scalars().all()
        if not hosts:
            return

        monitored_ids = [h.pterodactyl_node_id for h in hosts]  # type: ignore[list-item]

        result = await db.execute(select(PanelNode).where(PanelNode.id.in_(monitored_ids)))
        nodes = {n.id: n for n in result.scalars().all()}

        # Global default recipients (used when a host row leaves recipients
        # as NULL). Stored as comma-separated string of admin ids.
        global_recipients = await _load_global_default_recipients(db)

        # Resolve per-host alert config once per cycle.
        host_configs: dict[int, HostAlertConfig] = {}
        meta_map: dict[int, tuple[str, str, int]] = {}
        for host in hosts:
            if host.pterodactyl_node_id is None:
                continue
            config = await _load_host_alert_config(
                db, host, global_default_recipients=global_recipients,
            )
            host_configs[host.pterodactyl_node_id] = config
            try:
                endpoint, token = host_registry.decrypt_credentials(host)
            except host_registry.AgentNotConfigured as exc:
                logger.warning(
                    "agent credentials unusable for node %d (host=%d): %s",
                    host.pterodactyl_node_id, host.id, exc,
                )
                continue
            meta_map[host.pterodactyl_node_id] = (endpoint, token, host.id)

        async def _pull_direct(node_id: int) -> dict | None:
            ep_tok = meta_map.get(node_id)
            if not ep_tok:
                return None
            endpoint, token, _host_id = ep_tok
            url = f"{endpoint}/v1/metrics"
            try:
                async with httpx.AsyncClient(timeout=10.0, verify=True, trust_env=False) as client:
                    resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                if resp.status_code >= 400:
                    logger.warning("agent pull node %d -> HTTP %d", node_id, resp.status_code)
                    return None
                return resp.json()
            except httpx.HTTPError as exc:
                logger.warning("agent pull node %d transport: %s", node_id, exc)
                return None

        async def _collect(node_id: int) -> tuple[int, dict | None, dict]:
            node = nodes.get(node_id)
            if not node:
                logger.warning("monitored node %d not found in panel DB", node_id)
                return node_id, None, {"ok": False, "error_msg": "Node not in DB"}
            agent_payload, pub_result = await asyncio.gather(
                _pull_direct(node_id),
                _probe_wings_public(node_id, node.fqdn, node.scheme, node.daemon_listen),
            )
            return node_id, agent_payload, pub_result

        try:
            raw_results = await asyncio.gather(
                *[_collect(nid) for nid in monitored_ids],
                return_exceptions=True,
            )
        except Exception:  # pragma: no cover
            logger.exception("monitoring pull cycle crashed unexpectedly")
            raw_results = []

        results: list[tuple[int, dict | None, dict]] = []
        for nid, item in zip(monitored_ids, raw_results):
            if isinstance(item, BaseException):
                logger.warning("monitoring _collect(%d) failed: %r", nid, item)
                results.append((nid, None, {"ok": False, "error_msg": f"collect error: {item!r}"}))
            else:
                results.append(item)

        for node_id, agent_payload, pub_result in results:
            db.add(ProbeResult(
                ts=now, source="manager",
                probe_name=f"wings_pub_{node_id}",
                ok=pub_result["ok"],
                latency_ms=pub_result.get("latency_ms"),
                error_msg=pub_result.get("error_msg"),
            ))

            metrics_row = _build_metrics_row(node_id, now, agent_payload)
            metrics_row.public_reachable = pub_result["ok"]
            db.add(metrics_row)

            if agent_payload:
                for p in agent_payload.get("probes", []):
                    db.add(ProbeResult(
                        ts=now,
                        source=f"agent:{node_id}",
                        probe_name=p.get("name", "?"),
                        ok=bool(p.get("ok")),
                        latency_ms=p.get("latency_ms"),
                        error_msg=p.get("error_msg"),
                    ))

            config = host_configs.get(node_id)
            if config is not None:
                await _check_alerts(
                    db, metrics_row,
                    config=config,
                    node_name=nodes[node_id].name if node_id in nodes else f"node-{node_id}",
                )

        await _check_probe_alerts(
            db,
            host_configs=host_configs,
            node_names={nid: n.name for nid, n in nodes.items()},
        )
        await _cleanup_old_data(db)

        # Mark hosts whose agent answered this cycle as freshly seen.
        seen_host_ids = [
            meta_map[node_id][2]
            for node_id, agent_payload, _ in results
            if agent_payload is not None and node_id in meta_map
        ]
        if seen_host_ids:
            await db.execute(
                ManagerHost.__table__.update()
                .where(ManagerHost.id.in_(seen_host_ids))
                .values(last_seen_at=now)
            )

        await db.commit()
        logger.debug("agent-pull cycle committed for %d nodes", len(monitored_ids))
