"""Admin endpoints for the unified ``manager_hosts`` registry.

These routes are the *new* canonical surface for managing every box
manager talks to (wings nodes, nginx proxies, NAS, generic linux). The
legacy ``/api/admin/nodes/{id}/agent*`` routes still exist but only
operate on the wings_node subset; they will be removed once the
frontend migrates here.

Frontend ownership belongs to PR-C; these routes are wired now so the
backend can be exercised end-to-end (curl / pytest) before any UI work
begins.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_admin
from app.api.deps.db import get_db
from app.core import alert_defaults
from app.db.models.manager import HostAlertRule, HostAlertSettings
from app.db.models.pterodactyl import PteroUser
from app.services import agent_client, host_registry
from app.services.audit import log_manager_activity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/hosts", tags=["admin-hosts"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class HostOut(BaseModel):
    """Public projection of ``manager_hosts``.

    The Fernet ciphertext (``agent_token_enc``) is intentionally omitted;
    plaintext tokens are only ever returned by ``POST /{id}/agent-token/rotate``
    and exactly once at host creation time.
    """

    id: int
    name: str
    kind: str
    hostname: str
    agent_url: str
    pterodactyl_node_id: int | None
    extra_metadata: dict | None
    enabled: bool
    inbound_reachable: bool
    last_seen_at: str | None
    last_status_at: str | None
    created_at: str | None
    updated_at: str | None


def _serialize(host) -> HostOut:
    return HostOut(
        id=host.id,
        name=host.name,
        kind=host.kind,
        hostname=host.hostname,
        agent_url=host.agent_url,
        pterodactyl_node_id=host.pterodactyl_node_id,
        extra_metadata=host.extra_metadata,
        enabled=host.enabled,
        inbound_reachable=host.inbound_reachable,
        last_seen_at=host.last_seen_at.isoformat() if host.last_seen_at else None,
        last_status_at=host.last_status_at.isoformat() if host.last_status_at else None,
        created_at=host.created_at.isoformat() if host.created_at else None,
        updated_at=host.updated_at.isoformat() if host.updated_at else None,
    )


class HostCreateIn(BaseModel):
    """POST /admin/hosts body. ``pterodactyl_node_id`` is required iff
    ``kind == 'wings_node'`` — host_registry enforces this; we just relay
    the validation error as 400.

    ``agent_token`` must be provided by the operator from the host-side
    agent bootstrap output (systemd/journal). Manager does not generate
    a token in this flow.

    Per design doc §5.3 the endpoint **must probe successfully** before
    the host row is committed; a probe failure returns HTTP 400 and no
    row is inserted.
    """

    name: str = Field(min_length=1, max_length=128)
    kind: str
    hostname: str = Field(min_length=1, max_length=255)
    agent_url: str = Field(min_length=1, max_length=255)
    agent_token: str = Field(min_length=1)
    pterodactyl_node_id: int | None = None
    extra_metadata: dict | None = None
    enabled: bool = True

    @field_validator("kind")
    @classmethod
    def _kind_allowed(cls, v: str) -> str:
        if v not in host_registry.ALLOWED_KINDS:
            raise ValueError(
                f"kind must be one of {sorted(host_registry.ALLOWED_KINDS)}"
            )
        return v


class HostPatchIn(BaseModel):
    """PATCH /admin/hosts/{id} body. All fields optional; ``None`` means
    "do not change". The ``agent_token`` field is the plaintext Bearer
    minted client-side; if supplied, manager re-encrypts and persists it.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    agent_url: str | None = Field(default=None, min_length=1, max_length=255)
    agent_token: str | None = Field(default=None, min_length=1)
    extra_metadata: dict | None = None
    enabled: bool | None = None


class HostCreateOut(BaseModel):
    host: HostOut


class ProbeOut(BaseModel):
    ok: bool
    response: dict | None = None
    error: str | None = None
    latency_ms: int | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[HostOut])
async def list_hosts(
    kind: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[HostOut]:
    if kind is not None and kind not in host_registry.ALLOWED_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown kind: {kind!r}",
        )
    hosts = await host_registry.list_hosts(db, kind=kind, enabled=enabled)
    return [_serialize(h) for h in hosts]


