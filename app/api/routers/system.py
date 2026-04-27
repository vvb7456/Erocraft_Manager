"""Public and admin system routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.config import get_settings
from app.core.settings_store import get_settings_store
from app.core.time import local_today
from app.db.models.manager import ManagerCertificate
from app.db.models.pterodactyl import PteroUser
from app.db.repositories.servers import server_repository
from app.db.repositories.users import user_repository
from app.schemas.dashboard import (
    CertSummary,
    DashboardResponse,
    ExpiringServer,
    StatusDistribution,
    VersionResponse,
)

router = APIRouter(tags=["system"])


@router.get("/version", response_model=VersionResponse)
async def version(
    db: AsyncSession = Depends(get_db),
) -> VersionResponse:
    app_settings = get_settings()
    settings_store = get_settings_store()
    brand_name = await settings_store.get(db, "BRAND_NAME", app_settings.app_name)
    system_name = await settings_store.get(
        db,
        "UI_SYSTEM_NAME",
        "",
    )
    banner_url = await settings_store.get(db, "UI_BANNER_URL", "")
    icp_record = await settings_store.get(db, "UI_ICP_RECORD", "")
    timezone_name = await settings_store.get(db, "TIMEZONE", app_settings.default_timezone)
    return VersionResponse(
        version=app_settings.app_version,
        brandName=str(brand_name),
        systemName=str(system_name),
        bannerUrl=str(banner_url),
        icpRecord=str(icp_record),
        timezone=str(timezone_name),
    )


@router.get("/admin/dashboard", response_model=DashboardResponse)
async def dashboard(
    _: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    app_settings = get_settings()
    settings_store = get_settings_store()
    timezone_name = await settings_store.get(db, "TIMEZONE", app_settings.default_timezone)
    today = local_today(str(timezone_name))

    total_users = await user_repository.count(db)
    all_servers = await server_repository.list_all_for_dashboard(db)

    counts = {"normal": 0, "expiring_soon": 0, "expired": 0, "suspended": 0, "permanent": 0}
    for server in all_servers:
        if server.is_suspended:
            counts["suspended"] += 1

        expiration_date = server.expiration_date
        if expiration_date is None:
            counts["permanent"] += 1
            continue

        days_left = (expiration_date - today).days
        if days_left < 0:
            counts["expired"] += 1
        elif days_left <= 7:
            counts["expiring_soon"] += 1
        else:
            counts["normal"] += 1

    return DashboardResponse(
        totalUsers=total_users,
        totalServers=len(all_servers),
        normalCount=counts["normal"] + counts["expiring_soon"] + counts["permanent"],
        statusDistribution=StatusDistribution(**counts),
        expiringServers=_collect_expiring_servers(all_servers, today),
        certSummary=await _collect_cert_summary(db),
    )


def _collect_expiring_servers(
    servers, today
) -> list[ExpiringServer]:
    """Top non-suspended, non-permanent servers expiring within 7 days.

    Sorted by daysLeft ascending (most urgent first); already-expired (negative
    days) included so admins see them at the top. Capped at 12 entries.
    """
    rows: list[tuple[int, ExpiringServer]] = []
    for server in servers:
        if server.is_suspended:
            continue
        expiration = server.expiration_date
        if expiration is None:
            continue
        days_left = (expiration - today).days
        if days_left > 7:
            continue
        owner_username = server.owner.username if server.owner else None
        owner_email = server.owner.email if server.owner else None
        node_name = server.node.name if server.node else None
        rows.append(
            (
                days_left,
                ExpiringServer(
                    id=server.id,
                    name=server.name,
                    ownerUsername=owner_username,
                    ownerEmail=owner_email,
                    nodeName=node_name,
                    expiresAt=expiration.isoformat() if expiration else None,
                    daysLeft=days_left,
                    isSuspended=False,
                ),
            )
        )
    rows.sort(key=lambda x: x[0])
    return [r[1] for r in rows[:12]]


async def _collect_cert_summary(db: AsyncSession) -> CertSummary:
    """Aggregate manager_certificates: total enabled / expiring soon / expired.

    Each cert's own ``alert_threshold_days`` controls its "soon" boundary.
    """
    result = await db.execute(
        select(ManagerCertificate).where(ManagerCertificate.enabled.is_(True))
    )
    certs = list(result.scalars().all())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    total = len(certs)
    expiring_soon = 0
    expired = 0
    for cert in certs:
        if cert.source_not_after is None:
            continue
        delta = (cert.source_not_after - now).total_seconds() / 86400.0
        if delta < 0:
            expired += 1
        elif delta <= cert.alert_threshold_days:
            expiring_soon += 1
    return CertSummary(total=total, expiringSoon=expiring_soon, expired=expired)
