from __future__ import annotations
"""Monitoring collection task — Pull from per-node Erocraft Agent V2.

Each cycle (60s by default):
  1. For every monitored node: GET /v1/metrics from its agent (parallel).
  2. Persist a complete NodeMetrics row (system + wings + containers).
  3. Run the public-side reachability probe (Manager -> wings public).
  4. Evaluate alert rules and persist transitions.
  5. Cleanup data older than retention.
"""


import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_store import get_settings_store
from app.core.time import utc_naive_now
from app.db.models.monitoring import NodeAlert, NodeMetrics, ProbeResult
from app.db.session import get_session_factory
from app.services import agent_client
from app.services.metrics_builder import build_metrics_row

logger = logging.getLogger(__name__)

MONITORING_JOB_ID = "monitoring_collect"

RETRY_BASE_DELAY = 3
RETRY_MAX_ATTEMPTS = 5
RETRY_BACKOFF_FACTOR = 2


# ---------------------------------------------------------------------------
# Pull a single node's full metrics snapshot via its agent
# ---------------------------------------------------------------------------


async def _pull_node_via_agent(db: AsyncSession, node_id: int) -> dict | None:
    try:
        return await agent_client.fetch_metrics(db, node_id, timeout=10.0)
    except agent_client.AgentNotConfigured:
        logger.debug("agent not configured for node %d, skipping pull", node_id)
        return None
    except agent_client.AgentClientError as exc:
        logger.warning("agent pull failed for node %d: %s", node_id, exc)
        return None


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
# Alert engine
# ---------------------------------------------------------------------------


_ALERT_SETTING_KEYS: tuple[str, ...] = (
    "ALERT_EMAIL_ENABLED",
    "ALERT_EMAIL_ADMIN_IDS",
    "ALERT_NOTIFY_RESOLVE",
    "ALERT_MIN_SEVERITY",
    "ALERT_COOLDOWN_MIN",
    "ALERT_CPU_THRESHOLD",
    "ALERT_CPU_SUSTAIN_MIN",
    "ALERT_MEM_THRESHOLD",
    "ALERT_MEM_SUSTAIN_MIN",
    "ALERT_SWAP_THRESHOLD",
    "ALERT_DISK_WARNING",
    "ALERT_DISK_CRITICAL",
    "ALERT_LOAD_FACTOR",
    "ALERT_LOAD_SUSTAIN_MIN",
    "ALERT_TYPE_NODE_OFFLINE",
    "ALERT_TYPE_AGENT_ONLY_DOWN",
    "ALERT_TYPE_WINGS_ONLY_DOWN",
    "ALERT_TYPE_CPU_HIGH",
    "ALERT_TYPE_MEM_HIGH",
    "ALERT_TYPE_SWAP_HIGH",
    "ALERT_TYPE_DISK_HIGH",
    "ALERT_TYPE_DISK_CRITICAL",
    "ALERT_TYPE_LOAD_HIGH",
    "ALERT_TYPE_NETWORK_DOWN",
    "ALERT_TYPE_CLASH_DOWN",
)

_TYPE_TO_SETTING_KEY: dict[str, str] = {
    "node_offline":     "ALERT_TYPE_NODE_OFFLINE",
    "agent_only_down":  "ALERT_TYPE_AGENT_ONLY_DOWN",
    "wings_only_down":  "ALERT_TYPE_WINGS_ONLY_DOWN",
    "cpu_high":         "ALERT_TYPE_CPU_HIGH",
    "mem_high":         "ALERT_TYPE_MEM_HIGH",
    "swap_high":        "ALERT_TYPE_SWAP_HIGH",
    "disk_high":        "ALERT_TYPE_DISK_HIGH",
    "disk_critical":    "ALERT_TYPE_DISK_CRITICAL",
    "load_high":        "ALERT_TYPE_LOAD_HIGH",
    "network_down":     "ALERT_TYPE_NETWORK_DOWN",
    "clash_down":       "ALERT_TYPE_CLASH_DOWN",
}

_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}


def _to_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


