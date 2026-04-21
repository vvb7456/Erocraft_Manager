"""Monitoring routes — admin monitoring API (read-only views over pull cache)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.settings_store import get_settings_store
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
    store = get_settings_store()
    raw = await store.get(db, "MONITOR_NODE_IDS", "")
    if not raw:
        return []
    return [int(x.strip()) for x in str(raw).split(",") if x.strip().isdigit()]


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
