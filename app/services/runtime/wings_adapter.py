from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol, runtime_checkable

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.node_crypto import NodeTokenCryptoError, decrypt_node_token
from app.db.models.pterodactyl import PanelNode
from app.services.runtime.errors import (
    RuntimeConflictError,
    RuntimeError,
    RuntimeNotFoundError,
    RuntimeTimeoutError,
    RuntimeUnreachableError,
)
from app.services.runtime.reinstall_tokens import (
    issue_force_reinstall_token,
    revoke_force_reinstall_token,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeNodeEndpoint:
    fqdn: str
    scheme: str
    port: int
    token: str
    upload_size: int  # MiB (nodes.upload_size)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.fqdn}:{self.port}"


@dataclass(slots=True)
class _CachedNodeInfo:
    info: RuntimeNodeEndpoint
    expires_at: float


@runtime_checkable
class InstanceRuntimeAdapter(Protocol):
    async def create_server(self, db: AsyncSession, node_id: int, server_uuid: str, *, start_on_completion: bool = False) -> None: ...
    async def sync_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> None: ...
    async def reinstall_server(self, db: AsyncSession, node_id: int, server_uuid: str, *, force: bool = False) -> None: ...
    async def delete_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> None: ...
    async def delete_backup(self, db: AsyncSession, node_id: int, server_uuid: str, backup_uuid: str) -> None: ...
    async def get_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> dict[str, Any]: ...
    async def deauthorize_user(self, db: AsyncSession, node_id: int, user_uuid: str, *, server_uuids: list[str] | None = None) -> None: ...


def _raise_for_status(response: httpx.Response, *, fallback: str | None = None) -> NoReturn:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            detail = str(body["error"])
    except Exception:
        pass
    if not detail:
        detail = fallback or response.text.strip() or f"HTTP {response.status_code}"
    code = response.status_code
    if code == 404:
        raise RuntimeNotFoundError(detail, status_code=404)
    if code == 409:
        raise RuntimeConflictError(detail, status_code=409)
    if code in (408, 504):
        raise RuntimeTimeoutError(detail, status_code=code)
    raise RuntimeError(detail, status_code=code)


def _raise_for_transport_error(exc: httpx.HTTPError) -> NoReturn:
    if isinstance(exc, httpx.TimeoutException):
        raise RuntimeTimeoutError(f"Wings connection failed: {exc!r}") from exc
    raise RuntimeUnreachableError(f"Wings connection failed: {exc!r}") from exc


class WingsRuntimeAdapter:
    def __init__(self, cache_ttl_seconds: float = 60.0) -> None:
        self._cache_ttl_seconds = cache_ttl_seconds
        self._node_cache: dict[int, _CachedNodeInfo] = {}

    def clear_cache(self) -> None:
        self._node_cache.clear()
        from app.api.deps.wings_remote_auth import clear_remote_auth_cache

        clear_remote_auth_cache()

    async def _node_info(self, db: AsyncSession, node_id: int) -> RuntimeNodeEndpoint:
        now = time.monotonic()
        cached = self._node_cache.get(node_id)
        if cached and cached.expires_at > now:
            return cached.info
        node = await db.get(PanelNode, node_id)
        if node is None:
            raise RuntimeError(f"节点 {node_id} 不存在")
        try:
            token = decrypt_node_token(node.daemon_token)
        except NodeTokenCryptoError as exc:
            raise RuntimeError(str(exc)) from exc
        info = RuntimeNodeEndpoint(
            fqdn=node.fqdn,
            scheme=node.scheme,
            port=node.daemon_listen,
            token=token,
            upload_size=node.upload_size,
        )
        self._node_cache[node_id] = _CachedNodeInfo(info=info, expires_at=now + self._cache_ttl_seconds)
        return info

    async def _send(
        self,
        method: str,
        url: str,
        *,
        bearer: str,
        json_body: dict[str, Any] | list[Any] | None = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        expected_statuses: tuple[int, ...] = (200,),
        timeout: float = 20.0,
        error_fallback: str | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        elif json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.request(
                    method, url, headers=headers, json=json_body, params=params, content=content
                )
        except httpx.HTTPError as exc:
            _raise_for_transport_error(exc)
        if response.status_code not in expected_statuses:
            _raise_for_status(response, fallback=error_fallback)
        return response

    async def _request(
        self,
        db: AsyncSession,
        node_id: int,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | list[Any] | None = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        expected_statuses: tuple[int, ...] = (200,),
        timeout: float = 20.0,
    ) -> httpx.Response:
        node = await self._node_info(db, node_id)
        return await self._send(
            method,
            f"{node.base_url}/api/servers/{path.lstrip('/')}",
            bearer=node.token,
            json_body=json_body,
            params=params,
            content=content,
            content_type=content_type,
            expected_statuses=expected_statuses,
            timeout=timeout,
        )

    async def get_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> dict[str, Any]:
        return (await self._request(db, node_id, "GET", server_uuid)).json()

    async def post_node_update(
        self,
        db: AsyncSession,
        node_id: int,
        payload: dict[str, Any],
        *,
        explicit_token: str | None = None,
        explicit_base_url: str | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        # explicit_token/explicit_base_url 支持令牌轮换与端点迁移时仍用旧凭据/旧地址推新配置。
        if explicit_base_url is not None and explicit_token is not None:
            base_url, bearer = explicit_base_url, explicit_token
        else:
            node = await self._node_info(db, node_id)
            base_url = explicit_base_url if explicit_base_url is not None else node.base_url
            bearer = explicit_token if explicit_token is not None else node.token
        response = await self._send(
            "POST",
            f"{base_url}/api/update",
            bearer=bearer,
            json_body=payload,
            expected_statuses=(200, 204),
            timeout=timeout,
        )
        # 204 或空体等价 applied=True；200 非空不可解析时必须报错，避免轮换凭据误把反代错误页当成功。
        if response.status_code == 204 or not response.content:
            return {"applied": True}
        try:
            return response.json()
        except ValueError as exc:
            logger.warning(
                "wings POST /api/update returned 200 with unparseable body (node_id=%s, len=%s): %s",
                node_id, len(response.content or b""), (response.text or "")[:200],
            )
            raise RuntimeError(
                f"wings returned 200 with unparseable body (len={len(response.content or b'')})",
                status_code=response.status_code,
            ) from exc

    async def create_server(
        self, db: AsyncSession, node_id: int, server_uuid: str, *, start_on_completion: bool = False
    ) -> None:
        node = await self._node_info(db, node_id)
        body: dict[str, Any] = {"uuid": server_uuid}
        if start_on_completion:
            body["start_on_completion"] = True
        await self._send(
            "POST", f"{node.base_url}/api/servers", bearer=node.token, json_body=body, expected_statuses=(200, 202, 204)
        )

    async def sync_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> None:
        await self._request(db, node_id, "POST", f"{server_uuid}/sync", expected_statuses=(200, 202, 204))

    async def reinstall_server(
        self, db: AsyncSession, node_id: int, server_uuid: str, *, force: bool = False
    ) -> None:
        force_token = issue_force_reinstall_token(server_uuid) if force else None
        if not force:
            revoke_force_reinstall_token(server_uuid)
        try:
            await self._request(db, node_id, "POST", f"{server_uuid}/reinstall", expected_statuses=(200, 202, 204))
        except Exception:
            if force_token is not None:
                revoke_force_reinstall_token(server_uuid, token=force_token)
            raise

    async def deauthorize_user(
        self, db: AsyncSession, node_id: int, user_uuid: str, *, server_uuids: list[str] | None = None
    ) -> None:
        node = await self._node_info(db, node_id)
        body: dict[str, Any] = {"user": user_uuid}
        if server_uuids is not None:
            body["servers"] = server_uuids
        await self._send(
            "POST", f"{node.base_url}/api/deauthorize-user",
            bearer=node.token, json_body=body, expected_statuses=(200, 202, 204), timeout=10.0,
        )

    async def delete_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> None:
        try:
            await self._request(db, node_id, "DELETE", server_uuid, expected_statuses=(204, 404))
        except RuntimeError as exc:
            if isinstance(exc, RuntimeNotFoundError) or exc.status_code == 404:
                return
            raise

    async def delete_backup(
        self, db: AsyncSession, node_id: int, server_uuid: str, backup_uuid: str
    ) -> None:
        try:
            await self._request(db, node_id, "DELETE", f"{server_uuid}/backup/{backup_uuid}", expected_statuses=(204, 404))
        except RuntimeError as exc:
            if isinstance(exc, RuntimeNotFoundError) or exc.status_code == 404:
                return
            raise

    async def send_power_action(self, db: AsyncSession, node_id: int, server_uuid: str, action: str) -> None:
        await self._request(
            db, node_id, "POST", f"{server_uuid}/power", json_body={"action": action}, expected_statuses=(202, 204)
        )

    async def list_files(self, db: AsyncSession, node_id: int, server_uuid: str, directory: str = "/") -> list[dict[str, Any]]:
        return (await self._request(db, node_id, "GET", f"{server_uuid}/files/list-directory", params={"directory": directory})).json()

    async def get_file_contents(self, db: AsyncSession, node_id: int, server_uuid: str, file_path: str) -> str:
        return (await self._request(db, node_id, "GET", f"{server_uuid}/files/contents", params={"file": file_path})).text

    async def write_file(self, db: AsyncSession, node_id: int, server_uuid: str, file_path: str, content: str) -> None:
        await self._request(
            db, node_id, "POST", f"{server_uuid}/files/write",
            params={"file": file_path}, content=content.encode("utf-8"), content_type="text/plain", expected_statuses=(204,),
        )

    async def rename_file(
        self, db: AsyncSession, node_id: int, server_uuid: str, root: str, rename_from: str, rename_to: str
    ) -> None:
        await self._request(
            db, node_id, "PUT", f"{server_uuid}/files/rename",
            json_body={"root": root, "files": [{"from": rename_from, "to": rename_to}]}, expected_statuses=(204,),
        )

    async def delete_files(self, db: AsyncSession, node_id: int, server_uuid: str, root: str, files: list[str]) -> None:
        await self._request(
            db, node_id, "POST", f"{server_uuid}/files/delete",
            json_body={"root": root, "files": files}, expected_statuses=(204,),
        )

    async def create_directory(self, db: AsyncSession, node_id: int, server_uuid: str, name: str, path: str) -> None:
        await self._request(
            db, node_id, "POST", f"{server_uuid}/files/create-directory",
            json_body={"name": name, "path": path}, expected_statuses=(204,),
        )

    async def compress_files(self, db: AsyncSession, node_id: int, server_uuid: str, root: str, files: list[str]) -> dict[str, Any]:
        return (
            await self._request(
                db, node_id, "POST", f"{server_uuid}/files/compress",
                json_body={"root": root, "files": files}, timeout=60.0,
            )
        ).json()

    async def decompress_file(self, db: AsyncSession, node_id: int, server_uuid: str, root: str, file_path: str) -> None:
        await self._request(
            db, node_id, "POST", f"{server_uuid}/files/decompress",
            json_body={"root": root, "file": file_path}, expected_statuses=(204,), timeout=60.0,
        )

    async def create_wings_token(
        self, db: AsyncSession, node_id: int, server_uuid: str, user_uuid: str, *, is_admin: bool = False
    ) -> dict[str, str | int]:
        node = await self._node_info(db, node_id)
        now = int(time.time())
        exp = now + 600
        # 普通用户保留安装输出流权限以查看重装实时进度；仅管理员附带底层错误与迁移流权限。
        permissions = ["*", "admin.websocket.install"]
        if is_admin:
            permissions.extend(["admin.websocket.errors", "admin.websocket.transfer"])
        token = jwt.encode(
            {
                "server_uuid": server_uuid,
                "scope": "websocket file-upload",
                "permissions": permissions,
                "user_uuid": user_uuid,
                "unique_id": str(uuid.uuid4()),
                "iat": now,
                "nbf": now,
                "exp": exp,
            },
            node.token,
            algorithm="HS256",
        )
        ws_scheme = "wss" if node.scheme == "https" else "ws"
        return {
            "token": token,
            "wsUrl": f"{ws_scheme}://{node.fqdn}:{node.port}/api/servers/{server_uuid}/ws",
            "baseUrl": node.base_url,
            "serverUuid": server_uuid,
            "expiresAt": exp,
            "uploadSize": node.upload_size,
        }

    async def get_download_url(
        self, db: AsyncSession, node_id: int, server_uuid: str, file_path: str, *, user_uuid: str
    ) -> str:
        node = await self._node_info(db, node_id)
        now = int(time.time())
        token = jwt.encode(
            {
                "server_uuid": server_uuid,
                "file_path": file_path,
                "scope": "file-download",
                "user_uuid": user_uuid,
                "unique_id": str(uuid.uuid4()),
                "iat": now,
                "nbf": now,
                "exp": now + 300,
            },
            node.token,
            algorithm="HS256",
        )
        return f"{node.base_url}/download/file?token={token}"

    async def get_upload_url(self, db: AsyncSession, node_id: int, server_uuid: str, *, user_uuid: str) -> str:
        node = await self._node_info(db, node_id)
        now = int(time.time())
        token = jwt.encode(
            {
                "server_uuid": server_uuid,
                "scope": "file-upload",
                "user_uuid": user_uuid,
                "unique_id": str(uuid.uuid4()),
                "iat": now,
                "nbf": now,
                "exp": now + 900,
            },
            node.token,
            algorithm="HS256",
        )
        return f"{node.base_url}/upload/file?token={token}"

    async def _node_request(self, db: AsyncSession, node_id: int, method: str, path: str, *, timeout: float = 10.0) -> httpx.Response:
        # ADMIN-ONLY: 节点级接口返回全节点容器信息，禁止用户端路由调用。
        node = await self._node_info(db, node_id)
        return await self._send(
            method,
            f"{node.base_url}/api/{path.lstrip('/')}",
            bearer=node.token,
            timeout=timeout,
            error_fallback=f"Wings /api/{path} returned HTTP error",
        )

    async def get_node_system(self, db: AsyncSession, node_id: int) -> dict[str, Any]:
        return (await self._node_request(db, node_id, "GET", "system")).json()

    async def get_node_servers(self, db: AsyncSession, node_id: int) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = (await self._node_request(db, node_id, "GET", "servers")).json()
        # 剔除环境变量防止监控查询泄漏密钥。
        for srv in data:
            srv.get("configuration", {}).pop("environment", None)
        return data


wings_runtime_adapter = WingsRuntimeAdapter()

__all__ = [
    "RuntimeNodeEndpoint",
    "InstanceRuntimeAdapter",
    "WingsRuntimeAdapter",
    "wings_runtime_adapter",
]
