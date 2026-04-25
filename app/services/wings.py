"""Async Wings direct API client with TTL-cached node credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
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
    upload_size: int   # MiB; per-file upload limit (panel.nodes.upload_size)

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

    def _encrypt_laravel(self, plaintext: str) -> str:
        """Laravel ``Crypt::encrypt()`` compatible encrypt for fields that the
        Pterodactyl panel later decrypts (e.g. ``daemon_token``).

        Mirrors PHP serialise → AES-256-CBC → base64 → HMAC-SHA256 of the
        base64-encoded ``iv || value`` → JSON envelope ``{iv, value, mac, tag}``
        → final base64. ``tag`` is empty for CBC (only used by GCM in newer
        Laravel versions).
        """
        key = self._app_key()
        # PHP ``serialize($string)`` → ``s:LEN:"VALUE";``
        serialised = f's:{len(plaintext)}:"{plaintext}";'.encode("utf-8")
        padder = padding.PKCS7(128).padder()
        padded = padder.update(serialised) + padder.finalize()
        iv = secrets.token_bytes(16)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        iv_b64 = base64.b64encode(iv).decode("ascii")
        value_b64 = base64.b64encode(ciphertext).decode("ascii")
        mac = hmac.new(
            key,
            (iv_b64 + value_b64).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        envelope = json.dumps(
            {"iv": iv_b64, "value": value_b64, "mac": mac, "tag": ""},
            separators=(",", ":"),
        )
        return base64.b64encode(envelope.encode("utf-8")).decode("ascii")

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
            upload_size=node.upload_size,
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

    async def post_node_update(
        self,
        db: AsyncSession,
        node_id: int,
        payload: dict,
        *,
        explicit_token: str | None = None,
        explicit_base_url: str | None = None,
        timeout: float = 15.0,
    ) -> dict:
        """Push a partial Configuration patch to wings ``POST /api/update``.

        Wings binds the JSON onto its in-memory ``config.Configuration`` via
        Gin BindJSON, then writes to disk + hot-applies. Fields **omitted**
        from ``payload`` keep their existing wings value; explicit zero values
        (false / 0 / "") will overwrite. Returns ``{"applied": bool}`` —
        ``applied=false`` means the node has ``ignore_panel_config_updates: true``.

        ``explicit_token`` lets the caller authenticate with a token that may
        differ from the value currently stored in ``panel.nodes`` — needed for
        the daemon-token rotation flow (we must authenticate using the *old*
        token while pushing the *new* one).

        ``explicit_base_url`` lets the caller target a wings endpoint that
        differs from the value computed from the (possibly mutated) panel
        row — needed for ``put_wings_config`` so a change to ``fqdn`` /
        ``scheme`` / ``daemon_listen`` is pushed to the **old** address that
        wings is still listening on.
        """
        if explicit_base_url is not None:
            base_url = explicit_base_url
            if explicit_token is None:
                # Caller must provide token explicitly when overriding URL,
                # otherwise we'd race against the very mutation being pushed.
                node = await self._node_info(db, node_id)
                bearer = node.token
            else:
                bearer = explicit_token
        else:
            node = await self._node_info(db, node_id)
            base_url = node.base_url
            bearer = explicit_token if explicit_token is not None else node.token
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(
                    f"{base_url}/api/update",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise WingsServiceError(f"Wings connection failed: {exc!r}") from exc
        if response.status_code != 200:
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict) and "error" in body:
                    detail = body["error"]
            except Exception:
                pass
            raise WingsServiceError(detail or f"HTTP {response.status_code}")
        try:
            return response.json()
        except Exception:
            return {"applied": True}

    # ------------------------------------------------------------------
    # Server lifecycle (Phase X — direct DB + Wings, no Application API)
    # ------------------------------------------------------------------

    async def create_server(
        self,
        db: AsyncSession,
        node_id: int,
        server_uuid: str,
        *,
        start_on_completion: bool = False,
    ) -> None:
        """Notify Wings that a new server row exists in the panel DB.

        Wings will reverse-pull the full configuration via panel
        ``/api/remote/servers/{uuid}``. The panel row MUST already be inserted
        with ``status='installing'`` to trigger the install flow on the node.

        ``start_on_completion`` mirrors Pterodactyl's
        ``DaemonServerRepository::create($startOnCompletion)`` — when True,
        Wings will start the server automatically once install finishes.
        """
        node = await self._node_info(db, node_id)
        headers = {
            "Authorization": f"Bearer {node.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body: dict[str, object] = {"uuid": server_uuid}
        if start_on_completion:
            body["start_on_completion"] = True
        try:
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                response = await client.post(
                    f"{node.base_url}/api/servers",
                    headers=headers,
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise WingsServiceError(f"Wings connection failed: {exc!r}") from exc
        if response.status_code not in (200, 202, 204):
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict) and "error" in payload:
                    detail = payload["error"]
            except Exception:
                pass
            raise WingsServiceError(detail or f"HTTP {response.status_code}")

    async def sync_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> None:
        """Tell Wings to re-pull the configuration (suspend / unsuspend / build mod)."""
        await self._request(
            db,
            node_id,
            "POST",
            f"{server_uuid}/sync",
            expected_statuses=(200, 202, 204),
        )

    async def reinstall_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> None:
        """Trigger reinstall. The panel row MUST be set to status='installing',
        installed_at=NULL beforehand."""
        await self._request(
            db,
            node_id,
            "POST",
            f"{server_uuid}/reinstall",
            expected_statuses=(200, 202, 204),
        )

    async def deauthorize_user(
        self,
        db: AsyncSession,
        node_id: int,
        user_uuid: str,
        *,
        server_uuids: list[str] | None = None,
    ) -> None:
        """Revoke a user's active Wings websocket/SFTP JWT access.

        Wings exposes this as a node-level endpoint, not under
        ``/api/servers``. Omitting ``servers`` revokes access across the node.
        """
        node = await self._node_info(db, node_id)
        headers = {
            "Authorization": f"Bearer {node.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body: dict[str, object] = {"user": user_uuid}
        if server_uuids is not None:
            body["servers"] = server_uuids
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                response = await client.post(
                    f"{node.base_url}/api/deauthorize-user",
                    headers=headers,
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise WingsServiceError(f"Wings connection failed: {exc!r}") from exc

        if response.status_code not in (200, 202, 204):
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict) and "error" in payload:
                    detail = payload["error"]
            except Exception:
                pass
            raise WingsServiceError(detail or f"HTTP {response.status_code}")

    async def delete_server(self, db: AsyncSession, node_id: int, server_uuid: str) -> None:
        """Destroy the container + volume on the node. Idempotent: 404 → success."""
        try:
            await self._request(
                db,
                node_id,
                "DELETE",
                server_uuid,
                expected_statuses=(204,),
            )
        except WingsServiceError as exc:
            # 404 means already gone — acceptable for idempotent delete
            if "does not exist" in str(exc).lower() or "not found" in str(exc).lower():
                return
            raise

    async def delete_backup(
        self,
        db: AsyncSession,
        node_id: int,
        server_uuid: str,
        backup_uuid: str,
    ) -> None:
        """Remove the physical backup archive from the node. Idempotent.

        Pterodactyl's ``DeleteBackupService`` calls this before nulling out
        the backup row so leftover ``.tar.gz`` files don't accumulate on the
        node when a server is destroyed.
        """
        try:
            await self._request(
                db,
                node_id,
                "DELETE",
                f"{server_uuid}/backup/{backup_uuid}",
                expected_statuses=(204,),
            )
        except WingsServiceError as exc:
            if "does not exist" in str(exc).lower() or "not found" in str(exc).lower():
                return
            raise

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
            "uploadSize": node.upload_size,
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
