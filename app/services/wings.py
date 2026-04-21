"""Async Wings direct API client with TTL-cached node credentials."""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from dataclasses import dataclass

import httpx
import jwt
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.pterodactyl import PanelNode


class WingsServiceError(RuntimeError):
    """Raised when Wings cannot be reached or returns an operational error."""


@dataclass(slots=True)
class _NodeInfo:
    fqdn: str
    scheme: str
    port: int
    token: str

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.fqdn}:{self.port}"


@dataclass(slots=True)
class _CachedNodeInfo:
    info: _NodeInfo
    expires_at: float


class WingsService:
    def __init__(self, cache_ttl_seconds: float = 60.0) -> None:
        self._cache_ttl_seconds = cache_ttl_seconds
        self._node_cache: dict[int, _CachedNodeInfo] = {}

    def clear_cache(self) -> None:
        self._node_cache.clear()

    def _app_key(self) -> bytes:
        raw = get_settings().panel_app_key or ""
        if not raw:
            raise WingsServiceError("PANEL_APP_KEY 未配置")
        if raw.startswith("base64:"):
            return base64.b64decode(raw[7:])
        return raw.encode("utf-8")

    def _decrypt_laravel(self, encrypted_b64: str) -> str:
        payload = json.loads(base64.b64decode(encrypted_b64))
        iv = base64.b64decode(payload["iv"])
        value = base64.b64decode(payload["value"])
        cipher = Cipher(algorithms.AES(self._app_key()), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(value) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(decrypted) + unpadder.finalize()
        match = re.match(rb's:\d+:"(.+)";', plaintext)
        return match.group(1).decode("utf-8") if match else plaintext.decode("utf-8")

    async def _node_info(self, db: AsyncSession, node_id: int) -> _NodeInfo:
        now = time.monotonic()
        cached = self._node_cache.get(node_id)
        if cached and cached.expires_at > now:
            return cached.info

        node = await db.get(PanelNode, node_id)
        if node is None:
            raise WingsServiceError(f"节点 {node_id} 不存在")

        info = _NodeInfo(
            fqdn=node.fqdn,
            scheme=node.scheme,
            port=node.daemon_listen,
            token=self._decrypt_laravel(node.daemon_token),
        )
        self._node_cache[node_id] = _CachedNodeInfo(
            info=info,
            expires_at=now + self._cache_ttl_seconds,
        )
        return info

    async def _request(
        self,
        db: AsyncSession,
        node_id: int,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        expected_statuses: tuple[int, ...] = (200,),
        timeout: float = 20.0,
    ) -> httpx.Response:
        node = await self._node_info(db, node_id)
        headers = {
            "Authorization": f"Bearer {node.token}",
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = content_type
        elif json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.request(
                    method,
                    f"{node.base_url}/api/servers/{path.lstrip('/')}",
                    headers=headers,
                    json=json_body,
                    params=params,
                    content=content,
                )
        except httpx.HTTPError as exc:
            raise WingsServiceError(f"Wings connection failed: {exc!r}") from exc

        if response.status_code not in expected_statuses:
            # Wings returns errors as {"error": "message"} JSON
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict) and "error" in body:
                    detail = body["error"]
            except Exception:
                pass
            if not detail:
                detail = response.text.strip() or f"HTTP {response.status_code}"
            raise WingsServiceError(detail)
        return response

    async def get_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> dict:
        response = await self._request(db, node_id, "GET", server_uuid)
        return response.json()

    async def send_power_action(self, db: AsyncSession, node_id: int, server_uuid: str, action: str) -> None:
        await self._request(
            db,
            node_id,
            "POST",
            f"{server_uuid}/power",
            json_body={"action": action},
            expected_statuses=(202, 204),
        )

    async def list_files(self, db: AsyncSession, node_id: int, server_uuid: str, directory: str = "/") -> list[dict]:
        response = await self._request(
            db,
            node_id,
            "GET",
            f"{server_uuid}/files/list-directory",
            params={"directory": directory},
        )
        return response.json()

    async def get_file_contents(self, db: AsyncSession, node_id: int, server_uuid: str, file_path: str) -> str:
        response = await self._request(
            db,
            node_id,
            "GET",
            f"{server_uuid}/files/contents",
            params={"file": file_path},
        )
        return response.text

    async def write_file(self, db: AsyncSession, node_id: int, server_uuid: str, file_path: str, content: str) -> None:
        await self._request(
            db,
            node_id,
            "POST",
            f"{server_uuid}/files/write",
            params={"file": file_path},
            content=content.encode("utf-8"),
            content_type="text/plain",
            expected_statuses=(204,),
        )

    async def rename_file(
        self,
        db: AsyncSession,
        node_id: int,
        server_uuid: str,
        root: str,
        rename_from: str,
        rename_to: str,
    ) -> None:
        await self._request(
            db,
            node_id,
            "PUT",
            f"{server_uuid}/files/rename",
            json_body={"root": root, "files": [{"from": rename_from, "to": rename_to}]},
            expected_statuses=(204,),
        )

    async def delete_files(
        self,
        db: AsyncSession,
        node_id: int,
        server_uuid: str,
        root: str,
        files: list[str],
    ) -> None:
        await self._request(
            db,
            node_id,
            "POST",
            f"{server_uuid}/files/delete",
            json_body={"root": root, "files": files},
            expected_statuses=(204,),
        )

    async def create_directory(
        self,
        db: AsyncSession,
        node_id: int,
        server_uuid: str,
        name: str,
        path: str,
    ) -> None:
        await self._request(
            db,
            node_id,
            "POST",
            f"{server_uuid}/files/create-directory",
            json_body={"name": name, "path": path},
            expected_statuses=(204,),
        )

    async def compress_files(
        self,
        db: AsyncSession,
        node_id: int,
        server_uuid: str,
        root: str,
        files: list[str],
    ) -> dict:
        response = await self._request(
            db,
            node_id,
            "POST",
            f"{server_uuid}/files/compress",
            json_body={"root": root, "files": files},
            timeout=60.0,
        )
        return response.json()

    async def decompress_file(
        self,
        db: AsyncSession,
        node_id: int,
        server_uuid: str,
        root: str,
        file_path: str,
    ) -> None:
        await self._request(
            db,
            node_id,
            "POST",
            f"{server_uuid}/files/decompress",
            json_body={"root": root, "file": file_path},
            expected_statuses=(204,),
            timeout=60.0,
        )

    async def create_wings_token(
        self,
        db: AsyncSession,
        node_id: int,
        server_uuid: str,
        user_uuid: str,
    ) -> dict[str, str | int]:
        """Create a unified Wings token for WS console + file upload.

        Returns token, wsUrl, baseUrl, serverUuid, expiresAt.
        """
        node = await self._node_info(db, node_id)
        now = int(time.time())
        exp = now + 600  # 10 min
        token = jwt.encode(
            {
                "server_uuid": server_uuid,
                "permissions": [
                    "*",
                    "admin.websocket.errors",
                    "admin.websocket.install",
                    "admin.websocket.transfer",
                ],
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
        }

    async def get_download_url(self, db: AsyncSession, node_id: int, server_uuid: str, file_path: str) -> str:
        node = await self._node_info(db, node_id)
        now = int(time.time())
        token = jwt.encode(
            {
                "server_uuid": server_uuid,
                "file_path": file_path,
                "unique_id": str(uuid.uuid4()),
                "iat": now,
                "nbf": now,
                "exp": now + 300,
            },
            node.token,
            algorithm="HS256",
        )
        return f"{node.base_url}/download/file?token={token}"

    async def get_upload_url(self, db: AsyncSession, node_id: int, server_uuid: str) -> str:
        node = await self._node_info(db, node_id)
        now = int(time.time())
        token = jwt.encode(
            {
                "server_uuid": server_uuid,
                "unique_id": str(uuid.uuid4()),
                "iat": now,
                "nbf": now,
                "exp": now + 900,
            },
            node.token,
            algorithm="HS256",
        )
        return f"{node.base_url}/upload/file?token={token}"

    # ------------------------------------------------------------------
    # Node-level endpoints (monitoring)
    # ------------------------------------------------------------------

    async def _node_request(
        self,
        db: AsyncSession,
        node_id: int,
        method: str,
        path: str,
        *,
        timeout: float = 10.0,
    ) -> httpx.Response:
        """Make a request to a Wings node-level API endpoint (no /servers/ prefix).

        .. warning::
           **ADMIN-ONLY.** Node-level Wings endpoints return data across ALL
           servers on the node, including those owned by other users. Callers
           MUST be gated by ``require_admin``; NEVER expose this (or any method
           built on top of it such as :meth:`get_node_system` /
           :meth:`get_node_servers`) from a user-facing router.
        """
        node = await self._node_info(db, node_id)
        headers = {
            "Authorization": f"Bearer {node.token}",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.request(
                    method,
                    f"{node.base_url}/api/{path.lstrip('/')}",
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise WingsServiceError(f"Wings connection failed: {exc!r}") from exc

        if response.status_code != 200:
            raise WingsServiceError(f"Wings /api/{path} returned HTTP {response.status_code}")
        return response

    async def get_node_system(self, db: AsyncSession, node_id: int) -> dict:
        """GET /api/system — returns architecture, cpu_count, kernel, os, version.

        .. warning::
           **ADMIN-ONLY.** See :meth:`_node_request`. Must only be called from
           admin routers (``require_admin``).
        """
        response = await self._node_request(db, node_id, "GET", "system")
        return response.json()

    async def get_node_servers(self, db: AsyncSession, node_id: int) -> list[dict]:
        """GET /api/servers — returns all containers with state + utilization.

        .. warning::
           **ADMIN-ONLY.** Returns every server on the node, including those
           owned by other users. See :meth:`_node_request`. Must only be called
           from admin routers (``require_admin``).
        """
        response = await self._node_request(db, node_id, "GET", "servers")
        data = response.json()
        # Scrub environment from each container to avoid leaking secrets
        for srv in data:
            cfg = srv.get("configuration", {})
            cfg.pop("environment", None)
        return data


wings_service = WingsService()
