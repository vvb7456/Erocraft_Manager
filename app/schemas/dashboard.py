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


class DashboardResponse(BaseModel):
    totalUsers: int
    totalServers: int
    normalCount: int
    statusDistribution: StatusDistribution
