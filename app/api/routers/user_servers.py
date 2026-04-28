"""User-facing server routes backed by MySQL reads and direct Wings access."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.api.deps.ownership import get_owned_server
from app.config.egg_credentials import required_credential_vars
from app.core.runtime_settings import AUTOMATION_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import local_today
from app.db.models.pterodactyl import ActivityLog, ActivityLogSubject, PteroServer, PteroUser
from app.db.repositories.servers import server_repository
from app.schemas.user_servers import (
    PowerActionRequest,
    ReinstallRequest,
    STDefaultPasswordRequest,
    STDefaultPasswordResponse,
    ServerResourcesResponse,
    StartupVariableItem,
    StartupVariableUpdate,
    UserActivityActor,
    UserActivityLogItem,
    UserActivityLogsResponse,
    UserActivityReportRequest,
    UserServerDetail,
    UserServerItem,
    WingsTokenResponse,
)
from app.services.pterodactyl_activity import (
    PTERODACTYL_DISABLED_ACTIVITY_EVENTS,
    SUBJECT_EGG_VARIABLE,
    decode_activity_properties,
    pterodactyl_activity_logger,
)
from app.services import server_lifecycle
from app.services.server_lifecycle import LifecycleError
from app.services.wings import WingsServiceError, wings_service
from app.api.utils.wings_errors import translate_wings_error


router = APIRouter(prefix="/user", tags=["user_servers"])


async def _today(db: AsyncSession) -> date:
    timezone_name = await get_settings_store().get(
        db,
        "TIMEZONE",
        AUTOMATION_SPECS["TIMEZONE"].default_value(),
    )
    return local_today(str(timezone_name))


def _serialize_server(server: PteroServer, today: date) -> UserServerItem:
    expiration_date = server.expiration_date
    days_left = (expiration_date - today).days if expiration_date is not None else None
    allocation_ip = server.allocation.ip_alias or server.allocation.ip if server.allocation else None
    allocation_port = server.allocation.port if server.allocation else None
    node_fqdn = server.node.fqdn if server.node else None
    node_name = server.node.name if server.node else None
    node_sftp_port = server.node.daemon_sftp if server.node else None
    address = f"{node_fqdn}:{allocation_port}" if node_fqdn and allocation_port is not None else None

    return UserServerItem(
        id=server.id,
        uuid=server.uuid,
        uuidShort=server.uuid_short,
        name=server.name,
        description=server.description or None,
        status=server.status,
        isInstalling=server.status == "installing" or server.installed_at is None,
        isInstalled=server.installed_at is not None and server.status != "installing",
        isSuspended=server.is_suspended,
        nodeId=server.node_id,
        eggId=server.egg_id,
        eggName=server.egg.name if server.egg else "Unknown",
        limits={
            "memory": server.memory,
            "disk": server.disk,
            "cpu": server.cpu,
        },
        allocation={
            "ip": allocation_ip,
            "port": allocation_port,
        },
        node={
            "fqdn": node_fqdn,
            "name": node_name,
            "sftpPort": node_sftp_port,
        },
        expirationDate=expiration_date.isoformat() if expiration_date else None,
        daysLeft=days_left,
        address=address,
    )


def _validate_activity_report(payload: UserActivityReportRequest) -> dict[str, str]:
    props = payload.properties
    if payload.event == "server:console.command":
        command = str(props.get("command") or "").strip()
        if not command:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="activity.command_required")
        return {"command": command}

    if payload.event == "server:file.uploaded":
        directory = str(props.get("directory") or "").strip() or "/"
        file = str(props.get("file") or "").strip()
        if not file:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="activity.file_required")
        return {"directory": directory, "file": file}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="activity.event_not_allowed")


@router.get("/servers", response_model=list[UserServerItem])
async def list_user_servers(
    scope: str = Query("owner"),
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserServerItem]:
    today = await _today(db)
    if scope == "all" and bool(current_user.root_admin):
        servers = await server_repository.list_for_admin(db)
    else:
        servers = await server_repository.list_for_owner(db, current_user.id)
    return [_serialize_server(server, today) for server in servers]


@router.get("/servers/{server_id}", response_model=UserServerDetail)
async def get_user_server_detail(
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> UserServerDetail:
    today = await _today(db)
    item = _serialize_server(server, today)

    # Tunnel info — best-effort lookup; failures should not break the
    # core detail response (the Network tab will surface them on its own).
    tunnel_info = None
    host_tunnel_ready = False
    try:
        from app.services import host_registry
        from app.db.models.manager import ManagerHostTunnel
        from app.services.tunnel_manager import dispatcher as tm_dispatcher

        host = await host_registry.get_host_by_node_id(db, server.node_id)
        if host is not None:
            res = await db.execute(
                select(ManagerHostTunnel).where(
                    ManagerHostTunnel.host_id == host.id,
                )
            )
            ht = res.scalar_one_or_none()
            host_tunnel_ready = bool(ht and ht.cf_tunnel_id)
            st = await tm_dispatcher.get_server_tunnel(db, server.id)
            if st is not None and st.status != "deleted":
                tunnel_info = {
                    "status": st.status,
                    "hostname": st.hostname,
                    "customSubdomain": st.custom_subdomain,
                    "lastError": st.last_error,
                }
    except Exception:  # noqa: BLE001
        pass

    payload = item.model_dump()
    payload["tunnel"] = tunnel_info
    payload["hostTunnelReady"] = host_tunnel_ready
    return UserServerDetail.model_validate(payload)


@router.get("/servers/{server_id}/resources", response_model=ServerResourcesResponse)
async def get_user_server_resources(
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> ServerResourcesResponse:
    try:
        data = await wings_service.get_server(db, server.node_id, server.uuid)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc

    return ServerResourcesResponse(
        state=str(data.get("state") or "offline"),
        isSuspended=bool(data.get("is_suspended", server.is_suspended)),
        resources=data.get("utilization") or data.get("resources") or {},
    )


@router.post("/servers/{server_id}/power", status_code=status.HTTP_204_NO_CONTENT)
async def send_user_server_power_action(
    payload: PowerActionRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if server.is_suspended:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Server is suspended")

    # For 'start' / 'restart', enforce per-egg credential vars (e.g.
    # SillyTavern PASSWORD, USERNAME). The frontend's confirm dialog talks
    # about specific missing fields, so we collect every missing key and
    # surface them as a structured detail: { code, missing: [...] }. The
    # global exception handler echoes detail straight into the JSON body,
    # so the client receives `{ error: { code, missing } }`.
    if payload.action in ("start", "restart"):
        cred_keys = required_credential_vars(server.egg.name if server.egg else None)
        if cred_keys:
            rows = await server_repository.list_startup_variables(
                db, server_id=server.id, egg_id=server.egg_id,
            )
            wanted = set(cred_keys)
            present: dict[str, str | None] = {}
            for variable, value in rows:
                if variable.env_variable in wanted:
                    effective = value if value is not None else variable.default_value
                    present[variable.env_variable] = effective
            missing = [
                key for key in cred_keys
                if not (present.get(key) or "").strip()
            ]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "server.startup_credentials_required",
                        "missing": missing,
                    },
                )

    try:
        await wings_service.send_power_action(db, server.node_id, server.uuid, payload.action)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc

    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event=f"server:power.{payload.action}",
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/servers/{server_id}/wings-token", response_model=WingsTokenResponse)
async def get_user_server_wings_token(
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> WingsTokenResponse:
    """Unified Wings token for WS console + file upload."""
    if server.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="server_suspended",
        )
    try:
        data = await wings_service.create_wings_token(
            db, server.node_id, server.uuid, current_user.uuid,
        )
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc

    return WingsTokenResponse(**data)


@router.get("/servers/{server_id}/startup", response_model=list[StartupVariableItem])
async def list_user_server_startup_variables(
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> list[StartupVariableItem]:
    rows = await server_repository.list_startup_variables(db, server_id=server.id, egg_id=server.egg_id)
    variables: list[StartupVariableItem] = []
    for variable, value in rows:
        if not variable.user_viewable:
            continue
        variables.append(
            StartupVariableItem(
                envVariable=variable.env_variable,
                name=variable.name,
                description=variable.description or "",
                defaultValue=variable.default_value,
                value=value if value is not None else variable.default_value,
                isEditable=bool(variable.user_editable),
                rules=variable.rules or "",
            )
        )
    return variables


@router.put("/servers/{server_id}/startup", status_code=status.HTTP_204_NO_CONTENT)
async def update_user_server_startup(
    payload: StartupVariableUpdate,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    batch = str(uuid.uuid4()) if len(payload.variables) > 1 else None
    for env_var, value in payload.variables.items():
        result = await server_repository.update_startup_variable(
            db,
            server_id=server.id,
            egg_id=server.egg_id,
            env_variable=env_var,
            value=value,
        )
        if result is None or not result.changed:
            continue
        await pterodactyl_activity_logger.log_server_activity(
            db,
            server=server,
            actor=current_user,
            event="server:startup.edit",
            properties={
                "variable": result.variable.env_variable,
                "old": result.old_value,
                "new": result.new_value,
            },
            request=request,
            subjects=[(SUBJECT_EGG_VARIABLE, result.variable.id)],
            batch=batch,
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/{server_id}/reinstall", status_code=status.HTTP_204_NO_CONTENT)
async def reinstall_user_server(
    payload: ReinstallRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if server.is_suspended:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Server is suspended")

    if payload.force:
        await server_repository.update_startup_variable(
            db,
            server_id=server.id,
            egg_id=server.egg_id,
            env_variable="FORCE_REINSTALL",
            value="true",
        )
        await db.commit()

    try:
        try:
            await server_lifecycle.reinstall_server(db, server.id)
        except LifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        # Always reset FORCE_REINSTALL — without try/finally a Wings outage
        # leaves it set to "true" and every subsequent reinstall (even from
        # the UI's normal "reinstall" path) becomes a forced wipe. (Audit H2.)
        if payload.force:
            try:
                await server_repository.update_startup_variable(
                    db,
                    server_id=server.id,
                    egg_id=server.egg_id,
                    env_variable="FORCE_REINSTALL",
                    value="false",
                )
                await db.commit()
            except Exception:  # noqa: BLE001
                # Reset failure must not mask the original exception. Best-effort.
                await db.rollback()

    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:reinstall",
        request=request,
    )
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/{server_id}/activity", status_code=status.HTTP_204_NO_CONTENT)
async def report_user_server_activity(
    payload: UserActivityReportRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    properties = _validate_activity_report(payload)
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event=payload.event,
        properties=properties,
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/servers/{server_id}/activity", response_model=UserActivityLogsResponse)
async def list_user_server_activity(
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    event: str | None = Query(default=None, min_length=1),
    include_disabled: bool = Query(default=False),
) -> UserActivityLogsResponse:
    filters = [
        ActivityLogSubject.subject_type == "server",
        ActivityLogSubject.subject_id == server.id,
    ]
    if event:
        event_parts = [e.strip() for e in event.split(",") if e.strip()]
        if len(event_parts) == 1:
            filters.append(ActivityLog.event.like(f"%{event_parts[0]}%"))
        elif event_parts:
            filters.append(or_(*(ActivityLog.event.like(f"%{ep}%") for ep in event_parts)))
    if not include_disabled:
        filters.append(ActivityLog.event.notin_(PTERODACTYL_DISABLED_ACTIVITY_EVENTS))

    count_result = await db.execute(
        select(func.count(ActivityLog.id))
        .join(ActivityLogSubject, ActivityLogSubject.activity_log_id == ActivityLog.id)
        .where(*filters)
    )
    total = int(count_result.scalar_one() or 0)

    result = await db.execute(
        select(ActivityLog, PteroUser)
        .join(ActivityLogSubject, ActivityLogSubject.activity_log_id == ActivityLog.id)
        .outerjoin(
            PteroUser,
            and_(
                ActivityLog.actor_type == "user",
                ActivityLog.actor_id == PteroUser.id,
            ),
        )
        .where(*filters)
        .order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )

    logs: list[UserActivityLogItem] = []
    for activity, actor in result.all():
        logs.append(
            UserActivityLogItem(
                id=activity.id,
                batch=activity.batch,
                event=activity.event,
                ip=activity.ip,
                description=activity.description,
                actorType=activity.actor_type,
                actorId=activity.actor_id,
                apiKeyId=activity.api_key_id,
                properties=decode_activity_properties(activity.properties),
                timestamp=activity.timestamp,
                actor=UserActivityActor(
                    id=actor.id,
                    uuid=actor.uuid,
                    username=actor.username,
                    email=actor.email,
                ) if actor is not None else None,
            )
        )

    return UserActivityLogsResponse(
        logs=logs,
        total=total,
        page=page,
        perPage=per_page,
    )


_ST_DEFAULT_USER_KEY = "user:default-user"


def _st_storage_filename() -> str:
    import hashlib
    return hashlib.sha256(_ST_DEFAULT_USER_KEY.encode()).hexdigest()


def _hash_st_password(password: str) -> tuple[str, str]:
    """Generate scrypt hash + salt compatible with SillyTavern."""
    import hashlib
    import os
    import unicodedata

    salt = base64.b64encode(os.urandom(16)).decode("ascii")
    normalized = unicodedata.normalize("NFC", password)
    derived = hashlib.scrypt(
        normalized.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384, r=8, p=1, dklen=64,
    )
    password_hash = base64.b64encode(derived).decode("ascii")
    return password_hash, salt


@router.get("/servers/{server_id}/st-default-password", response_model=STDefaultPasswordResponse)
async def get_st_default_password_status(
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> STDefaultPasswordResponse:
    filename = _st_storage_filename()
    try:
        content = await wings_service.get_file_contents(
            db, server.node_id, server.uuid,
            f"/data/_storage/{filename}",
        )
        data = json.loads(content)
        has_password = bool(data.get("value", {}).get("password", ""))
        return STDefaultPasswordResponse(hasPassword=has_password)
    except (WingsServiceError, json.JSONDecodeError, KeyError):
        return STDefaultPasswordResponse(hasPassword=False)


@router.put("/servers/{server_id}/st-default-password", status_code=status.HTTP_204_NO_CONTENT)
async def set_st_default_password(
    payload: STDefaultPasswordRequest,
    request: Request,
    current_user: PteroUser = Depends(get_current_user),
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    filename = _st_storage_filename()
    file_path = f"/data/_storage/{filename}"

    try:
        content = await wings_service.get_file_contents(
            db, server.node_id, server.uuid, file_path,
        )
        data = json.loads(content)
    except (WingsServiceError, json.JSONDecodeError):
        data = {
            "key": _ST_DEFAULT_USER_KEY,
            "value": {
                "handle": "default-user",
                "name": "User",
                "created": int(time.time() * 1000),
                "password": "",
                "admin": True,
                "enabled": True,
                "salt": "",
            },
        }

    if payload.password:
        pw_hash, salt = _hash_st_password(payload.password)
        data["value"]["password"] = pw_hash
        data["value"]["salt"] = salt
    else:
        data["value"]["password"] = ""
        data["value"]["salt"] = ""

    try:
        await wings_service.write_file(
            db, server.node_id, server.uuid,
            file_path,
            json.dumps(data, ensure_ascii=False),
        )
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=current_user,
        event="server:file.write",
        properties={"file": file_path},
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
