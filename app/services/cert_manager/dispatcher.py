"""Dispatch certificate PEM material to agent-managed deployments."""

from __future__ import annotations

import logging
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_naive_now
from app.db.models.manager import ManagerCertDeployment, ManagerCertificate, ManagerHost
from app.services import agent_client, host_registry
from app.services.audit import log_manager_activity

from .pem import CertPemError, load_source_material

logger = logging.getLogger(__name__)

_DEFAULT_CERT_COMMAND_TIMEOUT = 30.0
_DSM_CERT_COMMAND_TIMEOUT = 300.0


async def redeploy_deployment(
    db: AsyncSession,
    deployment: ManagerCertDeployment,
    *,
    actor: str = "system",
    commit: bool = True,
) -> dict[str, Any]:
    """Install the deployment's certificate source on its target host."""
    cert = await db.get(ManagerCertificate, deployment.certificate_id)
    if cert is None:
        deployment.status = "deploy_failed"
        deployment.last_deploy_attempt_at = utc_naive_now()
        deployment.last_deploy_error = "certificate row not found"
        if commit:
            await db.commit()
        return {"ok": False, "deployment_id": deployment.id, "error": deployment.last_deploy_error}

    now = utc_naive_now()
    deployment.last_deploy_attempt_at = now

    try:
        host = await db.get(ManagerHost, deployment.host_id)
        command_timeout = (
            _DSM_CERT_COMMAND_TIMEOUT
            if host is not None and host.kind == host_registry.KIND_SYNOLOGY_DSM
            else _DEFAULT_CERT_COMMAND_TIMEOUT
        )
        request_timeout = max(90.0, command_timeout + 30.0)

        material = load_source_material(cert.source_path)
        endpoint, token = await host_registry.get_credentials(db, deployment.host_id)
    except (CertPemError, host_registry.HostRegistryError) as exc:
        deployment.status = "deploy_failed"
        deployment.last_deploy_error = str(exc)
        if commit:
            await db.commit()
        await log_manager_activity(
            db,
            actor=actor,
            action="cert_deploy",
            status="error",
            detail_key="cert.deploy.failed",
            detail_params={
                "certificate_id": cert.id,
                "deployment_id": deployment.id,
                "host_id": deployment.host_id,
                "error": str(exc),
            },
        )
        return {"ok": False, "deployment_id": deployment.id, "error": str(exc)}

    try:
        result = await agent_client.install_cert(
            endpoint,
            token,
            cert_id=cert.id,
            fullchain_pem=material.fullchain_pem,
            privkey_pem=material.privkey_pem,
            target_name=deployment.target_name,
            command_timeout=command_timeout,
            timeout=request_timeout,
        )
    except Exception as exc:
        deployment.status = "deploy_failed"
        deployment.last_deploy_error = str(exc)
        if commit:
            await db.commit()
        await log_manager_activity(
            db,
            actor=actor,
            action="cert_deploy",
            status="error",
            detail_key="cert.deploy.failed",
            detail_params={
                "certificate_id": cert.id,
                "deployment_id": deployment.id,
                "host_id": deployment.host_id,
                "error": str(exc),
            },
        )
        return {"ok": False, "deployment_id": deployment.id, "error": str(exc)}

    if not result.get("ok"):
        deployment.status = "deploy_failed"
        deployment.last_deploy_error = result.get("error") or "agent reported cert.install failure"
        if commit:
            await db.commit()
        await log_manager_activity(
            db,
            actor=actor,
            action="cert_deploy",
            status="error",
            detail_key="cert.deploy.failed",
            detail_params={
                "certificate_id": cert.id,
                "deployment_id": deployment.id,
                "host_id": deployment.host_id,
                "agent_error": deployment.last_deploy_error,
            },
        )
        return {
            "ok": False,
            "deployment_id": deployment.id,
            "error": deployment.last_deploy_error,
            "agent_response": result,
        }

    output = result.get("output") or {}
    deployment.deployed_fingerprint_sha256 = (
        output.get("fingerprint_sha256") or material.parsed.fingerprint_sha256
    )
    deployment.deployed_not_after = material.parsed.not_after
    deployment.last_deploy_at = now
    deployment.last_deploy_error = None
    deployment.status = "synced"

    # Keep source metadata fresh when a deployment successfully used it.
    cert.source_fingerprint_sha256 = material.parsed.fingerprint_sha256
    cert.source_not_before = material.parsed.not_before
    cert.source_not_after = material.parsed.not_after
    cert.source_last_seen_at = now
    cert.source_last_error = None

    if commit:
        await db.commit()
    await log_manager_activity(
        db,
        actor=actor,
        action="cert_deploy",
        status="success",
        detail_key="cert.deploy.success",
        detail_params={
            "certificate_id": cert.id,
            "deployment_id": deployment.id,
            "host_id": deployment.host_id,
            "fingerprint_sha256": deployment.deployed_fingerprint_sha256,
        },
    )
    return {
        "ok": True,
        "deployment_id": deployment.id,
        "certificate_id": cert.id,
        "host_id": deployment.host_id,
        "status": deployment.status,
        "fingerprint_sha256": deployment.deployed_fingerprint_sha256,
        "agent_response": result,
    }