async def _load_alert_settings(db: AsyncSession) -> dict[str, object]:
    store = get_settings_store()
    defaults = {
        "ALERT_EMAIL_ENABLED": False,
        "ALERT_EMAIL_ADMIN_IDS": "",
        "ALERT_NOTIFY_RESOLVE": False,
        "ALERT_MIN_SEVERITY": "warning",
        "ALERT_COOLDOWN_MIN": 30,
        "ALERT_CPU_THRESHOLD": 90,
        "ALERT_CPU_SUSTAIN_MIN": 5,
        "ALERT_MEM_THRESHOLD": 90,
        "ALERT_MEM_SUSTAIN_MIN": 5,
        "ALERT_SWAP_THRESHOLD": 50,
        "ALERT_DISK_WARNING": 85,
        "ALERT_DISK_CRITICAL": 95,
        "ALERT_LOAD_FACTOR": 1.5,
        "ALERT_LOAD_SUSTAIN_MIN": 5,
    }
    for k in _TYPE_TO_SETTING_KEY.values():
        # default per-type ON except swap_high / load_high
        defaults[k] = k not in {"ALERT_TYPE_SWAP_HIGH", "ALERT_TYPE_LOAD_HIGH"}
    out: dict[str, object] = {}
    for k in _ALERT_SETTING_KEYS:
        out[k] = await store.get(db, k, defaults.get(k))
    return out


async def _resolve_admin_emails(db: AsyncSession, admin_ids_csv: str) -> list[tuple[int, str]]:
    """Resolve comma-separated admin user IDs to (id, email) pairs."""
    ids = [int(x) for x in str(admin_ids_csv).split(",") if x.strip().isdigit()]
    if not ids:
        return []
    from app.db.models.pterodactyl import PteroUser
    result = await db.execute(
        select(PteroUser.id, PteroUser.email).where(
            PteroUser.id.in_(ids), PteroUser.root_admin.is_(True),
        )
    )
    return [(rid, email) for rid, email in result.all() if email]


def _type_enabled(settings: dict[str, object], alert_type: str) -> bool:
    key = _TYPE_TO_SETTING_KEY.get(alert_type)
    if not key:
        return True
    return _to_bool(settings.get(key, True))


def _severity_passes(settings: dict[str, object], severity: str) -> bool:
    min_rank = _SEVERITY_RANK.get(str(settings.get("ALERT_MIN_SEVERITY", "warning")), 1)
    cur_rank = _SEVERITY_RANK.get(severity, 1)
    return cur_rank >= min_rank


