"""Audit logging helpers for the FastAPI backend."""

from __future__ import annotations

import logging
import json
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.manager import ManagerActivityLog

logger = logging.getLogger(__name__)


_ACTION_MAP = {
    "auth": "auth",
    "server": "server",
    "user": "user",
    "account": "account",
    "settings": "settings",
    "automation": "automation",
    "email": "email",
    "allocation.create": "allocation.create",
    "allocation.delete": "allocation.delete",
    "allocation.delete_bulk": "allocation.delete_bulk",
    "create_host": "host",
    "delete_host": "host",
    "patch_host": "host",
    "probe_host": "host",
    "host_alerts_update": "host",
    "update_node_wings_config": "node",
    "reset_node_daemon_token": "node",
    "rotate_agent_token": "node",
    "restart_wings": "node",
    "cert_create": "certificate",
    "cert_patch": "certificate",
    "cert_delete": "certificate",
    "cert_deploy": "certificate",
    "cert_deployment_create": "certificate",
    "cert_deployment_delete": "certificate",
    "cert_acme_register": "certificate",
    "cert_renew_force": "certificate",
    "cert_source_changed": "certificate",
    "cert_settings": "settings",
    "global_defaults_update": "settings",
}

_CATEGORY_MAP = {
    "auth": "auth",
    "server": "server",
    "user": "user",
    "account": "user",
    "settings": "settings",
    "automation": "automation",
    "email": "email",
    "allocation.create": "server",
    "allocation.delete": "server",
    "allocation.delete_bulk": "server",
    "host": "host_node",
    "node": "host_node",
    "certificate": "certificate",
    "other": "other",
}

_STATUS_MAP = {
    "success": "success",
    "failure": "failed",
    "fail": "failed",
    "error": "failed",
    "failed": "failed",
    "partial": "partial",
    "info": "info",
}


def _normalize_action(action: str) -> str:
    return _ACTION_MAP.get(action, "other")


def _normalize_status(status: str) -> str:
    return _STATUS_MAP.get(status, "info")


def _normalize_category(category: str | None, action: str) -> str:
    if category:
        c = category.strip().lower()
        if c in {
            "auth", "server", "user", "host_node", "automation", "settings", "certificate", "email", "other",
        }:
            return c
    return _CATEGORY_MAP.get(action, "other")


async def log_manager_activity(
    db: AsyncSession,
    *,
    actor: str,
    category: str | None = None,
    action: str,
    status: str,
    detail_key: str,
    detail_params: Mapping[str, Any] | None = None,
) -> None:
    try:
        action_normalized = _normalize_action(action)
        status_normalized = _normalize_status(status)
        category_normalized = _normalize_category(category, action_normalized)
        db.add(
            ManagerActivityLog(
                actor=actor[:100],
                category=category_normalized[:32],
                action=action_normalized[:100],
                status=status_normalized[:50],
                detail_key=detail_key[:120],
                detail_params=json.dumps(dict(detail_params or {}), ensure_ascii=False, default=str),
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to write manager activity log")
