"""WeChat account APIs (separate from merchant APIv3)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.services.billing.gateway.base import GatewayBusinessError, GatewayTransientError


class _HideWechatQuery(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # These official GET endpoints put AppSecret / login codes in the URL.
        if isinstance(record.args, tuple):
            record.args = tuple(
                item.copy_with(query=None) if isinstance(item, httpx.URL) and item.host == "api.weixin.qq.com" else item
                for item in record.args
            )
        return True


logging.getLogger("httpx").addFilter(_HideWechatQuery())
_tokens: dict[str, tuple[str, str, str, float]] = {}
_token_lock = asyncio.Lock()


async def request(path: str, *, params: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as client:
        try:
            response = await client.request("POST" if body is not None else "GET", "https://api.weixin.qq.com" + path, params=params, json=body)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayTransientError("微信接口暂时无法连接，请稍后重试") from exc
    if data.get("errcode", 0):
        raise GatewayBusinessError(f"微信接口错误 {data['errcode']}：{data.get('errmsg', '')}")
    return data


async def access_token(kind: str, appid: str, secret: str) -> str:
    if not appid or not secret:
        raise GatewayBusinessError("请先配置对应的微信AppID和AppSecret")
    async with _token_lock:
        cached = _tokens.get(kind)
        if cached and cached[0:2] == (appid, secret) and cached[3] > time.monotonic():
            return cached[2]
        data = await request("/cgi-bin/stable_token", body={"grant_type": "client_credential", "appid": appid, "secret": secret})
        token = str(data["access_token"])
        _tokens[kind] = (appid, secret, token, time.monotonic() + int(data["expires_in"]) - 120)
        return token


async def account_request(kind: str, appid: str, secret: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    token = await access_token(kind, appid, secret)
    return await request(path, params={"access_token": token}, body=body)


async def openid(appid: str, secret: str, code: str, *, mini: bool) -> str:
    if not appid or not secret:
        raise GatewayBusinessError("微信授权尚未配置")
    params = {"appid": appid, "secret": secret, "grant_type": "authorization_code", "js_code" if mini else "code": code}
    data = await request("/sns/jscode2session" if mini else "/sns/oauth2/access_token", params=params)
    value = data.get("openid")
    if not isinstance(value, str) or not value:
        raise GatewayBusinessError("未取得微信用户标识，请重新授权")
    return value