@router.post("", response_model=HostCreateOut, status_code=status.HTTP_201_CREATED)
async def create_host(
    body: HostCreateIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HostCreateOut:
    token = body.agent_token
    probe = await host_registry.probe_credentials(body.agent_url, token)
    if not probe.get("ok"):
        await log_manager_activity(
            db, actor=admin.username, action="create_host", status="error",
            detail_key="host.create.probe_failed",
            detail_params={"name": body.name, "kind": body.kind, "error": probe.get("error")},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"agent probe failed: {probe.get('error') or 'unknown'}",
        )

    try:
        host = await host_registry.create_host(
            db,
            name=body.name,
            kind=body.kind,
            hostname=body.hostname,
            agent_url=body.agent_url,
            agent_token=token,
            pterodactyl_node_id=body.pterodactyl_node_id,
            extra_metadata=body.extra_metadata,
            enabled=body.enabled,
        )
    except host_registry.HostRegistryError as exc:
        await log_manager_activity(
            db, actor=admin.username, action="create_host", status="error",
            detail_key="host.create.invalid",
            detail_params={"name": body.name, "kind": body.kind, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
    await log_manager_activity(
        db, actor=admin.username, action="create_host", status="success",
        detail_key="host.create.ok",
        detail_params={
            "host_id": host.id, "name": host.name, "kind": host.kind,
            "hostname": host.hostname, "token_generated": False,
        },
    )
    return HostCreateOut(host=_serialize(host))


@router.get("/{host_id}", response_model=HostOut)
async def get_host(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HostOut:
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _serialize(host)


@router.patch("/{host_id}", response_model=HostOut)
async def patch_host(
    host_id: int,
    body: HostPatchIn,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HostOut:
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        host = await host_registry.update_host(
            db,
            host,
            name=body.name,
            hostname=body.hostname,
            agent_url=body.agent_url,
            agent_token=body.agent_token,
            extra_metadata=body.extra_metadata,
            enabled=body.enabled,
        )
    except host_registry.HostRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
    await log_manager_activity(
        db, actor=admin.username, action="patch_host", status="success",
        detail_key="host.patch.ok",
        detail_params={
            "host_id": host.id,
            # Mask the secret in the audit trail; keep the field name so
            # operators can see *that* it was rotated, just not the value.
            "changed": sorted(body.model_fields_set),
        },
    )
    return _serialize(host)


@router.delete("/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_host(
    host_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    snapshot = {"host_id": host.id, "name": host.name, "kind": host.kind}
    await host_registry.delete_host(db, host)
    await log_manager_activity(
        db, actor=admin.username, action="delete_host", status="success",
        detail_key="host.delete.ok", detail_params=snapshot,
    )


@router.post("/{host_id}/probe", response_model=ProbeOut)
async def probe_host(
    host_id: int,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProbeOut:
    """Hit the host's ``/v1/status`` and update cached reachability.

    Returns ``ok=true`` with the agent's status payload, or ``ok=false``
    plus a short error tag (transport / HTTP code). Disabled hosts and
    hosts with bad credentials surface as ``AgentNotConfigured`` -> 400.
    """
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        result = await host_registry.probe(db, host)
    except host_registry.AgentNotConfigured as exc:
        await log_manager_activity(
            db, actor=admin.username, action="probe_host", status="error",
            detail_key="host.probe.unconfigured",
            detail_params={"host_id": host.id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
    await log_manager_activity(
        db, actor=admin.username, action="probe_host",
        status="success" if result.get("ok") else "error",
        detail_key="host.probe.ok" if result.get("ok") else "host.probe.failed",
        detail_params={
            "host_id": host.id,
            "ok": bool(result.get("ok")),
            "error": result.get("error"),
        },
    )
    return ProbeOut(
        ok=bool(result.get("ok")),
        response=result.get("response"),
        error=result.get("error"),
        latency_ms=result.get("latency_ms"),
    )


# ---------------------------------------------------------------------------
# Certificate targets
# ---------------------------------------------------------------------------


class CertTargetOut(BaseModel):
    name: str
    type: str
    exists: bool | None = None
    paths: dict[str, str] | None = None
    certificate_desc: str | None = None
    dsm_cert_id: str | None = None
    is_default: bool | None = None
    domains: list[str] | None = None
    services: list[dict] | None = None
    current_cert: dict | None = None
    error: str | None = None


class CertTargetsOut(BaseModel):
    targets: list[CertTargetOut]
    wings_yaml_paths: dict[str, str | None] | None = None


@router.get("/{host_id}/cert-targets", response_model=CertTargetsOut)
async def get_host_cert_targets(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CertTargetsOut:
    try:
        endpoint, token = await host_registry.get_credentials(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except host_registry.AgentNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        payload = await agent_client.get_cert_status(endpoint, token, timeout=15.0)
    except agent_client.AgentClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"agent unreachable: {exc}",
        ) from exc

    targets_raw = payload.get("targets") or []
    targets_out: list[CertTargetOut] = []
    for item in targets_raw:
        targets_out.append(CertTargetOut(
            name=item.get("name", ""),
            type=item.get("type", "file"),
            exists=item.get("exists") if isinstance(item.get("exists"), bool) else None,
            paths=item.get("paths") if isinstance(item.get("paths"), dict) else None,
            certificate_desc=item.get("certificate_desc"),
            dsm_cert_id=str(item.get("dsm_cert_id")) if item.get("dsm_cert_id") else None,
            is_default=item.get("is_default") if isinstance(item.get("is_default"), bool) else None,
            domains=item.get("domains") if isinstance(item.get("domains"), list) else None,
            services=item.get("services") if isinstance(item.get("services"), list) else None,
            current_cert=item.get("current_cert") if isinstance(item.get("current_cert"), dict) else None,
            error=item.get("error"),
        ))

    wings_paths = payload.get("wings_yaml_paths")
    return CertTargetsOut(
        targets=targets_out,
        wings_yaml_paths=wings_paths if isinstance(wings_paths, dict) else None,
    )


# ---------------------------------------------------------------------------
# Per-host alert settings + rules
# ---------------------------------------------------------------------------


class HostAlertSettingsSchema(BaseModel):
    """Override fields for per-host alert channel settings.

    ``None`` on any field means "inherit default" (defaults live in
    ``app.core.alert_defaults``). The PUT endpoint treats missing or
    null as "clear override"; to set a value, include it explicitly.
    """

    email_enabled: bool | None = None
    email_recipients: list[int] | None = None  # admin user ids
    min_severity: Literal["info", "warning", "critical"] | None = None
    notify_resolve: bool | None = None
    cooldown_min: int | None = Field(default=None, ge=1, le=1440)


class HostAlertRuleSchema(BaseModel):
    """Per-host override for one alert type. ``alert_type`` is required;
    all other fields are nullable — ``None`` clears the override for that
    field and the default is used at evaluation time.
    """

    alert_type: str
    enabled: bool | None = None
    threshold: float | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    sustain_min: int | None = Field(default=None, ge=1, le=60)

    @field_validator("alert_type")
    @classmethod
    def _alert_type_known(cls, v: str) -> str:
        if v not in alert_defaults.ALERT_TYPES:
            raise ValueError(
                f"alert_type must be one of {list(alert_defaults.ALERT_TYPES)}"
            )
        return v


class HostAlertsResponse(BaseModel):
    """GET response — user overrides only, plus the resolved defaults so
    the UI can show placeholder values. The UI merges on display.
    """

    settings: HostAlertSettingsSchema
    rules: list[HostAlertRuleSchema]
    defaults: dict[str, object]


class HostAlertsUpdate(BaseModel):
    """PUT body — full replacement of overrides for this host.

    - ``settings``: new override row. Any field set to null clears that
      single override.
    - ``rules``: full replacement of this host's per-type overrides. A
      rule omitted from the list removes any existing override for that
      type. All fields null inside a rule keeps the row (useful for
      disabling via ``enabled=false`` without otherwise tweaking
      thresholds).
    """

    settings: HostAlertSettingsSchema = Field(default_factory=HostAlertSettingsSchema)
    rules: list[HostAlertRuleSchema] = Field(default_factory=list)


def _defaults_payload() -> dict[str, object]:
    return {
        "email_enabled": alert_defaults.DEFAULT_EMAIL_ENABLED,
        "email_recipients": list(alert_defaults.DEFAULT_EMAIL_RECIPIENTS),
        "min_severity": alert_defaults.DEFAULT_MIN_SEVERITY,
        "notify_resolve": alert_defaults.DEFAULT_NOTIFY_RESOLVE,
        "cooldown_min": alert_defaults.DEFAULT_COOLDOWN_MIN,
        "rules": {
            atype: alert_defaults.default_rule(atype)
            for atype in alert_defaults.ALERT_TYPES
        },
    }


@router.get("/{host_id}/alerts", response_model=HostAlertsResponse)
async def get_host_alerts(
    host_id: int,
    _admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HostAlertsResponse:
    try:
        await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    settings_row = (
        await db.execute(
            select(HostAlertSettings).where(HostAlertSettings.host_id == host_id)
        )
    ).scalar_one_or_none()

    rule_rows = (
        await db.execute(
            select(HostAlertRule).where(HostAlertRule.host_id == host_id)
        )
    ).scalars().all()

    settings_out = (
        HostAlertSettingsSchema(
            email_enabled=settings_row.email_enabled,
            email_recipients=settings_row.email_recipients,
            min_severity=settings_row.min_severity,  # type: ignore[arg-type]
            notify_resolve=settings_row.notify_resolve,
            cooldown_min=settings_row.cooldown_min,
        )
        if settings_row is not None
        else HostAlertSettingsSchema()
    )

    rules_out = [
        HostAlertRuleSchema(
            alert_type=r.alert_type,
            enabled=r.enabled,
            threshold=r.threshold,
            warning_threshold=r.warning_threshold,
            critical_threshold=r.critical_threshold,
            sustain_min=r.sustain_min,
        )
        for r in rule_rows
    ]

    return HostAlertsResponse(
        settings=settings_out,
        rules=rules_out,
        defaults=_defaults_payload(),
    )


@router.put("/{host_id}/alerts", response_model=HostAlertsResponse)
async def put_host_alerts(
    host_id: int,
    body: HostAlertsUpdate,
    admin: PteroUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HostAlertsResponse:
    try:
        host = await host_registry.require_host_by_id(db, host_id)
    except host_registry.HostNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # --- settings upsert ---
    s = body.settings
    settings_row = (
        await db.execute(
            select(HostAlertSettings).where(HostAlertSettings.host_id == host_id)
        )
    ).scalar_one_or_none()
    if settings_row is None:
        settings_row = HostAlertSettings(host_id=host_id)
        db.add(settings_row)
    settings_row.email_enabled = s.email_enabled
    settings_row.email_recipients = s.email_recipients
    settings_row.min_severity = s.min_severity
    settings_row.notify_resolve = s.notify_resolve
    settings_row.cooldown_min = s.cooldown_min

    # --- rules full-replace ---
    existing_rules = (
        await db.execute(
            select(HostAlertRule).where(HostAlertRule.host_id == host_id)
        )
    ).scalars().all()
    existing_by_type: dict[str, HostAlertRule] = {r.alert_type: r for r in existing_rules}
    incoming_types: set[str] = set()

    for rule in body.rules:
        incoming_types.add(rule.alert_type)
        row = existing_by_type.get(rule.alert_type)
        if row is None:
            row = HostAlertRule(host_id=host_id, alert_type=rule.alert_type, enabled=True)
            db.add(row)
        if rule.enabled is not None:
            row.enabled = rule.enabled
        row.threshold = rule.threshold
        row.warning_threshold = rule.warning_threshold
        row.critical_threshold = rule.critical_threshold
        row.sustain_min = rule.sustain_min

    for atype, row in existing_by_type.items():
        if atype not in incoming_types:
            await db.delete(row)

    await db.commit()

    await log_manager_activity(
        db, actor=admin.username, action="host_alerts_update", status="success",
        detail_key="host.alerts.update",
        detail_params={
            "host_id": host.id,
            "host_name": host.name,
            "rule_count": len(body.rules),
        },
    )

    # Re-read to produce a clean response.
    return await get_host_alerts(host_id, _admin=admin, db=db)  # type: ignore[arg-type]
