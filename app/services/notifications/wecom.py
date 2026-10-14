"""WeCom application messages; credentials and tokens never enter request logs."""

import asyncio
import hashlib
import html
import logging
import re
import time
from typing import Any

import httpx


class _HideCredentials(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "qyapi.weixin.qq.com" not in record.getMessage()


logging.getLogger("httpx").addFilter(_HideCredentials())


class DeliveryError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def normalize_recipients(members: list[str]) -> list[str]:
    names = re.split(r"[,;|\s，；]+", ",".join(members).strip())
    return list(dict.fromkeys(name.lower() for name in names if name))


def validate(settings: dict[str, Any], members: list[str]) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", str(settings.get("WECOM_CORP_ID") or "")):
        raise ValueError("请填写有效的企业 ID")
    if not str(settings.get("WECOM_AGENT_ID") or "").isdigit() or int(settings["WECOM_AGENT_ID"]) <= 0:
        raise ValueError("请填写有效的应用 AgentID")
    if not settings.get("WECOM_SECRET"):
        raise ValueError("请填写应用 Secret")
    names = normalize_recipients(members)
    if not names or len(names) > 100 or any(not re.fullmatch(r"[a-z0-9_.@-]{1,64}", name) or name == "@all" for name in names):
        raise ValueError("请填写具体的成员账号，多个账号用逗号分隔，最多 100 个")


def gateway_key(settings: dict[str, Any]) -> str:
    return hashlib.sha256(f"{settings.get('WECOM_CORP_ID')}:{settings.get('WECOM_AGENT_ID')}".encode()).hexdigest()


class WecomClient:
    def __init__(self) -> None:
        self._token = ""
        self._key = ""
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def _request(self, client: httpx.AsyncClient, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await client.request("POST" if "json" in kwargs else "GET", f"https://qyapi.weixin.qq.com/cgi-bin/{path}", **kwargs)
            if response.status_code != 200:
                raise DeliveryError(f"企业微信 HTTP {response.status_code}", retryable=response.status_code >= 500 or response.status_code == 429)
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except httpx.RequestError as exc:
            raise DeliveryError(f"企业微信网络请求失败（{type(exc).__name__}）", retryable=True) from None
        except ValueError:
            raise DeliveryError("企业微信返回了无法解析的响应", retryable=True) from None

    @staticmethod
    def _check(data: dict[str, Any]) -> None:
        code = data.get("errcode", -1)
        if code != 0:
            labels = {40013: "企业 ID 无效", 40001: "应用 Secret 无效", 60020: "服务器出口 IP 未加入应用可信 IP", 81013: "接收人不存在或不在应用可见范围内", 45009: "调用频率超限", 45011: "消息频率超限", 42001: "访问凭据过期"}
            raise DeliveryError(f"{labels.get(code, '企业微信拒绝了请求')}（{code}）", retryable=code in {-1, 45009, 45011, 42001, 40014})
        if any(data.get(key) for key in ("invaliduser", "invalidparty", "invalidtag", "unlicenseduser")):
            raise DeliveryError("接收人不存在、不在应用可见范围内或没有接口权限")

    async def _access_token(self, client: httpx.AsyncClient, settings: dict[str, Any]) -> str:
        key = hashlib.sha256(f"{gateway_key(settings)}:{settings['WECOM_SECRET']}".encode()).hexdigest()
        async with self._lock:
            if key == self._key and self._token and time.monotonic() < self._expires:
                return self._token
            data = await self._request(client, "gettoken", params={"corpid": settings["WECOM_CORP_ID"], "corpsecret": settings["WECOM_SECRET"]})
            self._check(data)
            if not data.get("access_token"):
                raise DeliveryError("企业微信未返回访问凭据", retryable=True)
            self._key, self._token = key, data["access_token"]
            self._expires = time.monotonic() + max(0, int(data.get("expires_in", 7200)) - 120)
            return self._token

    async def send(self, settings: dict[str, Any], *, recipient: str, title: str, body: str, url: str, reference: int) -> str:
        validate(settings, [recipient])
        # text supports links in both WeCom and its WeChat plugin; bound UTF-8 bytes, not characters.
        heading = html.escape(title[:180])
        link = f'\n<a href="{html.escape(url, quote=True)}">查看详情</a>' if url else ""
        suffix = f"\n通知 #{reference}"
        content = f"{heading}\n{html.escape(body)}"
        budget = max(0, 2048 - len((link + suffix).encode()))
        content = content.encode()[:budget].decode(errors="ignore") + link + suffix
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            for attempt in range(2):
                token = await self._access_token(client, settings)
                data = await self._request(client, "message/send", params={"access_token": token}, json={
                    "touser": recipient, "agentid": int(settings["WECOM_AGENT_ID"]), "msgtype": "text",
                    "text": {"content": content}, "enable_duplicate_check": 1, "duplicate_check_interval": 14400,
                })
                if data.get("errcode") in {40014, 42001} and attempt == 0:
                    self._expires = 0
                    continue
                self._check(data)
                return str(data.get("msgid") or "")[:255]
        raise DeliveryError("企业微信访问凭据失效", retryable=True)


client = WecomClient()
