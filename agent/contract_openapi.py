"""OpenAPI declarations for the shared HTTP error and operation contracts."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from .contracts import ProblemDetails


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    family: {"model": ProblemDetails, "description": description}
    for family, description in (
        ("4XX", "请求无法执行；code 标识原因，fields 按需提供字段问题。"),
        ("5XX", "系统或依赖服务失败；operation 保留各动作的成功或失败结果。"),
    )
}

OPERATION_HEADERS = {
    f"X-Operation-{name}": {"description": description, "schema": schema}
    for name, description, schema in (
        ("Action", "动作标识", {"type": "string"}),
        ("Phase", "结果阶段", {"type": "string", "enum": ["request", "execution", "observation", "acceptance"]}),
        ("Outcome", "本阶段结果", {"type": "string", "enum": ["success", "failed"]}),
        ("Target", "对象标识的 JSON 摘要，不含批量 ID 列表；按需提供", {"type": "string"}),
        ("Succeeded", "实际成功数量；按需提供", {"type": "integer"}),
        ("Failed", "实际失败数量；按需提供", {"type": "integer"}),
    )
}


def install_contract_openapi(app: FastAPI, *, operation_headers: bool = False) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
            for path in schema["paths"].values():
                for operation in path.values():
                    for code, response in operation.get("responses", {}).items():
                        if code in PROBLEM_RESPONSES:
                            content = response["content"]
                            if content.get("application/json", {}).get("schema", {}).get("$ref") == "#/components/schemas/ProblemDetails":
                                content["application/problem+json"] = content.pop("application/json")
                        if operation_headers:
                            response.setdefault("headers", {}).update(OPERATION_HEADERS)
            app.openapi_schema = schema
        return app.openapi_schema

    # FastAPI puts additional response models under application/json by default.
    app.openapi = openapi  # type: ignore[method-assign]