async def _maybe_notify(
    db: AsyncSession,
    settings: dict[str, object],
    *,
    node_name: str,
    node_id: int | None,
    alert_obj: NodeAlert,
    kind: str,  # 'fired' | 'resolved'
    now: datetime,
) -> None:
    """Apply gating (channel enabled / type / severity / cooldown) then send."""
    if not _to_bool(settings.get("ALERT_EMAIL_ENABLED", False)):
        return
    if kind == "resolved" and not _to_bool(settings.get("ALERT_NOTIFY_RESOLVE", False)):
        return
    if not _type_enabled(settings, alert_obj.alert_type):
        return
    if not _severity_passes(settings, alert_obj.severity):
        return

    # Cooldown: only relevant for 'fired'. Resolves bypass to avoid getting stuck.
    if kind == "fired":
        cooldown_min = int(settings.get("ALERT_COOLDOWN_MIN", 30) or 30)
        last_at = alert_obj.last_notified_at
        if last_at and (now - last_at) < timedelta(minutes=cooldown_min):
            return

    recipients = await _resolve_admin_emails(
        db, str(settings.get("ALERT_EMAIL_ADMIN_IDS", "")),
    )
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
    node_id: int,
    metrics: NodeMetrics,
    *,
    settings: dict[str, object],
    node_name: str,
) -> None:
    cpu_threshold = float(settings.get("ALERT_CPU_THRESHOLD", 90) or 90)
    cpu_sustain = int(settings.get("ALERT_CPU_SUSTAIN_MIN", 5) or 5)
    mem_threshold = float(settings.get("ALERT_MEM_THRESHOLD", 90) or 90)
    mem_sustain = int(settings.get("ALERT_MEM_SUSTAIN_MIN", 5) or 5)
    swap_threshold = float(settings.get("ALERT_SWAP_THRESHOLD", 50) or 50)
    disk_warn = float(settings.get("ALERT_DISK_WARNING", 85) or 85)
    disk_crit = float(settings.get("ALERT_DISK_CRITICAL", 95) or 95)
    load_factor = float(settings.get("ALERT_LOAD_FACTOR", 1.5) or 1.5)
    load_sustain = int(settings.get("ALERT_LOAD_SUSTAIN_MIN", 5) or 5)

    now = utc_naive_now()

    # --- reachability: 3 mutually-exclusive states ---
    if not metrics.agent_online and not metrics.wings_online:
        await _raise_or_skip(db, node_id, "node_offline", "critical",
                             f"Node {node_id} unreachable (agent + wings down)",
                             now, settings=settings, node_name=node_name)
        await _auto_resolve(db, node_id, "agent_only_down", now,
                            settings=settings, node_name=node_name)
        await _auto_resolve(db, node_id, "wings_only_down", now,
                            settings=settings, node_name=node_name)
    elif not metrics.agent_online:
        await _raise_or_skip(db, node_id, "agent_only_down", "warning",
                             f"Node {node_id} agent unreachable (wings still online)",
                             now, settings=settings, node_name=node_name)
        await _auto_resolve(db, node_id, "node_offline", now,
                            settings=settings, node_name=node_name)
        await _auto_resolve(db, node_id, "wings_only_down", now,
                            settings=settings, node_name=node_name)
    elif not metrics.wings_online:
        await _raise_or_skip(db, node_id, "wings_only_down", "critical",
                             f"Node {node_id} wings unreachable (agent still online)",
                             now, settings=settings, node_name=node_name)
        await _auto_resolve(db, node_id, "node_offline", now,
                            settings=settings, node_name=node_name)
        await _auto_resolve(db, node_id, "agent_only_down", now,
                            settings=settings, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "node_offline", now,
                            settings=settings, node_name=node_name)
        await _auto_resolve(db, node_id, "agent_only_down", now,
                            settings=settings, node_name=node_name)
        await _auto_resolve(db, node_id, "wings_only_down", now,
                            settings=settings, node_name=node_name)

    # --- CPU ---
    if metrics.cpu_pct is not None and metrics.cpu_pct > cpu_threshold:
        if await _check_sustained_above(db, node_id, "cpu_pct", cpu_threshold, minutes=cpu_sustain):
            await _raise_or_skip(db, node_id, "cpu_high", "warning",
                                 f"CPU {metrics.cpu_pct}% > {cpu_threshold}% sustained",
                                 now, settings=settings, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "cpu_high", now,
                            settings=settings, node_name=node_name)

    # --- Memory ---
    if metrics.mem_pct is not None and metrics.mem_pct > mem_threshold:
        if await _check_sustained_above(db, node_id, "mem_pct", mem_threshold, minutes=mem_sustain):
            await _raise_or_skip(db, node_id, "mem_high", "warning",
                                 f"Memory {metrics.mem_pct}% > {mem_threshold}% sustained",
                                 now, settings=settings, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "mem_high", now,
                            settings=settings, node_name=node_name)

    # --- Swap ---
    swap_pct: float | None = None
    if metrics.swap_total_mb and metrics.swap_total_mb > 0 and metrics.swap_used_mb is not None:
        swap_pct = round(metrics.swap_used_mb * 100.0 / metrics.swap_total_mb, 1)
    if swap_pct is not None and swap_pct > swap_threshold:
        await _raise_or_skip(db, node_id, "swap_high", "warning",
                             f"Swap {swap_pct}% > {swap_threshold}%",
                             now, settings=settings, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "swap_high", now,
                            settings=settings, node_name=node_name)

    # --- Load ---
    load_limit: float | None = None
    if metrics.cpu_cores and metrics.cpu_cores > 0:
        load_limit = metrics.cpu_cores * load_factor
    if (metrics.load_1m is not None and load_limit is not None
            and metrics.load_1m > load_limit):
        if await _check_sustained_above(db, node_id, "load_1m", load_limit, minutes=load_sustain):
            await _raise_or_skip(db, node_id, "load_high", "warning",
                                 f"Load {metrics.load_1m} > {load_limit:.2f} ({metrics.cpu_cores} cores × {load_factor})",
                                 now, settings=settings, node_name=node_name)
    else:
        await _auto_resolve(db, node_id, "load_high", now,
                            settings=settings, node_name=node_name)

    # --- Disk ---
    if metrics.disk_pct is not None:
        if metrics.disk_pct > disk_crit:
            await _raise_or_skip(db, node_id, "disk_critical", "critical",
                                 f"Disk {metrics.disk_pct}% > {disk_crit}%",
                                 now, settings=settings, node_name=node_name)
        elif metrics.disk_pct > disk_warn:
            await _raise_or_skip(db, node_id, "disk_high", "warning",
                                 f"Disk {metrics.disk_pct}% > {disk_warn}%",
                                 now, settings=settings, node_name=node_name)
            await _auto_resolve(db, node_id, "disk_critical", now,
                                settings=settings, node_name=node_name)
        else:
            await _auto_resolve(db, node_id, "disk_high", now,
                                settings=settings, node_name=node_name)
            await _auto_resolve(db, node_id, "disk_critical", now,
                                settings=settings, node_name=node_name)


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
    settings: dict[str, object] | None = None,
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
        # Already raised; the cooldown gate inside _maybe_notify decides
        # whether to (re-)send a fired email at this cycle.
        if settings is not None:
            await _maybe_notify(
                db, settings,
                node_name=node_name, node_id=node_id,
                alert_obj=open_row, kind="fired", now=now,
            )
        return

    alert = NodeAlert(
        node_id=node_id, alert_type=alert_type, severity=severity,
        message=message, created_at=now,
    )
    db.add(alert)
    # Ensure we have an in-session row to flip notified/last_notified_at on.
    await db.flush()

    if settings is not None:
        await _maybe_notify(
            db, settings,
            node_name=node_name, node_id=node_id,
            alert_obj=alert, kind="fired", now=now,
        )


