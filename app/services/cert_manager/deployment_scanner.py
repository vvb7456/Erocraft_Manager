"""Scan certificate deployment state on agent-managed hosts."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.manager import ManagerCertDeployment, ManagerCertificate
from app.services import agent_client, host_registry

logger = logging.getLogger(__name__)


def _parse_agent_not_after(current_cert: dict[str, Any] | None) -> datetime | None:
    if not current_cert:
        return None
    value = current_cert.get("not_after")
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
    return None


async def scan_deployment(
    db: AsyncSession,
    deployment: ManagerCertDeployment,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """Ask the target agent which certificate is currently installed."""
    cert = await db.get(ManagerCertificate, deployment.certificate_id)
    if cert is None:
        deployment.status = "unknown"
        deployment.last_check_at = utc_naive_now()
        deployment.last_check_error = "certificate row not found"
        if commit:
            await db.commit()
        return {"ok": False, "deployment_id": deployment.id, "status": deployment.status}

    now = utc_naive_now()
    deployment.last_check_at = now
    try:
        endpoint, token = await host_registry.get_credentials(db, deployment.host_id)
        payload = await agent_client.get_cert_status(endpoint, token, timeout=10.0)
    except host_registry.HostRegistryError as exc:
        deployment.status = "unreachable"
        deployment.last_check_error = str(exc)
        if commit:
            await db.commit()
        return {
            "ok": False,
            "deployment_id": deployment.id,
            "status": deployment.status,
            "error": str(exc),
        }
    except agent_client.AgentClientError as exc:
        deployment.status = "unreachable"
        deployment.last_check_error = str(exc)
        if commit:
            await db.commit()
        return {
            "ok": False,
            "deployment_id": deployment.id,
            "status": deployment.status,
            "error": str(exc),
        }

    if deployment.target_name:
        targets = payload.get("targets") or []
        target_status = next(
            (
                item for item in targets
                if isinstance(item, dict) and item.get("name") == deployment.target_name
            ),
            None,
        )
        if target_status is None:
            deployment.status = "unknown"
            deployment.last_check_error = f"agent target not found: {deployment.target_name}"
            if commit:
                await db.commit()
            return {
                "ok": False,
                "deployment_id": deployment.id,
                "status": deployment.status,
                "error": deployment.last_check_error,
            }
        current_cert = target_status.get("current_cert")
        agent_error = target_status.get("error")
    else:
        current_cert = payload.get("current_cert")
        agent_error = payload.get("error")

    if not current_cert:
        deployment.deployed_fingerprint_sha256 = None
        deployment.deployed_not_after = None
        deployment.status = "unknown"
        deployment.last_check_error = agent_error or "agent reported no current cert"
    else:
        deployed_fp = current_cert.get("fingerprint_sha256")
        deployment.deployed_fingerprint_sha256 = deployed_fp
        deployment.deployed_not_after = _parse_agent_not_after(current_cert)
        if cert.source_fingerprint_sha256 and deployed_fp == cert.source_fingerprint_sha256:
            deployment.status = "synced"
            deployment.last_check_error = None
        else:
            deployment.status = "outdated"
            deployment.last_check_error = None

    if commit:
        await db.commit()
    return {
        "ok": deployment.status in {"synced", "outdated"},
        "deployment_id": deployment.id,
        "certificate_id": deployment.certificate_id,
        "host_id": deployment.host_id,
        "status": deployment.status,
        "deployed_fingerprint_sha256": deployment.deployed_fingerprint_sha256,
        "source_fingerprint_sha256": cert.source_fingerprint_sha256,
    }


async def scan_all_deployments(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(ManagerCertDeployment.id).order_by(ManagerCertDeployment.id)
    )
    deployment_ids = [row[0] for row in result.all()]
    out: list[dict[str, Any]] = []
    for dep_id in deployment_ids:
        try:
            deployment = await db.get(ManagerCertDeployment, dep_id)
            if deployment is None:
                continue
            out.append(await scan_deployment(db, deployment))
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.warning("cert deployment scan crashed deployment_id=%s: %s", dep_id, exc)
            out.append({
                "ok": False,
                "deployment_id": dep_id,
                "status": "unreachable",
                "error": str(exc),
            })
    return out
