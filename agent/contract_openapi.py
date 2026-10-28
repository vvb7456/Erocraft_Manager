"""OpenAPI declarations for the shared HTTP error and operation contracts."""

from __future__ import annotations

from typing import Any, Dict, Union

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from .contracts import ProblemDetails


PROBLEM_RESPONSES: Dict[Union[int, str], Dict[str, Any]] = {
    family: {"model": ProblemDetails, "description": description}
    for family, description in (
        ("4XX", "请求无法执行；code 标识原因，fields 按需提供字段问题。"),
        ("5XX", "系统或依赖服务失败；operation 保留各动作的成功或失败结果。"),
    )
}

def install_contract_openapi(app: FastAPI) -> None:
    def openapi() -> Dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
            for path in schema["paths"].values():
                for operation in path.values():
                    for code, response in operation.get("responses", {}).items():
                        if code in PROBLEM_RESPONSES:
                            content = response["content"]
                            if content.get("application/json", {}).get("schema", {}).get("$ref") == "#/components/schemas/ProblemDetails":
                                content["application/problem+json"] = content.pop("application/json")
            app.openapi_schema = schema
        return app.openapi_schema

    # FastAPI puts additional response models under application/json by default.
    app.openapi = openapi  # type: ignore[method-assign]
