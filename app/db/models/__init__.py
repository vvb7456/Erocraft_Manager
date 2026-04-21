"""Typed ORM models for the FastAPI backend."""

from app.db.models.manager import (
    ManagerActivityLog,
    ManagerEmailChange,
    ManagerEmailTemplate,
    ManagerPasswordReset,
    ServerMeta,
    SystemSetting,
)
from app.db.models.monitoring import NodeAlert, NodeMetrics, ProbeResult
from app.db.models.pterodactyl import (
    ActivityLog,
    ActivityLogSubject,
    Allocation,
    Egg,
    EggVariable,
    Nest,
    PanelNode,
    PteroServer,
    PteroUser,
    ServerVariable,
)

__all__ = [
    "ActivityLog",
    "ActivityLogSubject",
    "Allocation",
    "Egg",
    "EggVariable",
    "ManagerActivityLog",
    "ManagerEmailChange",
    "ManagerEmailTemplate",
    "ManagerPasswordReset",
    "Nest",
    "PanelNode",
    "PteroServer",
    "PteroUser",
    "ServerVariable",
    "ServerMeta",
    "SystemSetting",
]
