"""Pterodactyl Application API client — async, for FastAPI.

Server/user listing is done via direct MySQL queries (see db/models/).
This module retains API calls for: create/delete/suspend/unsuspend servers,
create/update/delete users, reinstall, and updating server descriptions.
"""

from __future__ import annotations

import logging
import re
from datetime import date

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0


class PterodactylServiceError(Exception):
    """Raised when a Pterodactyl API call fails."""


class PterodactylService:
    """Async wrapper around the Pterodactyl Application API."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        """Create a persistent httpx client (call during app lifespan)."""
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    async def shutdown(self) -> None:
        """Close the persistent httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _base_url(self) -> str:
        return (get_settings().ptero_panel_url or "").rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {get_settings().ptero_api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _check(self) -> None:
        s = get_settings()
        if not s.ptero_panel_url or not s.ptero_api_key:
            raise PterodactylServiceError("Pterodactyl API 未配置")

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json: dict | None = None,
        timeout: float = _TIMEOUT,
    ) -> httpx.Response:
        self._check()
        url = f"{self._base_url()}/api/application/{endpoint}"
        client = self._client or httpx.AsyncClient(timeout=timeout)
        try:
            resp = await client.request(
                method, url, headers=self._headers(), json=json, timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise PterodactylServiceError(f"Pterodactyl API 请求失败: {exc}") from exc
        finally:
            if client is not self._client:
                await client.aclose()
        return resp

    # ── Server operations ──

    async def suspend_server(self, server_id: int) -> None:
        resp = await self._request("POST", f"servers/{server_id}/suspend")
        if resp.status_code >= 400:
            raise PterodactylServiceError(
                f"冻结服务器 {server_id} 失败 (HTTP {resp.status_code})"
            )

    async def unsuspend_server(self, server_id: int) -> None:
        resp = await self._request("POST", f"servers/{server_id}/unsuspend")
        if resp.status_code >= 400:
            raise PterodactylServiceError(
                f"解冻服务器 {server_id} 失败 (HTTP {resp.status_code})"
            )

    async def delete_server(self, server_id: int) -> None:
        resp = await self._request("DELETE", f"servers/{server_id}")
        if resp.status_code not in (204, 404) and resp.status_code >= 400:
            raise PterodactylServiceError(
                f"删除服务器 {server_id} 失败 (HTTP {resp.status_code})"
            )

    async def reinstall_server(self, server_id: int) -> None:
        resp = await self._request("POST", f"servers/{server_id}/reinstall")
        if resp.status_code >= 400:
            raise PterodactylServiceError(
                f"重装服务器 {server_id} 失败 (HTTP {resp.status_code})"
            )

    async def create_server(
        self,
        *,
        user_id: int,
        server_name: str,
        egg_id: int,
        node_id: int,
        allocation_id: int,
        docker_image: str,
        startup_command: str,
        environment: dict,
        cpu: int,
        memory: int,
        disk: int,
        databases: int,
        backups: int,
        allocations: int,
        expiration_date: date,
    ) -> dict:
        """Create a server via the Pterodactyl API.

        Returns the server attributes dict. ServerMeta is managed by the caller.
        """
        description = f"到期时间：{expiration_date.strftime('%Y/%m/%d')}"
        payload = {
            "name": server_name,
            "user": user_id,
            "egg": egg_id,
            "description": description,
            "docker_image": docker_image,
            "startup": startup_command,
            "environment": environment,
            "limits": {
                "memory": memory,
                "swap": 0,
                "disk": disk,
                "io": 500,
                "cpu": cpu,
            },
            "feature_limits": {
                "databases": databases,
                "allocations": allocations,
                "backups": backups,
            },
            "allocation": {"default": allocation_id},
        }
        resp = await self._request("POST", "servers", json=payload)
        if resp.status_code == 422:
            detail = self._extract_validation_error(resp)
            raise PterodactylServiceError(f"创建服务器验证失败: {detail}")
        if resp.status_code >= 400:
            raise PterodactylServiceError(
                f"创建服务器失败 (HTTP {resp.status_code})"
            )
        attrs = resp.json().get("attributes")
        if not attrs:
            raise PterodactylServiceError("创建服务器返回数据异常")
        return attrs

    async def update_server_description(
        self, server_id: int, new_expiration_date: date
    ) -> None:
        """Backward-compatible wrapper for syncing expiration into description."""
        await self.sync_server_expiration(server_id, new_expiration_date)

    async def sync_server_expiration(self, server_id: int, expiration_date: date | None) -> None:
        """Ensure the Panel description carries the current expiration line.

        When expiration_date is None, any existing expiration line is removed.
        """
        resp = await self._request("GET", f"servers/{server_id}")
        if resp.status_code >= 400:
            raise PterodactylServiceError(
                f"获取服务器 {server_id} 详情失败 (HTTP {resp.status_code})"
            )

        server_data = resp.json().get("attributes", {})
        old_desc = server_data.get("description", "") or ""
        cleaned_desc = re.sub(
            r"(^|\n)到期时间[：:]\s*\d{4}[/-]\d{1,2}[/-]\d{1,2}(?=\n|$)",
            "",
            old_desc,
        ).strip()

        if expiration_date is None:
            new_desc = cleaned_desc
        else:
            new_line = f"到期时间：{expiration_date.strftime('%Y/%m/%d')}"
            new_desc = f"{new_line}\n{cleaned_desc}".strip() if cleaned_desc else new_line

        patch_payload = {
            "name": server_data.get("name", ""),
            "user": server_data.get("user", 0),
            "description": new_desc,
        }
        resp2 = await self._request(
            "PATCH", f"servers/{server_id}/details", json=patch_payload
        )
        if resp2.status_code >= 400:
            raise PterodactylServiceError(
                f"同步服务器 {server_id} 到期描述失败 (HTTP {resp2.status_code})"
            )

    # ── User operations ──

    async def create_user(
        self,
        *,
        email: str,
        username: str,
        first_name: str = "New",
        last_name: str = "User",
        password: str,
    ) -> dict:
        payload = {
            "email": email,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "password": password,
            "root_admin": False,
        }
        resp = await self._request("POST", "users", json=payload)
        if resp.status_code == 422:
            detail = self._extract_validation_error(resp)
            raise PterodactylServiceError(f"创建用户验证失败: {detail}")
        if resp.status_code >= 400:
            raise PterodactylServiceError(
                f"创建用户失败 (HTTP {resp.status_code})"
            )
        attrs = resp.json().get("attributes")
        if not attrs:
            raise PterodactylServiceError("创建用户返回数据异常")
        return attrs

    async def update_user(
        self,
        user_id: int,
        *,
        email: str,
        username: str,
        first_name: str,
        last_name: str,
        password: str | None = None,
    ) -> None:
        payload: dict = {
            "email": email,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        }
        if password:
            payload["password"] = password
        resp = await self._request("PATCH", f"users/{user_id}", json=payload)
        if resp.status_code == 422:
            detail = self._extract_validation_error(resp)
            raise PterodactylServiceError(f"更新用户验证失败: {detail}")
        if resp.status_code >= 400:
            raise PterodactylServiceError(
                f"更新用户 {user_id} 失败 (HTTP {resp.status_code})"
            )

    async def delete_user(self, user_id: int) -> None:
        resp = await self._request("DELETE", f"users/{user_id}")
        if resp.status_code not in (204, 404) and resp.status_code >= 400:
            raise PterodactylServiceError(
                f"删除用户 {user_id} 失败 (HTTP {resp.status_code})"
            )

    # ── Helpers ──

    @staticmethod
    def _extract_validation_error(resp: httpx.Response) -> str:
        try:
            errors = resp.json().get("errors", [])
            return "; ".join(e.get("detail", "") for e in errors) if errors else "验证失败"
        except Exception:
            return "验证失败"


pterodactyl_service = PterodactylService()
