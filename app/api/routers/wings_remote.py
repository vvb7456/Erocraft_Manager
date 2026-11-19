"""Wings daemon remote protocol endpoints (``/api/remote/*``).

100% protocol-compatible replacement for Pterodactyl Panel's
``routes/api-remote.php`` (12 endpoints).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import logging
import math
import re
import struct
import time
import uuid as uuid_lib
from collections import deque
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.db import get_db
from app.api.deps.wings_remote_auth import (
    WingsRemoteError,
    remote_validation_error,
    require_wings_node,
)
from app.core.time import utc_naive_now, utc_naive_now_sec
from app.db.models.pterodactyl import (
    ActivityLog,
    ActivityLogSubject,
    Allocation,
    Backup,
    Egg,
    PanelNode,
    PteroServer,
    PteroUser,
    ServerTransfer,
    Subuser,
    UserSshKey,
)
from app.services.pterodactyl_activity import (
    SUBJECT_BACKUP,
    SUBJECT_SERVER,
    SUBJECT_USER,
    get_request_ip,
    pterodactyl_activity_logger,
)
from app.services.wings import wings_service
from app.services.wings_remote_config import build_server_configs_batch

logger = logging.getLogger(__name__)

# Excluded from Manager's ProblemDetails OpenAPI contract because /api/remote/*
# uses Pterodactyl's native {"errors": [...]} envelope.
router = APIRouter(prefix="/remote", tags=["wings_remote"], include_in_schema=False)

# ---------------------------------------------------------------------------
# SFTP anti-brute-force throttle (5 failures / 60s per server|ip)
# ---------------------------------------------------------------------------

SFTP_THROTTLE_MAX_ATTEMPTS = 5
SFTP_THROTTLE_WINDOW_SECONDS = 60.0
_SFTP_THROTTLE_MAX_KEYS = 4096
_sftp_failures: dict[str, deque[float]] = {}


def _extract_client_host(raw: str | None) -> str:
    """Strip source port from Wings conn.RemoteAddr().String() values."""
    text = (raw or "").strip()
    if not text:
        return ""
    host = text
    if text.startswith("["):
        end = text.find("]")
        if end > 1:
            rest = text[end + 1 :]
            if rest == "" or (rest.startswith(":") and rest[1:].isdigit()):
                host = text[1:end]
    elif text.count(":") == 1:
        candidate, port = text.rsplit(":", 1)
        if port.isdigit():
            host = candidate
    if not host:
        return ""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return host


def _sftp_throttle_remaining_seconds(key: str) -> int:
    now = time.monotonic()
    bucket = _sftp_failures.get(key)
    if not bucket:
        return 0
    cutoff = now - SFTP_THROTTLE_WINDOW_SECONDS
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if not bucket:
        _sftp_failures.pop(key, None)
        return 0
    if len(bucket) >= SFTP_THROTTLE_MAX_ATTEMPTS:
        return max(1, math.ceil(bucket[0] + SFTP_THROTTLE_WINDOW_SECONDS - now))
    return 0


def _sftp_throttle_record_failure(key: str) -> None:
    now = time.monotonic()
    if len(_sftp_failures) >= _SFTP_THROTTLE_MAX_KEYS and key not in _sftp_failures:
        cutoff = now - SFTP_THROTTLE_WINDOW_SECONDS
        stale = [k for k, q in _sftp_failures.items() if not q or q[-1] <= cutoff]
        for k in stale:
            _sftp_failures.pop(k, None)
        if len(_sftp_failures) >= _SFTP_THROTTLE_MAX_KEYS:
            _sftp_failures.clear()
    bucket = _sftp_failures.setdefault(key, deque())
    cutoff = now - SFTP_THROTTLE_WINDOW_SECONDS
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    bucket.append(now)


# ---------------------------------------------------------------------------
# SSH public key parsing & SHA-256 fingerprint (matches UserSSHKey.php + phpseclib3)
# ---------------------------------------------------------------------------

_PUBLIC_KEY_MAX_LENGTH = 16384
_PUBLIC_KEY_PREFIXES: tuple[str, ...] = (
    "ssh-rsa ",
    "ssh-ed25519 ",
    "ecdsa-sha2-",
    "sk-ssh-ed25519@openssh.com ",
    "sk-ecdsa-sha2-nistp256@openssh.com ",
    "-----BEGIN PUBLIC KEY-----",
    "-----BEGIN RSA PUBLIC KEY-----",
    "-----BEGIN EC PUBLIC KEY-----",
    "-----BEGIN DSA PUBLIC KEY-----",
)


def _is_supported_public_key_material(raw: str) -> bool:
    if not raw or len(raw) > _PUBLIC_KEY_MAX_LENGTH or "\x00" in raw:
        return False
    return raw.startswith(_PUBLIC_KEY_PREFIXES)


def _openssh_blob_sha256(blob: bytes) -> str:
    return base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def compute_ssh_public_key_fingerprint(raw_key: str) -> str | None:
    """Validate OpenSSH/PEM public key material and return raw base64 SHA-256 fingerprint."""
    material = raw_key.strip()
    if not _is_supported_public_key_material(material):
        return None

    encoded = material.encode("utf-8")
    if material.startswith("-----BEGIN "):
        try:
            pub = serialization.load_pem_public_key(encoded)
            openssh_line = pub.public_bytes(
                serialization.Encoding.OpenSSH,
                serialization.PublicFormat.OpenSSH,
            ).decode("ascii")
            blob = base64.b64decode(openssh_line.split()[1], validate=True)
            return _openssh_blob_sha256(blob)
        except Exception:
            return None

    try:
        pub = serialization.load_ssh_public_key(encoded)
        openssh_line = pub.public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH,
        ).decode("ascii")
        blob = base64.b64decode(openssh_line.split()[1], validate=True)
        return _openssh_blob_sha256(blob)
    except UnsupportedAlgorithm:
        # FIDO2 sk-* keys may not be supported by older cryptography backends;
        # verify the OpenSSH wire-format key-type prefix matches before hashing.
        parts = material.split()
        if len(parts) < 2 or not parts[0].startswith("sk-"):
            return None
        try:
            blob = base64.b64decode(parts[1], validate=True)
            if len(blob) < 4:
                return None
            (type_len,) = struct.unpack(">I", blob[:4])
            if len(blob) < 4 + type_len:
                return None
            wire_type = blob[4 : 4 + type_len].decode("ascii")
            if wire_type != parts[0]:
                return None
            return _openssh_blob_sha256(blob)
        except Exception:
            return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Shared lookup & helper functions
# ---------------------------------------------------------------------------

_FRACTIONAL_TZ_RE = re.compile(r"\.\d+(?=(?:Z|[+-]\d{2}:\d{2})$)")


def _parse_int_query(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_additional_allocations(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[int] = []
    for item in parsed:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


async def _get_server_by_uuid_or_404(db: AsyncSession, server_uuid: str) -> PteroServer:
    server = (
        await db.execute(
            select(PteroServer).where(
                or_(PteroServer.uuid == server_uuid, PteroServer.uuid_short == server_uuid)
            )
        )
    ).scalar_one_or_none()
    if server is None:
        raise WingsRemoteError(404, "RecordNotFoundException", "")
    return server


async def _get_active_transfer(db: AsyncSession, server_id: int) -> ServerTransfer | None:
    return (
        await db.execute(
            select(ServerTransfer)
            .where(ServerTransfer.server_id == server_id, ServerTransfer.successful.is_(None))
            .order_by(ServerTransfer.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _get_backup_by_uuid_or_404(db: AsyncSession, backup_uuid: str) -> Backup:
    model = (
        await db.execute(
            select(Backup).where(Backup.uuid == backup_uuid, Backup.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if model is None:
        raise WingsRemoteError(404, "NotFoundHttpException", "The requested resource does not exist.")
    return model


async def _get_user_server_permissions(
    db: AsyncSession,
    server: PteroServer,
    user: PteroUser,
) -> list[str]:
    if user.root_admin or user.id == server.owner_id:
        perms = ["*"]
        if user.root_admin:
            perms.extend(
                [
                    "admin.websocket.errors",
                    "admin.websocket.install",
                    "admin.websocket.transfer",
                ]
            )
        return perms

    subuser = (
        await db.execute(
            select(Subuser).where(Subuser.server_id == server.id, Subuser.user_id == user.id)
        )
    ).scalar_one_or_none()
    return subuser.permission_list if subuser is not None else []


def _parse_sftp_username(value: str) -> tuple[str, str]:
    # Split from the right so usernames containing dots remain intact.
    if "." in value:
        username, server_ident = value.rsplit(".", 1)
        return username, server_ident
    return "", value


def _parse_rfc3339_to_utc_naive(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    # Strip nanosecond/microsecond precision so Go RFC3339Nano parses cleanly
    # and MySQL TIMESTAMP (seconds precision) does not round up half-seconds.
    normalized = _FRACTIONAL_TZ_RE.sub("", text)
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(microsecond=0)
    return dt.astimezone(UTC).replace(tzinfo=None, microsecond=0)


def _is_valid_uuid(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        uuid_lib.UUID(value)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class InstallationDataIn(BaseModel):
    successful: bool
    reinstall: bool = False


class SftpAuthIn(BaseModel):
    type: Literal["password", "public_key"] | None = None
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    ip: str | None = None
    session_id: str | None = None
    client_version: str | None = None


class BackupRestoreIn(BaseModel):
    successful: bool = False


# ---------------------------------------------------------------------------
# 1. GET /api/remote/servers
# ---------------------------------------------------------------------------


@router.get("/servers")
async def list_remote_servers(
    request: Request,
    page: str | None = None,
    per_page: str | None = None,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Wings boots with page=0; Laravel's LengthAwarePaginator treats page<=0 as page 1.
    parsed_page = _parse_int_query(page, 1)
    current_page = parsed_page if parsed_page >= 1 else 1
    parsed_per_page = _parse_int_query(per_page, 50)
    limit = parsed_per_page if parsed_per_page >= 1 else 50

    total = int(
        (
            await db.execute(
                select(func.count(PteroServer.id)).where(PteroServer.node_id == node.id)
            )
        ).scalar_one()
        or 0
    )
    last_page = max(1, math.ceil(total / limit)) if total > 0 else 1

    offset = (current_page - 1) * limit
    servers = list(
        (
            await db.execute(
                select(PteroServer)
                .where(PteroServer.node_id == node.id)
                .order_by(PteroServer.id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
    )

    data = await build_server_configs_batch(db, servers, include_top_uuid=True)

    from_idx = offset + 1 if data else None
    to_idx = offset + len(data) if data else None
    base_path = str(request.url.replace(query=""))

    return {
        "data": data,
        "links": {
            "first": f"{base_path}?page=1",
            "last": f"{base_path}?page={last_page}",
            "prev": f"{base_path}?page={current_page - 1}" if current_page > 1 else None,
            "next": f"{base_path}?page={current_page + 1}" if current_page < last_page else None,
        },
        "meta": {
            "current_page": current_page,
            "from": from_idx,
            "last_page": last_page,
            "path": base_path,
            "per_page": limit,
            "to": to_idx,
            "total": total,
        },
    }


# ---------------------------------------------------------------------------
# 2. POST /api/remote/servers/reset
# ---------------------------------------------------------------------------


@router.post("/servers/reset", status_code=204)
async def reset_remote_servers_state(
    request: Request,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> Response:
    restoring_servers = list(
        (
            await db.execute(
                select(PteroServer).where(
                    PteroServer.node_id == node.id,
                    PteroServer.status == "restoring_backup",
                )
            )
        ).scalars().all()
    )

    for server in restoring_servers:
        latest_restore_log = (
            await db.execute(
                select(ActivityLog)
                .join(ActivityLogSubject, ActivityLogSubject.activity_log_id == ActivityLog.id)
                .where(
                    ActivityLogSubject.subject_type == SUBJECT_SERVER,
                    ActivityLogSubject.subject_id == server.id,
                    ActivityLog.event == "server:backup.restore-started",
                )
                .order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_restore_log is None:
            continue

        backup_subject = (
            await db.execute(
                select(ActivityLogSubject).where(
                    ActivityLogSubject.activity_log_id == latest_restore_log.id,
                    ActivityLogSubject.subject_type == SUBJECT_BACKUP,
                )
            )
        ).scalar_one_or_none()
        if backup_subject is None:
            continue

        backup = await db.get(Backup, backup_subject.subject_id)
        if backup is None:
            continue

        await pterodactyl_activity_logger.log_server_activity(
            db,
            server=server,
            actor=None,
            event="server:backup.restore-failed",
            properties={"name": backup.name},
            request=request,
            subjects=((SUBJECT_BACKUP, backup.id),),
        )

    await db.execute(
        update(PteroServer)
        .where(
            PteroServer.node_id == node.id,
            PteroServer.status.in_(("installing", "restoring_backup")),
        )
        .values(status=None, updated_at=utc_naive_now())
    )
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 3. GET /api/remote/servers/{uuid}
# ---------------------------------------------------------------------------


@router.get("/servers/{uuid}")
async def get_remote_server(
    uuid: str,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    server = await _get_server_by_uuid_or_404(db, uuid)
    transfer = await _get_active_transfer(db, server.id)

    valid = (
        node.id in (transfer.old_node, transfer.new_node)
        if transfer is not None
        else node.id == server.node_id
    )
    if not valid:
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Requesting node does not have permission to access this server.",
        )

    configs = await build_server_configs_batch(db, [server], include_top_uuid=False)
    return configs[0]


# ---------------------------------------------------------------------------
# 4. GET /api/remote/servers/{uuid}/install
# ---------------------------------------------------------------------------


@router.get("/servers/{uuid}/install")
async def get_remote_server_install(
    uuid: str,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    server = await _get_server_by_uuid_or_404(db, uuid)
    if server.node_id != node.id:
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Requesting node does not have permission to access this server.",
        )

    egg = await db.get(Egg, server.egg_id)
    if egg is None:
        raise WingsRemoteError(500, "HttpException", f"Egg {server.egg_id} missing.")

    parent_egg = (
        await db.get(Egg, egg.copy_script_from) if egg.copy_script_from is not None else None
    )
    return {
        "container_image": egg.resolve_script_container(parent_egg),
        "entrypoint": egg.resolve_script_entry(parent_egg),
        "script": egg.resolve_script_install(parent_egg),
    }


# ---------------------------------------------------------------------------
# 5. POST /api/remote/servers/{uuid}/install
# ---------------------------------------------------------------------------


@router.post("/servers/{uuid}/install", status_code=204)
async def store_remote_server_install(
    uuid: str,
    payload: InstallationDataIn,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> Response:
    server = await _get_server_by_uuid_or_404(db, uuid)
    if server.node_id != node.id:
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Requesting node does not have permission to access this server.",
        )

    new_status: str | None = None
    if not payload.successful:
        new_status = "reinstall_failed" if payload.reinstall else "install_failed"

    if server.status == "suspended":
        new_status = "suspended"

    now = utc_naive_now()
    server.status = new_status
    server.installed_at = now
    server.updated_at = now
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 6. POST /api/remote/sftp/auth
# ---------------------------------------------------------------------------


@router.post("/sftp/auth")
async def authenticate_sftp(
    payload: SftpAuthIn,
    request: Request,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    username, server_ident = _parse_sftp_username(payload.username)
    if not server_ident:
        raise WingsRemoteError(
            400,
            "BadRequestHttpException",
            "No valid server identifier was included in the request.",
        )

    client_ip = _extract_client_host(payload.ip) or get_request_ip(request)
    throttle_key = f"{server_ident.lower()}|{client_ip}"
    retry_after = _sftp_throttle_remaining_seconds(throttle_key)
    if retry_after > 0:
        raise WingsRemoteError(
            429,
            "TooManyRequestsHttpException",
            f"Too many login attempts for this account, please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    user = (
        await db.execute(select(PteroUser).where(PteroUser.username == username))
    ).scalar_one_or_none()
    if user is None:
        _sftp_throttle_record_failure(throttle_key)
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Authorization credentials were not correct, please try again.",
        )

    server = (
        await db.execute(
            select(PteroServer).where(
                or_(PteroServer.uuid == server_ident, PteroServer.uuid_short == server_ident),
                PteroServer.node_id == node.id,
            )
        )
    ).scalar_one_or_none()
    if server is None:
        _sftp_throttle_record_failure(throttle_key)
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Authorization credentials were not correct, please try again.",
        )

    if payload.type != "public_key":
        valid_pwd = await asyncio.to_thread(user.check_password, payload.password)
        if not valid_pwd:
            await pterodactyl_activity_logger.log_account_activity(
                db,
                user=user,
                actor=None,
                event="auth:sftp.fail",
                properties={"method": "password"},
                request=request,
            )
            await db.commit()
            _sftp_throttle_record_failure(throttle_key)
            raise WingsRemoteError(
                403,
                "HttpForbiddenException",
                "Authorization credentials were not correct, please try again.",
            )
    else:
        fingerprint = compute_ssh_public_key_fingerprint(payload.password)
        matched_key = None
        if fingerprint is not None:
            matched_key = (
                await db.execute(
                    select(UserSshKey.id).where(
                        UserSshKey.user_id == user.id,
                        UserSshKey.fingerprint == fingerprint,
                        UserSshKey.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()

        if fingerprint is None or matched_key is None:
            # Matches SftpAuthenticationController.php: only count malformed keys against throttle,
            # because SSH clients offer multiple valid keys sequentially during handshake.
            if fingerprint is None:
                _sftp_throttle_record_failure(throttle_key)
            raise WingsRemoteError(
                403,
                "HttpForbiddenException",
                "Authorization credentials were not correct, please try again.",
            )

    permissions = await _get_user_server_permissions(db, server, user)
    if not user.root_admin and server.owner_id != user.id and "file.sftp" not in permissions:
        await pterodactyl_activity_logger.log_server_activity(
            db,
            server=server,
            actor=user,
            event="server:sftp.denied",
            request=request,
        )
        await db.commit()
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "You do not have permission to access SFTP for this server.",
        )

    active_transfer = await _get_active_transfer(db, server.id)
    if (
        server.status == "suspended"
        or node.maintenance_mode
        or server.status in ("installing", "install_failed", "restoring_backup")
        or active_transfer is not None
    ):
        raise WingsRemoteError(
            409,
            "ServerStateConflictException",
            "This server is currently in a state that prevents access.",
        )

    return {
        "user": user.uuid,
        "server": server.uuid,
        "permissions": permissions,
    }


# ---------------------------------------------------------------------------
# 7. POST /api/remote/activity
# ---------------------------------------------------------------------------


@router.post("/activity", status_code=200)
async def ingest_remote_activity(
    request: Request,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        body = await request.json()
    except Exception:
        raise WingsRemoteError(400, "BadRequestHttpException", "Malformed JSON payload.") from None

    if not isinstance(body, dict):
        raise remote_validation_error([("data", "required", "The data field is required.")])

    raw_data = body.get("data")
    if raw_data is None or (isinstance(raw_data, list) and len(raw_data) == 0):
        raise remote_validation_error([("data", "required", "The data field is required.")])
    if not isinstance(raw_data, list):
        raise remote_validation_error([("data", "array", "The data field must be an array.")])

    validation_errors: list[tuple[str, str, str]] = []
    parsed_items: list[dict[str, Any]] = []

    for idx, item in enumerate(raw_data):
        if not isinstance(item, dict):
            validation_errors.append((f"data.{idx}", "array", f"data.{idx} must be an object."))
            continue

        user_val = item.get("user")
        if user_val == "":
            user_val = None
        if user_val is not None and not _is_valid_uuid(user_val):
            validation_errors.append(
                (f"data.{idx}.user", "uuid", f"data.{idx}.user must be a valid UUID.")
            )

        server_val = item.get("server")
        if not server_val:
            validation_errors.append(
                (f"data.{idx}.server", "required", f"data.{idx}.server is required.")
            )
        elif not _is_valid_uuid(server_val):
            validation_errors.append(
                (f"data.{idx}.server", "uuid", f"data.{idx}.server must be a valid UUID.")
            )

        event_val = item.get("event")
        if not isinstance(event_val, str) or not event_val:
            validation_errors.append(
                (f"data.{idx}.event", "required", f"data.{idx}.event is required.")
            )

        if "metadata" not in item:
            validation_errors.append(
                (f"data.{idx}.metadata", "present", f"data.{idx}.metadata must be present.")
            )
        else:
            meta_val = item.get("metadata")
            if meta_val is not None and not isinstance(meta_val, (dict, list)):
                validation_errors.append(
                    (f"data.{idx}.metadata", "array", f"data.{idx}.metadata must be an array or object.")
                )

        ip_val = item.get("ip")
        if ip_val == "":
            ip_val = None
        if ip_val is not None:
            # Python's ipaddress accepts RFC 4007 IPv6 zone IDs (e.g. fe80::1%eth0),
            # whereas PHP filter_var(FILTER_VALIDATE_IP) and Go net.ParseIP reject them.
            if not isinstance(ip_val, str) or "%" in ip_val:
                validation_errors.append(
                    (f"data.{idx}.ip", "ip", f"data.{idx}.ip must be a valid IP address.")
                )
            else:
                try:
                    ipaddress.ip_address(ip_val)
                except ValueError:
                    validation_errors.append(
                        (f"data.{idx}.ip", "ip", f"data.{idx}.ip must be a valid IP address.")
                    )

        ts_val = item.get("timestamp")
        if not isinstance(ts_val, str) or not ts_val:
            validation_errors.append(
                (f"data.{idx}.timestamp", "required", f"data.{idx}.timestamp is required.")
            )

        parsed_items.append(
            {
                "user": user_val,
                "server": server_val,
                "event": event_val,
                "metadata": item.get("metadata"),
                "ip": ip_val,
                "timestamp": ts_val,
            }
        )

    if validation_errors:
        raise remote_validation_error(validation_errors)

    server_uuids = {item["server"] for item in parsed_items}
    user_uuids = {item["user"] for item in parsed_items if item["user"]}

    servers = (
        await db.execute(
            select(PteroServer).where(
                PteroServer.node_id == node.id,
                PteroServer.uuid.in_(server_uuids),
            )
        )
    ).scalars().all()
    servers_by_uuid = {s.uuid: s for s in servers}

    users_by_uuid: dict[str, PteroUser] = {}
    if user_uuids:
        users = (
            await db.execute(select(PteroUser).where(PteroUser.uuid.in_(user_uuids)))
        ).scalars().all()
        users_by_uuid = {u.uuid: u for u in users}

    pending_entries: list[tuple[ActivityLog, int]] = []
    for item in parsed_items:
        server = servers_by_uuid.get(item["server"])
        if server is None or not item["event"].startswith("server:"):
            continue

        metadata = item["metadata"]
        parsed_ts = _parse_rfc3339_to_utc_naive(item["timestamp"])
        if parsed_ts is None:
            logger.warning("Unparseable Wings activity timestamp: %r", item["timestamp"])
            parsed_ts = utc_naive_now_sec()
            if isinstance(metadata, dict):
                metadata = {**metadata, "original_timestamp": item["timestamp"]}
            else:
                metadata = {"original_timestamp": item["timestamp"]}

        actor = users_by_uuid.get(item["user"]) if item["user"] else None
        props = metadata if metadata is not None else []

        log_row = ActivityLog(
            ip=item["ip"] or "127.0.0.1",
            event=item["event"],
            properties=json.dumps(props, ensure_ascii=False, separators=(",", ":")),
            timestamp=parsed_ts,
            actor_type=SUBJECT_USER if actor is not None else None,
            actor_id=actor.id if actor is not None else None,
        )
        db.add(log_row)
        pending_entries.append((log_row, server.id))

    if pending_entries:
        await db.flush()
        db.add_all(
            [
                ActivityLogSubject(
                    activity_log_id=log_row.id,
                    subject_type=SUBJECT_SERVER,
                    subject_id=server_id,
                )
                for log_row, server_id in pending_entries
            ]
        )
        await db.commit()

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# 8. POST /api/remote/servers/{uuid}/transfer/failure
# ---------------------------------------------------------------------------


@router.post("/servers/{uuid}/transfer/failure", status_code=204)
async def report_transfer_failure(
    uuid: str,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> Response:
    server = await _get_server_by_uuid_or_404(db, uuid)
    transfer = await _get_active_transfer(db, server.id)
    if transfer is None:
        raise WingsRemoteError(409, "ConflictHttpException", "Server is not being transferred.")

    if node.id not in (transfer.old_node, transfer.new_node):
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Requesting node does not have permission to access this server.",
        )

    now = utc_naive_now()
    transfer.successful = False
    transfer.updated_at = now
    alloc_ids = [transfer.new_allocation, *_parse_additional_allocations(transfer.new_additional_allocations)]
    await db.execute(
        update(Allocation).where(Allocation.id.in_(alloc_ids)).values(server_id=None, updated_at=now)
    )
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 9. POST /api/remote/servers/{uuid}/transfer/success
# ---------------------------------------------------------------------------


@router.post("/servers/{uuid}/transfer/success", status_code=204)
async def report_transfer_success(
    uuid: str,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> Response:
    server = await _get_server_by_uuid_or_404(db, uuid)
    transfer = await _get_active_transfer(db, server.id)
    if transfer is None:
        raise WingsRemoteError(409, "ConflictHttpException", "Server is not being transferred.")

    if node.id != transfer.new_node:
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Requesting node does not have permission to access this server.",
        )

    old_node_id = transfer.old_node
    now = utc_naive_now()
    old_alloc_ids = [
        transfer.old_allocation,
        *_parse_additional_allocations(transfer.old_additional_allocations),
    ]
    await db.execute(
        update(Allocation).where(Allocation.id.in_(old_alloc_ids)).values(server_id=None, updated_at=now)
    )
    server.allocation_id = transfer.new_allocation
    server.node_id = transfer.new_node
    server.updated_at = now
    transfer.successful = True
    transfer.updated_at = now
    await db.commit()

    # Best-effort cleanup of the old container on the source node (matches PHP).
    try:
        await wings_service.delete_server(db, old_node_id, server.uuid)
    except Exception:
        logger.warning(
            "Failed to delete transferred server %s from old node %s (transfer_id=%s)",
            server.uuid,
            old_node_id,
            transfer.id,
            exc_info=True,
        )

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 10. GET /api/remote/backups/{backup}
# ---------------------------------------------------------------------------


@router.get("/backups/{backup}")
async def get_backup_remote_upload(
    backup: str,
    size: str | None = None,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    parsed_size = _parse_int_query(size, 0)
    if parsed_size <= 0:
        raise WingsRemoteError(
            400,
            "BadRequestHttpException",
            'A non-empty "size" query parameter must be provided.',
        )

    model = await _get_backup_by_uuid_or_404(db, backup)
    server = await db.get(PteroServer, model.server_id)
    if server is None or server.node_id != node.id:
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Requesting node does not have permission to access this server.",
        )

    if model.completed_at is not None:
        raise WingsRemoteError(
            409,
            "ConflictHttpException",
            "This backup is already in a completed state.",
        )

    # S3 remote backup adapter is not enabled in Manager; only local Wings backups are used.
    raise WingsRemoteError(
        400,
        "BadRequestHttpException",
        "The configured backup adapter is not an S3 compatible adapter.",
    )


# ---------------------------------------------------------------------------
# 11. POST /api/remote/backups/{backup}
# ---------------------------------------------------------------------------


@router.post("/backups/{backup}", status_code=204)
async def report_backup_complete(
    backup: str,
    request: Request,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        body = await request.json()
    except Exception:
        raise WingsRemoteError(400, "BadRequestHttpException", "Malformed JSON payload.") from None

    if not isinstance(body, dict):
        raise remote_validation_error([("successful", "required", "The successful field is required.")])

    errors: list[tuple[str, str, str]] = []
    if "successful" not in body or not isinstance(body["successful"], bool):
        errors.append(("successful", "required" if "successful" not in body else "boolean", "The successful field must be a boolean."))
        raise remote_validation_error(errors)

    successful: bool = body["successful"]
    checksum = body.get("checksum")
    checksum_type = body.get("checksum_type")
    size_val = body.get("size")
    parts = body.get("parts")

    if successful:
        if not isinstance(checksum, str) or not checksum:
            errors.append(("checksum", "required_if", "The checksum field is required when successful is true."))
        if not isinstance(checksum_type, str) or not checksum_type:
            errors.append(("checksum_type", "required_if", "The checksum_type field is required when successful is true."))
        if size_val is None or isinstance(size_val, bool) or not isinstance(size_val, (int, float)):
            errors.append(("size", "required_if", "The size field is required when successful is true."))
    if parts is not None:
        if not isinstance(parts, list):
            errors.append(("parts", "array", "The parts field must be an array."))
        else:
            for idx, part in enumerate(parts):
                if not isinstance(part, dict) or not isinstance(part.get("etag"), str) or not part.get("etag"):
                    errors.append((f"parts.{idx}.etag", "required", f"parts.{idx}.etag is required."))
                pn = part.get("part_number") if isinstance(part, dict) else None
                if pn is None or isinstance(pn, bool) or not isinstance(pn, (int, float)):
                    errors.append((f"parts.{idx}.part_number", "required", f"parts.{idx}.part_number is required."))

    if errors:
        raise remote_validation_error(errors)

    model = await _get_backup_by_uuid_or_404(db, backup)
    server = await db.get(PteroServer, model.server_id)
    if server is None or server.node_id != node.id:
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Requesting node does not have permission to access this server.",
        )

    if model.is_successful:
        raise WingsRemoteError(
            400,
            "BadRequestHttpException",
            "Cannot update the status of a backup that is already marked as completed.",
        )

    now = utc_naive_now()
    model.is_successful = successful
    model.is_locked = bool(model.is_locked) if successful else False
    model.checksum = f"{checksum_type}:{checksum}" if successful else None
    model.bytes = int(size_val) if successful and size_val is not None else 0
    model.completed_at = now
    model.updated_at = now

    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=None,
        event="server:backup.complete" if successful else "server:backup.fail",
        properties={"name": model.name},
        request=request,
        subjects=((SUBJECT_BACKUP, model.id),),
    )
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 12. POST /api/remote/backups/{backup}/restore
# ---------------------------------------------------------------------------


@router.post("/backups/{backup}/restore", status_code=204)
async def report_backup_restore(
    backup: str,
    payload: BackupRestoreIn,
    request: Request,
    node: PanelNode = Depends(require_wings_node),
    db: AsyncSession = Depends(get_db),
) -> Response:
    model = await _get_backup_by_uuid_or_404(db, backup)
    server = await db.get(PteroServer, model.server_id)
    if server is None or server.node_id != node.id:
        raise WingsRemoteError(
            403,
            "HttpForbiddenException",
            "Requesting node does not have permission to access this server.",
        )

    server.status = None
    server.updated_at = utc_naive_now()
    await pterodactyl_activity_logger.log_server_activity(
        db,
        server=server,
        actor=None,
        event="server:backup.restore-complete" if payload.successful else "server:backup.restore-failed",
        properties={"name": model.name},
        request=request,
        subjects=((SUBJECT_BACKUP, model.id),),
    )
    await db.commit()
    return Response(status_code=204)
