"""统一支付网关的签名请求与通知验签。"""

import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_settings import BILLING_SPECS
from app.core.settings_store import get_settings_store


class GatewayError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


def signature(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    content = "\n".join((timestamp, method, path, hashlib.sha256(body).hexdigest()))
    return hmac.new(secret.encode(), content.encode(), hashlib.sha256).hexdigest()


class GatewayClient:
    def __init__(self, url: str, app_id: str, secret: str):
        self.url = url.rstrip("/")
        self.app_id = app_id
        self.secret = secret

    @classmethod
    async def load(cls, db: AsyncSession) -> "GatewayClient":
        values = await get_settings_store().get_many(db, {
            key: BILLING_SPECS[key].default_value()
            for key in ("PAYMENT_GATEWAY_URL", "PAYMENT_GATEWAY_APP_ID", "PAYMENT_GATEWAY_SECRET")
        })
        if not all(values.values()):
            raise GatewayError("gateway_not_configured", "支付网关尚未配置", 503)
        return cls(values["PAYMENT_GATEWAY_URL"], values["PAYMENT_GATEWAY_APP_ID"], values["PAYMENT_GATEWAY_SECRET"])

    async def request(self, method: str, path: str, body: dict | None = None) -> Any:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode() if body is not None else b""
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json", "X-App-Id": self.app_id,
            "X-Timestamp": timestamp, "X-Signature": signature(self.secret, timestamp, method, path, raw),
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
            try:
                response = await client.request(method, self.url + path, content=raw, headers=headers)
            except httpx.RequestError as exc:
                raise GatewayError("gateway_unreachable", "暂未取得支付网关响应，将继续同步原请求") from exc
        if response.is_error:
            if response.headers.get("content-type", "").startswith("application/problem+json"):
                problem = response.json()
                raise GatewayError(problem["code"], problem["title"], response.status_code)
            raise GatewayError("gateway_unreachable", "支付网关暂时无法连接，将继续同步原请求")
        return response.json() if response.status_code != 204 else None

    def verify(self, headers, method: str, path: str, raw: bytes) -> bool:
        timestamp = headers.get("x-timestamp", "")
        try:
            age = abs(time.time() - int(timestamp))
        except (ValueError, OverflowError):
            return False
        return (
            age <= 300 and headers.get("x-app-id") == self.app_id
            and hmac.compare_digest(headers.get("x-signature", ""), signature(self.secret, timestamp, method, path, raw))
        )