async def _auto_resolve(
    db: AsyncSession, node_id: int | None, alert_type: str, now: datetime,
    *,
    settings: dict[str, object] | None = None,
    node_name: str = "",
) -> None:
    # Find currently-open alerts of (node_id, alert_type) so we can notify on resolve.
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

    if settings is not None and _to_bool(settings.get("ALERT_NOTIFY_RESOLVE", False)):
        # Send only for alerts that were previously notified (received fired email).
        for row in open_rows:
            if row.notified:
                await _maybe_notify(
                    db, settings,
                    node_name=node_name, node_id=node_id,
                    alert_obj=row, kind="resolved", now=now,
                )


async def _check_probe_alerts(
    db: AsyncSession,
    *,
    settings: dict[str, object] | None = None,
    node_names: dict[int, str] | None = None,
) -> None:
    """Per-node probe alerting.

    ``ProbeResult`` rows carry two orthogonal identifiers:

    * ``source`` — ``"manager"`` for the public-side Wings probe the Manager
      runs itself, or ``"agent:<node_id>"`` for probes reported by a node
      agent (clash_proxy, upstream_db, ...).
    * ``probe_name`` — either the user-defined label from agent config, or
      ``wings_pub_<node_id>`` for the Manager-side probe.

    We look at the *latest* row for each ``(source, probe_name)`` pair and
    raise / auto-resolve one alert **per node**. Previously a ``LIKE
    'wings_pub%'`` LIMIT 1 collapsed every node's status into a single
    alert row with ``node_id=NULL``, which made multi-node outages
    indistinguishable (CR §2.7).
    """
    node_names = node_names or {}
    now = utc_naive_now()
    probe_alert_map = {
        "clash_proxy": ("clash_down", "warning"),
        "wings_pub": ("network_down", "critical"),
    }

    # Only look at probes from the recent collection window; anything older
    # is stale (agent offline, retention cleanup, etc.) and should not drive
    # a fresh alert decision.
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
        # Match probe_name against the alert-type prefix table.
        matched: tuple[str, str] | None = None
        for prefix, spec in probe_alert_map.items():
            if probe.probe_name.startswith(prefix):
                matched = spec
                break
        if matched is None:
            continue
        alert_type, severity = matched

        # Derive node_id: "agent:<id>" source wins; else parse from
        # wings_pub_<id>. Anything that can't be resolved stays None.
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

        if not probe.ok:
            await _raise_or_skip(
                db, node_id, alert_type, severity,
                f"Probe {probe.probe_name} failed", now,
                settings=settings, node_name=node_name,
            )
        else:
            await _auto_resolve(
                db, node_id, alert_type, now,
                settings=settings, node_name=node_name,
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
        store = get_settings_store()
        if str(await store.get(db, "MONITOR_ENABLED", "false")).lower() not in ("true", "1", "yes"):
            return

        monitored_ids = [
            int(x.strip())
            for x in str(await store.get(db, "MONITOR_NODE_IDS", "")).split(",")
            if x.strip().isdigit()
        ]
        if not monitored_ids:
            return

        now = utc_naive_now()

        from app.db.models.pterodactyl import PanelNode
        from app.db.models.manager import NodeMeta
        result = await db.execute(select(PanelNode).where(PanelNode.id.in_(monitored_ids)))
        nodes = {n.id: n for n in result.scalars().all()}

        # Pre-load alert settings once per cycle to avoid hammering the store.
        alert_settings = await _load_alert_settings(db)

        # Pre-load all NodeMeta to avoid concurrent session use during gather
        meta_result = await db.execute(select(NodeMeta).where(NodeMeta.node_id.in_(monitored_ids)))
        meta_map: dict[int, tuple[str, str]] = {}
        from app.core.config import get_settings as _get_settings
        from app.core.security import decrypt_value as _dec
        from app.services.agent_endpoint import (
            AgentEndpointError,
            validate_agent_endpoint,
        )
        for meta in meta_result.scalars().all():
            if not meta.agent_endpoint or not meta.agent_token_encrypted:
                continue
            # Defence-in-depth: re-validate the endpoint at read time so a
            # historically-stored bad value (e.g. inserted before the SSRF
            # guard was added) cannot be used.
            try:
                endpoint = validate_agent_endpoint(meta.agent_endpoint)
            except AgentEndpointError as exc:
                logger.warning(
                    "agent endpoint rejected for node %d: %s", meta.node_id, exc,
                )
                continue
            try:
                tok = _dec(meta.agent_token_encrypted, _get_settings().settings_encryption_key)
            except ValueError:
                logger.warning("agent token decrypt failed for node %d", meta.node_id)
                continue
            meta_map[meta.node_id] = (endpoint, tok)

        async def _pull_direct(node_id: int) -> dict | None:
            ep_tok = meta_map.get(node_id)
            if not ep_tok:
                return None
            endpoint, token = ep_tok
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
            # Each _collect already bounded by the 10s httpx timeout inside
            # _pull_direct and _probe_wings_public. Using return_exceptions
            # makes one slow/crashing node a no-op for itself only, instead of
            # killing the whole cycle (see CR §2.5).
            raw_results = await asyncio.gather(
                *[_collect(nid) for nid in monitored_ids],
                return_exceptions=True,
            )
        except Exception:  # pragma: no cover — gather with return_exceptions shouldn't raise
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

            await _check_alerts(
                db, node_id, metrics_row,
                settings=alert_settings,
                node_name=nodes[node_id].name if node_id in nodes else f"node-{node_id}",
            )

        await _check_probe_alerts(
            db, settings=alert_settings,
            node_names={nid: n.name for nid, n in nodes.items()},
        )
        await _cleanup_old_data(db)


        await db.commit()
        logger.debug("agent-pull cycle committed for %d nodes", len(monitored_ids))
