"""Schema models for version and dashboard routes."""

from __future__ import annotations

from pydantic import BaseModel


class VersionResponse(BaseModel):
    version: str
    brandName: str
    systemName: str
    bannerUrl: str
    icpRecord: str
    timezone: str


class StatusDistribution(BaseModel):
    normal: int
    expiring_soon: int
    expired: int
    suspended: int
    permanent: int


class ExpiringServer(BaseModel):
    id: int
    name: str
    ownerUsername: str | None
    ownerEmail: str | None = None
    nodeName: str | None = None
    expiresAt: str | None = None  # ISO date YYYY-MM-DD
    daysLeft: int
    isSuspended: bool


class CertSummary(BaseModel):
    total: int
    expiringSoon: int  # within each cert's own alert_threshold_days
    expired: int


class DashboardResponse(BaseModel):
    totalUsers: int
    totalServers: int
    normalCount: int
    statusDistribution: StatusDistribution
    expiringServers: list[ExpiringServer]
    certSummary: CertSummary
