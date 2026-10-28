"""小程序登录的微信身份交换，与付款无关。"""

import httpx


class WechatLoginError(Exception):
    pass


class WechatUnavailable(Exception):
    pass


async def openid(appid: str, secret: str, code: str) -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as client:
        try:
            response = await client.get("https://api.weixin.qq.com/sns/jscode2session", params={
                "appid": appid, "secret": secret, "js_code": code, "grant_type": "authorization_code",
            })
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WechatUnavailable("微信登录暂时无法连接，请稍后重试") from exc
    data = response.json()
    if data.get("errcode", 0):
        raise WechatLoginError(data["errmsg"])
    return data["openid"]
