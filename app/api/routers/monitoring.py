"""Monitoring routes — admin monitoring API (read-only views over pull cache)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.settings_store import get_settings_store
from app.db.models.manager import ManagerHost
from app.db.models.monitoring import NodeAlert, NodeMetrics, ProbeResult
from app.db.models.pterodactyl import PanelNode, PteroUser
from app.schemas.monitoring import (
    AlertItem,
    AlertListResponse,
    AlertSummary,
    MonitoringOverviewResponse,
    NodeHistoryResponse,
    NodeOverview,
    HistoryPoint,
    ProbeOverview,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["monitoring"])


# ---------------------------------------------------------------------------
# Admin monitoring API
# ---------------------------------------------------------------------------


async def _get_monitored_node_ids(db: AsyncSession) -> list[int]:
    """Return panel node ids of all enabled wings_node manager_hosts."""
    from app.services import host_registry
    result = await db.execute(
        select(ManagerHost.pterodactyl_node_id).where(
            ManagerHost.kind == host_registry.KIND_WINGS_NODE,
            ManagerHost.enabled.is_(True),
            ManagerHost.pterodactyl_node_id.isnot(None),
        )
    )
    return [int(nid) for (nid,) in result.all() if nid is not None]


@router.get("/monitoring/overview", response_model=MonitoringOverviewResponse)
async def monitoring_overview(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MonitoringOverviewResponse:
    """Get overview of all monitored nodes, probes, and alerts."""
    monitored_ids = await _get_monitored_node_ids(db)
    if not monitored_ids:
        return MonitoringOverviewResponse(
            nodes=[], probes=[], alerts=AlertSummary()
        )

    # Fetch node info from Panel
    result = await db.execute(
        select(PanelNode).where(PanelNode.id.in_(monitored_ids))
    )
    nodes_map = {n.id: n for n in result.scalars().all()}

    # Latest metrics per node (subquery for max ts per node)
    latest_sub = (
        select(
            NodeMetrics.node_id,
            func.max(NodeMetrics.id).label("max_id"),
        )
        .where(NodeMetrics.node_id.in_(monitored_ids))
        .group_by(NodeMetrics.node_id)
        .subquery()
    )
    result = await db.execute(
        select(NodeMetrics).join(
            latest_sub, NodeMetrics.id == latest_sub.c.max_id
        )
    )
    metrics_map = {m.node_id: m for m in result.scalars().all()}

    # Active alerts per node
    result = await db.execute(
        select(NodeAlert.node_id, func.count(NodeAlert.id).label("cnt"))
        .where(NodeAlert.node_id.in_(monitored_ids), NodeAlert.resolved_at.is_(None))
        .group_by(NodeAlert.node_id)
    )
    alert_counts = {row.node_id: row.cnt for row in result}

    nodes_out = []
    for nid in monitored_ids:
        node = nodes_map.get(nid)
        if not node:
            continue
        m = metrics_map.get(nid)
        nodes_out.append(NodeOverview(
            id=nid,
            name=node.name,
            fqdn=node.fqdn,
            agentOnline=m.agent_online if m else False,
            wingsOnline=m.wings_online if m else False,
            publicReachable=m.public_reachable if m else None,
            lastSeen=m.ts if m else None,
            wingsVersion=m.wings_version if m else None,
            cpuPct=m.cpu_pct if m else None,
            cpuCores=m.cpu_cores if m else None,
            loadAvg=[m.load_1m, m.load_5m, m.load_15m] if m and m.load_1m is not None else None,
            memUsedMb=m.mem_used_mb if m else None,
            memTotalMb=m.mem_total_mb if m else None,
            memPct=m.mem_pct if m else None,
            swapUsedMb=m.swap_used_mb if m else None,
            swapTotalMb=m.swap_total_mb if m else None,
            uptimeSec=m.uptime_sec if m else None,
            diskUsedMb=m.disk_used_mb if m else None,
            diskTotalMb=m.disk_total_mb if m else None,
            diskPct=m.disk_pct if m else None,
            netRxBps=m.net_rx_bps if m else None,
            netTxBps=m.net_tx_bps if m else None,
            containerTotal=m.container_total if m else None,
            containerRunning=m.container_running if m else None,
            containerMemMb=m.container_mem_mb if m else None,
            containerCpuPct=m.container_cpu_pct if m else None,
            containerDiskMb=m.container_disk_mb if m else None,
            activeAlerts=alert_counts.get(nid, 0),
        ))

    # Latest probes (distinct by source + probe_name, last 5 min)
    five_min_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    probe_sub = (
        select(
            ProbeResult.source,
            ProbeResult.probe_name,
            func.max(ProbeResult.id).label("max_id"),
        )
        .where(ProbeResult.ts >= five_min_ago)
        .group_by(ProbeResult.source, ProbeResult.probe_name)
        .subquery()
    )
    result = await db.execute(
        select(ProbeResult).join(probe_sub, ProbeResult.id == probe_sub.c.max_id)
    )
    probes_out = [
        ProbeOverview(
            name=p.probe_name,
            ok=p.ok,
            latencyMs=p.latency_ms,
            source=p.source,
            ts=p.ts,
        )
        for p in result.scalars().all()
    ]

    # Alert summary
    now = datetime.now(UTC).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    active_count_result = await db.execute(
        select(func.count(NodeAlert.id)).where(NodeAlert.resolved_at.is_(None))
    )
    active_count = active_count_result.scalar() or 0

    today_count_result = await db.execute(
        select(func.count(NodeAlert.id)).where(NodeAlert.created_at >= today_start)
    )
    today_count = today_count_result.scalar() or 0

    return MonitoringOverviewResponse(
        nodes=nodes_out,
        probes=probes_out,
        alerts=AlertSummary(active=active_count, todayTotal=today_count),
    )


@router.get("/monitoring/nodes/{node_id}/history", response_model=NodeHistoryResponse)
async def node_history(
    node_id: int,
    # Cap at 720 hours (30 days) to match MONITOR_RETENTION_DAYS default and
    # prevent a caller from requesting unbounded ranges that could OOM the
    # response path or hang the DB with a huge scan.
    hours: int = Query(24, ge=1, le=720),
    interval: str | None = None,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> NodeHistoryResponse:
    """Get historical metrics for a node."""
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    result = await db.execute(
        select(NodeMetrics)
        .where(NodeMetrics.node_id == node_id, NodeMetrics.ts >= since)
        .order_by(NodeMetrics.ts)
    )
    rows = result.scalars().all()

    # Determine interval label (from query param or auto-detect)
    if interval and interval in ("1m", "5m", "15m", "1h"):
        used_interval = interval
    elif hours <= 6:
        used_interval = "1m"
    elif hours <= 24:
        used_interval = "5m"
    else:
        used_interval = "15m"

    points = [
        HistoryPoint(
            ts=r.ts,
            cpuPct=r.cpu_pct,
            memPct=r.mem_pct,
            diskPct=r.disk_pct,
            loadAvg1m=r.load_1m,
            containerRunning=r.container_running,
            netRxBps=r.net_rx_bps,
            netTxBps=r.net_tx_bps,
        )
        for r in rows
    ]

    return NodeHistoryResponse(nodeId=node_id, interval=used_interval, points=points)


# ---------------------------------------------------------------------------
# PR-C history endpoint
# ---------------------------------------------------------------------------


_METRIC_TO_COLUMN = {
    "cpu": NodeMetrics.cpu_pct,
    "mem": NodeMetrics.mem_pct,
    "disk": NodeMetrics.disk_pct,
    "load": NodeMetrics.load_1m,
    "net_rx": NodeMetrics.net_rx_bps,
    "net_tx": NodeMetrics.net_tx_bps,
    "disk_read": NodeMetrics.disk_read_bps,
    "disk_write": NodeMetrics.disk_write_bps,
}


_WINDOW_TO_SECONDS: dict[str, int] = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
}


@router.get("/monitoring/history/{node_id}")
async def monitoring_history(
    node_id: int,
    metric: str = Query(...),
    window: str = Query("1h"),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Single-metric history for one node.

    Returns ``{series: [[ts_ms, value], ...]}`` — the payload shape
    vue-echarts consumes directly. ``metric`` must be one of
    ``cpu|mem|disk|load``; ``window`` one of ``1h|6h|24h|7d``.

    The target bucket count is 60 — we compute an interval from window
    size and downsample with GROUP BY + AVG so the response stays small
    regardless of the pull cycle resolution.
    """
    col = _METRIC_TO_COLUMN.get(metric)
    if col is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"metric must be one of {sorted(_METRIC_TO_COLUMN.keys())}",
        )
    seconds = _WINDOW_TO_SECONDS.get(window)
    if seconds is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"window must be one of {sorted(_WINDOW_TO_SECONDS.keys())}",
        )
    # Aim for ~60 evenly-spaced points; round interval up to the next
    # 10-second multiple so downsampled buckets stay aligned.
    bucket_seconds = max(10, (seconds // 60 // 10) * 10 or 10)

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=seconds)

    # Portable expression using FROM_UNIXTIME so MariaDB/MySQL returns
    # a proper bucket timestamp.
    bucket_ts = func.from_unixtime(
        func.floor(func.unix_timestamp(NodeMetrics.ts) / bucket_seconds) * bucket_seconds
    )

    stmt = (
        select(bucket_ts.label("bucket"), func.avg(col).label("value"))
        .where(NodeMetrics.node_id == node_id, NodeMetrics.ts >= since, col.isnot(None))
        .group_by("bucket")
        .order_by("bucket")
    )
    rows = (await db.execute(stmt)).all()

    series: list[list[float]] = []
    for bucket, value in rows:
        if bucket is None or value is None:
            continue
        # bucket arrives as naive datetime from MariaDB; treat as UTC.
        ts_ms = int(bucket.replace(tzinfo=UTC).timestamp() * 1000)
        series.append([ts_ms, round(float(value), 2)])

    return {
        "nodeId": node_id,
        "metric": metric,
        "window": window,
        "bucketSeconds": bucket_seconds,
        "series": series,
    }


# ---------------------------------------------------------------------------
# PR-C host snapshot endpoint
# ---------------------------------------------------------------------------


@router.get("/admin/hosts/{host_id}/snapshot")
async def admin_host_snapshot(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Latest metric + probe snapshot for a single host.

    Shape is tailored for the HostDetailPage overview tab's ECharts
    panel (see design doc §3.2). Non-wings hosts get a minimal
    payload — last_seen_at + inbound_reachable — since they have no
    NodeMetrics rows.
    """
    from app.services import host_registry

    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    base: dict[str, object] = {
        "hostId": host.id,
        "name": host.name,
        "kind": host.kind,
        "enabled": host.enabled,
        "inboundReachable": host.inbound_reachable,
        "lastSeenAt": host.last_seen_at.isoformat() if host.last_seen_at else None,
        "lastStatusAt": host.last_status_at.isoformat() if host.last_status_at else None,
    }

    node_id = host.pterodactyl_node_id
    if node_id is None:
        return base | {"metrics": None, "probes": []}

    metrics_row = (
        await db.execute(
            select(NodeMetrics)
            .where(NodeMetrics.node_id == node_id)
            .order_by(NodeMetrics.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    five_min_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    probe_sub = (
        select(
            ProbeResult.source,
            ProbeResult.probe_name,
            func.max(ProbeResult.id).label("max_id"),
        )
        .where(
            ProbeResult.ts >= five_min_ago,
            (ProbeResult.source == f"agent:{node_id}")
            | (ProbeResult.probe_name == f"wings_pub_{node_id}"),
        )
        .group_by(ProbeResult.source, ProbeResult.probe_name)
        .subquery()
    )
    probe_rows = (
        await db.execute(
            select(ProbeResult).join(probe_sub, ProbeResult.id == probe_sub.c.max_id)
        )
    ).scalars().all()

    metrics_out: dict[str, object] | None = None
    if metrics_row is not None:
        metrics_out = {
            "ts": metrics_row.ts.isoformat(),
            "agentOnline": metrics_row.agent_online,
            "wingsOnline": metrics_row.wings_online,
            "publicReachable": metrics_row.public_reachable,
            "cpuPct": metrics_row.cpu_pct,
            "cpuCores": metrics_row.cpu_cores,
            "memUsedMb": metrics_row.mem_used_mb,
            "memTotalMb": metrics_row.mem_total_mb,
            "memPct": metrics_row.mem_pct,
            "swapUsedMb": metrics_row.swap_used_mb,
            "swapTotalMb": metrics_row.swap_total_mb,
            "diskUsedMb": metrics_row.disk_used_mb,
            "diskTotalMb": metrics_row.disk_total_mb,
            "diskPct": metrics_row.disk_pct,
            "load1m": metrics_row.load_1m,
            "load5m": metrics_row.load_5m,
            "load15m": metrics_row.load_15m,
            "uptimeSec": metrics_row.uptime_sec,
            "netRxBps": metrics_row.net_rx_bps,
            "netTxBps": metrics_row.net_tx_bps,
            "containerTotal": metrics_row.container_total,
            "containerRunning": metrics_row.container_running,
            "containerMemMb": metrics_row.container_mem_mb,
            "containerCpuPct": metrics_row.container_cpu_pct,
            "containerDiskMb": metrics_row.container_disk_mb,
            "wingsVersion": metrics_row.wings_version,
        }

    probes_out = [
        {
            "name": p.probe_name,
            "source": p.source,
            "ok": p.ok,
            "latencyMs": p.latency_ms,
            "errorMsg": p.error_msg,
            "ts": p.ts.isoformat(),
        }
        for p in probe_rows
    ]

    return base | {
        "nodeId": node_id,
        "metrics": metrics_out,
        "probes": probes_out,
    }


@router.get("/monitoring/alerts", response_model=AlertListResponse)
async def list_alerts(
    active_only: bool = False,
    limit: int = 50,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AlertListResponse:
    """List alerts (newest first)."""
    query = select(NodeAlert).order_by(NodeAlert.created_at.desc()).limit(limit)
    if active_only:
        query = query.where(NodeAlert.resolved_at.is_(None))
    result = await db.execute(query)
    alerts = result.scalars().all()

    count_q = select(func.count(NodeAlert.id))
    if active_only:
        count_q = count_q.where(NodeAlert.resolved_at.is_(None))
    total = (await db.execute(count_q)).scalar() or 0

    return AlertListResponse(
        items=[
            AlertItem(
                id=a.id,
                nodeId=a.node_id,
                alertType=a.alert_type,
                severity=a.severity,
                message=a.message,
                createdAt=a.created_at,
                resolvedAt=a.resolved_at,
                notified=a.notified,
            )
            for a in alerts
        ],
        total=total,
    )


@router.post("/monitoring/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Manually resolve an alert."""
    result = await db.execute(select(NodeAlert).where(NodeAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.resolved_at:
        return {"status": "already_resolved"}
    alert.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    return {"status": "resolved"}