async def dispatch_certificate(
    db: AsyncSession,
    cert: ManagerCertificate,
    *,
    actor: str = "system",
    statuses: Iterable[str] = ("outdated", "unknown", "deploy_failed"),
) -> list[dict[str, Any]]:
    status_set = set(statuses)
    stmt = (
        select(ManagerCertDeployment)
        .where(ManagerCertDeployment.certificate_id == cert.id)
        .order_by(ManagerCertDeployment.id)
    )
    if status_set:
        stmt = stmt.where(ManagerCertDeployment.status.in_(status_set))
    result = await db.execute(stmt)
    out: list[dict[str, Any]] = []
    for deployment in result.scalars().all():
        out.append(await redeploy_deployment(db, deployment, actor=actor))
    return out


async def dispatch_changed_sources(
    db: AsyncSession,
    scan_results: list[dict[str, Any]],
    *,
    actor: str = "system",
) -> list[dict[str, Any]]:
    """Dispatch certificates whose source scan reported a fingerprint change."""
    out: list[dict[str, Any]] = []
    changed_ids = [
        int(row["certificate_id"])
        for row in scan_results
        if row.get("ok") and row.get("changed")
    ]
    for cert_id in changed_ids:
        cert = await db.get(ManagerCertificate, cert_id)
        if cert is None or not cert.enabled:
            continue
        # A source fingerprint change makes even previously "synced" rows
        # stale; dispatch every binding for that certificate.
        out.extend(await dispatch_certificate(db, cert, actor=actor, statuses=()))
    return out


async def dispatch_pending_deployments(
    db: AsyncSession,
    *,
    actor: str = "system",
) -> list[dict[str, Any]]:
    """Dispatch deployments whose installed fingerprint is not the source.

    This intentionally derives work from persisted DB state instead of an
    in-memory "last scan" cache, so manager-jobs restarts cannot lose a
    source change before auto-dispatch runs.
    """
    rows = (
        await db.execute(
            select(ManagerCertDeployment, ManagerCertificate)
            .join(ManagerCertificate, ManagerCertificate.id == ManagerCertDeployment.certificate_id)
            .where(ManagerCertificate.enabled.is_(True))
            .where(ManagerCertificate.source_fingerprint_sha256.is_not(None))
            .order_by(ManagerCertDeployment.id)
        )
    ).all()
    out: list[dict[str, Any]] = []
    for deployment, cert in rows:
        pending = (
            deployment.status in {"outdated", "unknown", "deploy_failed"}
            or deployment.deployed_fingerprint_sha256 != cert.source_fingerprint_sha256
        )
        if pending:
            out.append(await redeploy_deployment(db, deployment, actor=actor))
    return out
