"""Certificate registry and deployment admin API."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core.runtime_settings import CERTIFICATE_SPECS, defaults_for
from app.core.settings_store import get_settings_store
from app.core.time import to_iso_z
from app.db.models.manager import ManagerCertDeployment, ManagerCertificate, ManagerHost
from app.db.models.pterodactyl import PteroUser
from app.schemas.settings import SettingsMessageResponse
from app.services import agent_client, host_registry
from app.services.audit import log_manager_activity
from app.services.cert_manager import acme_sh
from app.services.cert_manager.acme_sh import AcmeShError
from app.services.cert_manager.dispatcher import (
    dispatch_certificate,
    redeploy_deployment,
)
from app.services.cert_manager.source_scanner import scan_certificate_source

router = APIRouter(tags=["certificates"])


class DeploymentOut(BaseModel):
    id: int
    certificate_id: int
    host_id: int
    host_name: str | None = None
    host_kind: str | None = None
    target_name: str
    target_cert_path: str | None = None
    target_key_path: str | None = None
    target_path_error: str | None = None
    deployed_fingerprint_sha256: str | None
    deployed_not_after: str | None
    last_check_at: str | None
    last_check_error: str | None
    last_deploy_at: str | None
    last_deploy_attempt_at: str | None
    last_deploy_error: str | None
    status: str
    created_at: str | None
    updated_at: str | None


class CertificateOut(BaseModel):
    id: int
    name: str
    domains: list[str]
    source_type: str
    source_path: str
    source_fingerprint_sha256: str | None
    source_not_before: str | None
    source_not_after: str | None
    source_last_seen_at: str | None
    source_last_error: str | None
    alert_threshold_days: int
    enabled: bool
    created_at: str | None
    updated_at: str | None
    deployments: list[DeploymentOut] = Field(default_factory=list)


class DeploymentIn(BaseModel):
    host_id: int
    target_name: str = Field(default="", max_length=64)

    @field_validator("target_name")
    @classmethod
    def _target_name(cls, value: str) -> str:
        return value.strip()


class CertificateCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    domains: list[str] = Field(min_length=1)
    source_type: str = Field(default="acme_sh_local", max_length=32)
    source_path: str = Field(min_length=1, max_length=512)
    alert_threshold_days: int = Field(default=14, ge=1, le=90)
    enabled: bool = True
    deployments: list[DeploymentIn] = Field(default_factory=list)

    @field_validator("name", "source_type", "source_path")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        domains = [d.strip().lower() for d in value if d.strip()]
        if not domains:
            raise ValueError("at least one domain is required")
        return domains


class CertificatePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    domains: list[str] | None = None
    source_type: str | None = Field(default=None, min_length=1, max_length=32)
    source_path: str | None = Field(default=None, min_length=1, max_length=512)
    alert_threshold_days: int | None = Field(default=None, ge=1, le=90)
    enabled: bool | None = None

    @field_validator("name", "source_type", "source_path")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("domains")
    @classmethod
    def _domains_optional(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        domains = [d.strip().lower() for d in value if d.strip()]
        if not domains:
            raise ValueError("at least one domain is required")
        return domains


class CertificateSettingsOut(BaseModel):
    webhook_token_set: bool
    alert_email_enabled: bool
    alert_email_admin_ids: list[int]


class CertificateSettingsIn(BaseModel):
    webhook_token: str | None = Field(default=None, min_length=1)
    alert_email_enabled: bool | None = None
    alert_email_admin_ids: list[int] | None = None


class AcmeCertificateOut(BaseModel):
    domain: str
    alt_names: list[str]
    is_ecc: bool
    conf_path: str
    cert_dir: str
    source_path: str | None
    source_compatible: bool
    fullchain_path: str | None
    key_path: str | None
    cert_create_time_iso: str | None
    next_renew_time_iso: str | None
    ca: str | None
    webroot: str | None
    reload_cmd_set: bool
    fingerprint_sha256: str | None
    not_before: str | None
    not_after: str | None
    source_error: str | None
    registered_certificate_id: int | None = None


class AcmeStatusOut(BaseModel):
    home: str
    binary: str
    home_exists: bool
    binary_exists: bool
    binary_executable: bool
    certificate_count: int
    registered_count: int
    certificates: list[AcmeCertificateOut]


class AcmeRegisterIn(BaseModel):
    domain: str = Field(min_length=1)
    is_ecc: bool = True
    name: str | None = Field(default=None, min_length=1, max_length=128)
    alert_threshold_days: int = Field(default=14, ge=1, le=90)
    enabled: bool = True
    deployments: list[DeploymentIn] = Field(default_factory=list)

    @field_validator("domain", "name")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


def _cert_status_paths(payload: dict[str, Any], target_name: str) -> tuple[str | None, str | None, str | None]:
    if target_name:
        targets = payload.get("targets") or []
        target = next(
            (
                item for item in targets
                if isinstance(item, dict) and item.get("name") == target_name
            ),
            None,
        )
        if target is None:
            return None, None, f"agent target not found: {target_name}"
        if target.get("type") == "synology_dsm":
            dsm_id = target.get("dsm_cert_id")
            desc = target.get("certificate_desc") or target_name
            label = f"dsm:{dsm_id}" if dsm_id else f"dsm:{desc}"
            return label, None, None
        paths = target.get("paths") if isinstance(target, dict) else None
    else:
        paths = payload.get("wings_yaml_paths")

    if not isinstance(paths, dict):
        return None, None, "agent did not report certificate paths"
    cert_path = paths.get("cert")
    key_path = paths.get("key")
    return (
        str(cert_path) if cert_path else None,
        str(key_path) if key_path else None,
        None,
    )


async def _prefetch_cert_status_for_hosts(
    db: AsyncSession,
    host_ids: list[int],
    cert_status_cache: dict[int, tuple[dict[str, Any] | None, str | None]],
) -> None:
    """Fan-out agent /cert/status calls in parallel and populate the cache.

    Without this, ``_load_deployments`` (and every endpoint that builds a
    CertificateOut) walks deployments serially with a 3s agent timeout each,
    so a 5-host certificate takes up to 15s to render. (Audit M4.)
    """
    pending = [hid for hid in set(host_ids) if hid not in cert_status_cache]
    if not pending:
        return

    async def _fetch_one(hid: int) -> tuple[int, dict[str, Any] | None, str | None]:
        try:
            endpoint, token = await host_registry.get_credentials(db, hid)
            payload = await agent_client.get_cert_status(endpoint, token, timeout=3.0)
            return hid, payload, None
        except (host_registry.HostRegistryError, agent_client.AgentClientError) as exc:
            return hid, None, str(exc)

    results = await asyncio.gather(*(_fetch_one(hid) for hid in pending))
    for hid, payload, err in results:
        cert_status_cache[hid] = (payload, err)


async def _deployment_target_paths(
    db: AsyncSession,
    dep: ManagerCertDeployment,
    cert_status_cache: dict[int, tuple[dict[str, Any] | None, str | None]],
) -> tuple[str | None, str | None, str | None]:
    if dep.host_id not in cert_status_cache:
        try:
            endpoint, token = await host_registry.get_credentials(db, dep.host_id)
            payload = await agent_client.get_cert_status(endpoint, token, timeout=3.0)
            cert_status_cache[dep.host_id] = (payload, None)
        except (host_registry.HostRegistryError, agent_client.AgentClientError) as exc:
            cert_status_cache[dep.host_id] = (None, str(exc))

    payload, error = cert_status_cache[dep.host_id]
    if error:
        return None, None, error
    if payload is None:
        return None, None, "agent certificate status unavailable"
    return _cert_status_paths(payload, dep.target_name)


def _deployment_out(
    dep: ManagerCertDeployment,
    host: ManagerHost | None = None,
    *,
    target_cert_path: str | None = None,
    target_key_path: str | None = None,
    target_path_error: str | None = None,
) -> DeploymentOut:
    return DeploymentOut(
        id=dep.id,
        certificate_id=dep.certificate_id,
        host_id=dep.host_id,
        host_name=host.name if host else None,
        host_kind=host.kind if host else None,
        target_name=dep.target_name,
        target_cert_path=target_cert_path,
        target_key_path=target_key_path,
        target_path_error=target_path_error,
        deployed_fingerprint_sha256=dep.deployed_fingerprint_sha256,
        deployed_not_after=to_iso_z(dep.deployed_not_after),
        last_check_at=to_iso_z(dep.last_check_at),
        last_check_error=dep.last_check_error,
        last_deploy_at=to_iso_z(dep.last_deploy_at),
        last_deploy_attempt_at=to_iso_z(dep.last_deploy_attempt_at),
        last_deploy_error=dep.last_deploy_error,
        status=dep.status,
        created_at=to_iso_z(dep.created_at),
        updated_at=to_iso_z(dep.updated_at),
    )


async def _load_deployments(
    db: AsyncSession,
    cert_id: int,
    cert_status_cache: dict[int, tuple[dict[str, Any] | None, str | None]] | None = None,
) -> list[DeploymentOut]:
    if cert_status_cache is None:
        cert_status_cache = {}
    rows = (
        await db.execute(
            select(ManagerCertDeployment, ManagerHost)
            .join(ManagerHost, ManagerHost.id == ManagerCertDeployment.host_id)
            .where(ManagerCertDeployment.certificate_id == cert_id)
            .order_by(ManagerCertDeployment.id)
        )
    ).all()
    # Pre-fetch all distinct host cert statuses concurrently. This is a no-op
    # for hosts already in the cache (e.g. shared cache across the list endpoint).
    await _prefetch_cert_status_for_hosts(
        db,
        [int(dep.host_id) for dep, _host in rows],
        cert_status_cache,
    )
    out: list[DeploymentOut] = []
    for dep, host in rows:
        cert_path, key_path, path_error = await _deployment_target_paths(db, dep, cert_status_cache)
        out.append(
            _deployment_out(
                dep,
                host,
                target_cert_path=cert_path,
                target_key_path=key_path,
                target_path_error=path_error,
            )
        )
    return out


async def _certificate_out(
    db: AsyncSession,
    cert: ManagerCertificate,
    cert_status_cache: dict[int, tuple[dict[str, Any] | None, str | None]] | None = None,
) -> CertificateOut:
    return CertificateOut(
        id=cert.id,
        name=cert.name,
        domains=list(cert.domains or []),
        source_type=cert.source_type,
        source_path=cert.source_path,
        source_fingerprint_sha256=cert.source_fingerprint_sha256,
        source_not_before=to_iso_z(cert.source_not_before),
        source_not_after=to_iso_z(cert.source_not_after),
        source_last_seen_at=to_iso_z(cert.source_last_seen_at),
        source_last_error=cert.source_last_error,
        alert_threshold_days=cert.alert_threshold_days,
        enabled=cert.enabled,
        created_at=to_iso_z(cert.created_at),
        updated_at=to_iso_z(cert.updated_at),
        deployments=await _load_deployments(db, cert.id, cert_status_cache),
    )


async def _require_certificate(db: AsyncSession, cert_id: int) -> ManagerCertificate:
    cert = await db.get(ManagerCertificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="certificate not found")
    return cert


async def _require_deployment(
    db: AsyncSession, cert_id: int, deployment_id: int,
) -> ManagerCertDeployment:
    dep = await db.get(ManagerCertDeployment, deployment_id)
    if dep is None or dep.certificate_id != cert_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deployment not found")
    return dep


async def _add_deployment_row(
    db: AsyncSession,
    cert_id: int,
    body: DeploymentIn,
) -> ManagerCertDeployment:
    try:
        host = await host_registry.require_host_by_id(db, body.host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Validate target_name against agent for non-wings hosts.
    # Wings hosts allow empty target_name (default api.ssl paths).
    if host.kind != host_registry.KIND_WINGS_NODE and not body.target_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_name is required for non-wings hosts",
        )

    if body.target_name:
        try:
            endpoint, token = await host_registry.get_credentials(db, body.host_id)
        except host_registry.AgentNotConfigured as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        try:
            cert_status = await agent_client.get_cert_status(endpoint, token, timeout=15.0)
        except agent_client.AgentClientError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"failed to reach agent: {exc}",
            ) from exc
        targets = cert_status.get("targets") or []
        known = {item.get("name") for item in targets if isinstance(item, dict)}
        if body.target_name not in known:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown target_name: {body.target_name!r} (available: {sorted(known)})",
            )

    dep = ManagerCertDeployment(
        certificate_id=cert_id,
        host_id=body.host_id,
        target_name=body.target_name,
    )
    db.add(dep)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="deployment already exists for this certificate/host/target",
        ) from exc
    return dep


async def _registered_source_map(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(select(ManagerCertificate.id, ManagerCertificate.source_path))
    ).all()
    return {source_path.rstrip("/"): cert_id for cert_id, source_path in rows}


async def _acme_out_list(db: AsyncSession) -> list[AcmeCertificateOut]:
    registered = await _registered_source_map(db)
    out: list[AcmeCertificateOut] = []
    for cert in acme_sh.discover_certificates():
        registered_id = registered.get(cert.source_path.rstrip("/")) if cert.source_path else None
        out.append(
            AcmeCertificateOut(
                domain=cert.domain,
                alt_names=cert.alt_names,
                is_ecc=cert.is_ecc,
                conf_path=cert.conf_path,
                cert_dir=cert.cert_dir,
                source_path=cert.source_path,
                source_compatible=cert.source_compatible,
                fullchain_path=cert.fullchain_path,
                key_path=cert.key_path,
                cert_create_time_iso=cert.cert_create_time_iso,
                next_renew_time_iso=cert.next_renew_time_iso,
                ca=cert.ca,
                webroot=cert.webroot,
                reload_cmd_set=cert.reload_cmd_set,
                fingerprint_sha256=cert.fingerprint_sha256,
                not_before=to_iso_z(cert.not_before),
                not_after=to_iso_z(cert.not_after),
                source_error=cert.source_error,
                registered_certificate_id=registered_id,
            )
        )
    return out


def _domains_for_acme(cert: acme_sh.AcmeShCertificate) -> list[str]:
    domains: list[str] = []
    for value in [cert.domain, *cert.alt_names]:
        if value and value not in domains:
            domains.append(value)
    return domains


def _find_acme_for_certificate(cert: ManagerCertificate) -> acme_sh.AcmeShCertificate | None:
    normalized_source = cert.source_path.rstrip("/")
    cert_domains = set(cert.domains or [])
    for acme_cert in acme_sh.discover_certificates():
        if acme_cert.source_path and acme_cert.source_path.rstrip("/") == normalized_source:
            return acme_cert
        if acme_cert.domain in cert_domains:
            return acme_cert
        if cert_domains.intersection(acme_cert.alt_names):
            return acme_cert
    return None


@router.get("/admin/certificates", response_model=list[CertificateOut])
async def list_certificates(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CertificateOut]:
    certs = (
        await db.execute(select(ManagerCertificate).order_by(ManagerCertificate.id))
    ).scalars().all()
    cert_status_cache: dict[int, tuple[dict[str, Any] | None, str | None]] = {}
    return [await _certificate_out(db, cert, cert_status_cache) for cert in certs]


@router.get("/admin/certificates/acme/status", response_model=AcmeStatusOut)
async def get_acme_status(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AcmeStatusOut:
    base = acme_sh.status()
    certs = await _acme_out_list(db)
    return AcmeStatusOut(
        **base,
        registered_count=sum(1 for cert in certs if cert.registered_certificate_id is not None),
        certificates=certs,
    )


@router.get("/admin/certificates/acme/certs", response_model=list[AcmeCertificateOut])
async def list_acme_certificates(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AcmeCertificateOut]:
    return await _acme_out_list(db)


@router.post("/admin/certificates/acme/register", response_model=CertificateOut, status_code=status.HTTP_201_CREATED)
async def register_acme_certificate(
    body: AcmeRegisterIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CertificateOut:
    acme_cert = acme_sh.find_certificate(body.domain, body.is_ecc)
    if acme_cert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="acme.sh certificate not found")
    if not acme_cert.source_path or not acme_cert.source_compatible:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="acme.sh certificate does not expose a compatible source path",
        )
    existing_id = (await _registered_source_map(db)).get(acme_cert.source_path.rstrip("/"))
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"certificate source is already registered: {existing_id}",
        )

    cert = ManagerCertificate(
        name=body.name or f"{acme_cert.domain} certificate",
        domains=_domains_for_acme(acme_cert),
        source_type="acme_sh_local",
        source_path=acme_cert.source_path.rstrip("/"),
        alert_threshold_days=body.alert_threshold_days,
        enabled=body.enabled,
    )
    try:
        db.add(cert)
        await db.flush()
        for dep_body in body.deployments:
            await _add_deployment_row(db, cert.id, dep_body)
        scan_result = await scan_certificate_source(db, cert, commit=False)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="certificate or deployment already exists",
        ) from exc
    except Exception:
        await db.rollback()
        raise

    await db.refresh(cert)
    await log_manager_activity(
        db,
        actor=admin.username,
        category="certificate",
        status="success" if scan_result.get("ok") else "partial",
        detail_key="cert.acme.register",
        detail_params={
            "certificate_id": cert.id,
            "domain": acme_cert.domain,
            "source_scan": scan_result,
        },
    )
    return await _certificate_out(db, cert)


@router.post("/admin/certificates", response_model=CertificateOut, status_code=status.HTTP_201_CREATED)
async def create_certificate(
    body: CertificateCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CertificateOut:
    cert = ManagerCertificate(
        name=body.name,
        domains=body.domains,
        source_type=body.source_type,
        source_path=body.source_path.rstrip("/"),
        alert_threshold_days=body.alert_threshold_days,
        enabled=body.enabled,
    )
    try:
        db.add(cert)
        await db.flush()
        for dep_body in body.deployments:
            await _add_deployment_row(db, cert.id, dep_body)
        scan_result = await scan_certificate_source(db, cert, commit=False)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="certificate or deployment already exists",
        ) from exc
    except Exception:
        await db.rollback()
        raise

    await db.refresh(cert)
    await log_manager_activity(
        db,
        actor=admin.username,
        category="certificate",
        status="success" if scan_result.get("ok") else "partial",
        detail_key="cert.create",
        detail_params={
            "certificate_id": cert.id,
            "name": cert.name,
            "source_scan": scan_result,
        },
    )
    return await _certificate_out(db, cert)


@router.get("/admin/certificates/settings", response_model=CertificateSettingsOut)
async def get_certificate_settings(
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CertificateSettingsOut:
    values = await get_settings_store().get_many(db, defaults_for(CERTIFICATE_SPECS))
    raw_ids = str(values.get("CERT_ALERT_EMAIL_ADMIN_IDS") or "")
    return CertificateSettingsOut(
        webhook_token_set=bool(values.get("CERT_WEBHOOK_TOKEN")),
        alert_email_enabled=bool(values.get("CERT_ALERT_EMAIL_ENABLED", True)),
        alert_email_admin_ids=[int(x) for x in raw_ids.split(",") if x.strip().isdigit()],
    )


@router.post("/admin/certificates/settings", response_model=SettingsMessageResponse)
async def save_certificate_settings(
    body: CertificateSettingsIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingsMessageResponse:
    updates: dict[str, Any] = {}
    if body.webhook_token is not None:
        updates["CERT_WEBHOOK_TOKEN"] = body.webhook_token.strip()
    if body.alert_email_enabled is not None:
        updates["CERT_ALERT_EMAIL_ENABLED"] = body.alert_email_enabled
    if body.alert_email_admin_ids is not None:
        updates["CERT_ALERT_EMAIL_ADMIN_IDS"] = ",".join(
            str(int(x)) for x in body.alert_email_admin_ids
        )
    if updates:
        await get_settings_store().set_values(db, updates, category="certificates")
    await log_manager_activity(
        db,
        actor=admin.username,
        category="settings",
        status="success",
        detail_key="cert.settings.update",
        detail_params={"changed": sorted(updates.keys())},
    )
    return SettingsMessageResponse(message="证书设置已保存。")


@router.get("/admin/certificates/{cert_id}", response_model=CertificateOut)
async def get_certificate(
    cert_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CertificateOut:
    return await _certificate_out(db, await _require_certificate(db, cert_id))


@router.patch("/admin/certificates/{cert_id}", response_model=CertificateOut)
async def patch_certificate(
    cert_id: int,
    body: CertificatePatchIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CertificateOut:
    cert = await _require_certificate(db, cert_id)
    changed: list[str] = []
    for field in body.model_fields_set:
        value = getattr(body, field)
        if field == "source_path" and isinstance(value, str):
            value = value.rstrip("/")
        if getattr(cert, field) != value:
            setattr(cert, field, value)
            changed.append(field)
    if changed:
        await db.commit()
        await db.refresh(cert)
    scan_result = None
    if set(changed) & {"source_path", "source_type", "enabled"}:
        scan_result = await scan_certificate_source(db, cert)
    await log_manager_activity(
        db,
        actor=admin.username,
        category="certificate",
        status="success",
        detail_key="cert.patch",
        detail_params={"certificate_id": cert.id, "changed": changed, "source_scan": scan_result},
    )
    return await _certificate_out(db, cert)


@router.delete("/admin/certificates/{cert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certificate(
    cert_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    cert = await _require_certificate(db, cert_id)
    snapshot = {"certificate_id": cert.id, "name": cert.name}
    await db.delete(cert)
    await db.commit()
    await log_manager_activity(
        db,
        actor=admin.username,
        category="certificate",
        status="success",
        detail_key="cert.delete",
        detail_params=snapshot,
    )


@router.post(
    "/admin/certificates/{cert_id}/deployments",
    response_model=DeploymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_deployment(
    cert_id: int,
    body: DeploymentIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DeploymentOut:
    await _require_certificate(db, cert_id)
    try:
        dep = await _add_deployment_row(db, cert_id, body)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    host = await db.get(ManagerHost, dep.host_id)
    await log_manager_activity(
        db,
        actor=admin.username,
        category="certificate",
        status="success",
        detail_key="cert.deployment.create",
        detail_params={"certificate_id": cert_id, "deployment_id": dep.id, "host_id": dep.host_id},
    )
    return _deployment_out(dep, host)


@router.delete(
    "/admin/certificates/{cert_id}/deployments/{deployment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_deployment(
    cert_id: int,
    deployment_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    dep = await _require_deployment(db, cert_id, deployment_id)
    snapshot = {"certificate_id": cert_id, "deployment_id": dep.id, "host_id": dep.host_id}
    await db.delete(dep)
    await db.commit()
    await log_manager_activity(
        db,
        actor=admin.username,
        category="certificate",
        status="success",
        detail_key="cert.deployment.delete",
        detail_params=snapshot,
    )


@router.post("/admin/certificates/{cert_id}/deployments/{deployment_id}/redeploy")
async def redeploy_certificate(
    cert_id: int,
    deployment_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # manager-jobs may update the same deployment row concurrently (status
    # scanner/dispatcher). Retry once on MySQL 1020 to avoid surfacing a
    # transient write-conflict as a hard API failure.
    for _attempt in range(2):
        dep = await _require_deployment(db, cert_id, deployment_id)
        try:
            return await redeploy_deployment(db, dep, actor=admin.username)
        except OperationalError as exc:
            if "1020" not in str(exc):
                raise
            await db.rollback()
            continue
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="deployment row changed concurrently; please retry",
    )


@router.post("/admin/certificates/{cert_id}/renew-force")
async def renew_certificate_force(
    cert_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cert = await _require_certificate(db, cert_id)
    acme_cert = _find_acme_for_certificate(cert)
    if acme_cert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="matching acme.sh certificate not found")

    before_fingerprint = cert.source_fingerprint_sha256
    try:
        renew_result = await acme_sh.renew_force(acme_cert.domain, is_ecc=acme_cert.is_ecc)
    except AcmeShError as exc:
        await log_manager_activity(
            db,
            actor=admin.username,
            category="certificate",
            status="error",
            detail_key="cert.renew_force.failed",
            detail_params={"certificate_id": cert.id, "domain": acme_cert.domain, "error": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    scan_result = await scan_certificate_source(db, cert)
    await db.refresh(cert)
    changed = (
        scan_result.get("ok")
        and before_fingerprint is not None
        and before_fingerprint != cert.source_fingerprint_sha256
    )
    dispatch_results: list[dict[str, Any]] = []
    if renew_result.get("ok") and changed:
        dispatch_results = await dispatch_certificate(db, cert, actor=admin.username, statuses=())

    status_text = "success" if renew_result.get("ok") else "error"
    await log_manager_activity(
        db,
        actor=admin.username,
        category="certificate",
        status=status_text,
        detail_key="cert.renew_force",
        detail_params={
            "certificate_id": cert.id,
            "domain": acme_cert.domain,
            "exit_code": renew_result.get("exit_code"),
            "changed": bool(changed),
            "dispatch_count": len(dispatch_results),
        },
    )
    if not renew_result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=renew_result.get("output") or "acme.sh renew failed",
        )
    return {
        "ok": True,
        "renew": renew_result,
        "source_scan": scan_result,
        "changed": bool(changed),
        "dispatch": dispatch_results,
        "certificate": await _certificate_out(db, cert),
    }


@router.post("/admin/certificates/{cert_id}/scan")
async def scan_certificate(
    cert_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cert = await _require_certificate(db, cert_id)
    return await scan_certificate_source(db, cert)


@router.post("/cert/source-changed")
async def cert_source_changed_webhook(
    request: Request,
    source_path: str | None = Query(default=None, min_length=1),
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    expected = str(
        await get_settings_store().get(
            db,
            "CERT_WEBHOOK_TOKEN",
            CERTIFICATE_SPECS["CERT_WEBHOOK_TOKEN"].default_value(),
        )
        or ""
    )
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="certificate webhook token is not configured",
        )
    if not x_webhook_token or not secrets.compare_digest(x_webhook_token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid webhook token")

    if source_path is None:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = await request.json()
            if isinstance(payload, dict):
                source_path = payload.get("source_path")
        else:
            form = await request.form()
            raw = form.get("source_path")
            source_path = str(raw) if raw is not None else None
    if not source_path or not str(source_path).strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_path is required")

    normalized_path = source_path.strip().rstrip("/")
    certs = (
        await db.execute(
            select(ManagerCertificate)
            .where(ManagerCertificate.source_path == normalized_path)
            .where(ManagerCertificate.enabled.is_(True))
        )
    ).scalars().all()
    if not certs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="certificate source not registered")

    results: list[dict[str, Any]] = []
    dispatch_results: list[dict[str, Any]] = []
    for cert in certs:
        scan = await scan_certificate_source(db, cert)
        results.append(scan)
        dispatch_results.extend(
            await dispatch_certificate(db, cert, actor="system", statuses=())
        )
    await log_manager_activity(
        db,
        actor="system",
        category="certificate",
        status="success",
        detail_key="cert.source_changed",
        detail_params={
            "source": "acme_webhook",
            "source_path": normalized_path,
            "certificate_count": len(certs),
            "dispatch_count": len(dispatch_results),
        },
    )
    return {
        "ok": True,
        "source_path": normalized_path,
        "source_scan": results,
        "dispatch": dispatch_results,
    }
