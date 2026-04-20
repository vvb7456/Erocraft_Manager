"""User-facing server routes backed by MySQL reads and direct Wings access."""

from __future__ import annotations

import base64
import json
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db
from app.api.deps.ownership import get_owned_server
from app.core.runtime_settings import AUTOMATION_SPECS
from app.core.settings_store import get_settings_store
from app.core.time import local_today
from app.db.models.pterodactyl import PteroServer, PteroUser
from app.db.repositories.servers import server_repository
from app.schemas.user_servers import (
    PowerActionRequest,
    ReinstallRequest,
    STDefaultPasswordRequest,
    STDefaultPasswordResponse,
    ServerResourcesResponse,
    StartupVariableItem,
    StartupVariableUpdate,
    UserServerDetail,
    UserServerItem,
    WingsTokenResponse,
)
from app.services.pterodactyl import PterodactylServiceError, pterodactyl_service
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
        },
        expirationDate=expiration_date.isoformat() if expiration_date else None,
        daysLeft=days_left,
        address=address,
    )


@router.get("/servers", response_model=list[UserServerItem])
async def list_user_servers(
    current_user: PteroUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserServerItem]:
    today = await _today(db)
    servers = await server_repository.list_for_owner(db, current_user.id)
    return [_serialize_server(server, today) for server in servers]


@router.get("/servers/{server_id}", response_model=UserServerDetail)
async def get_user_server_detail(
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> UserServerDetail:
    today = await _today(db)
    item = _serialize_server(server, today)
    return UserServerDetail.model_validate(item.model_dump())


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
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if server.is_suspended:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Server is suspended")

    try:
        await wings_service.send_power_action(db, server.node_id, server.uuid, payload.action)
    except WingsServiceError as exc:
        raise translate_wings_error(exc) from exc

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
    server: PteroServer = Depends(get_owned_server),
    db: AsyncSession = Depends(get_db),
) -> Response:
    for env_var, value in payload.variables.items():
        await server_repository.update_startup_variable(
            db,
            server_id=server.id,
            egg_id=server.egg_id,
            env_variable=env_var,
            value=value,
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/{server_id}/reinstall", status_code=status.HTTP_204_NO_CONTENT)
async def reinstall_user_server(
    payload: ReinstallRequest,
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
        await pterodactyl_service.reinstall_server(server.id)
    except PterodactylServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if payload.force:
        await server_repository.update_startup_variable(
            db,
            server_id=server.id,
            egg_id=server.egg_id,
            env_variable="FORCE_REINSTALL",
            value="false",
        )
        await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    return Response(status_code=status.HTTP_204_NO_CONTENT)
