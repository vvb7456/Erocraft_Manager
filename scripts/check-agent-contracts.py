"""Check Agent imports, model evaluation and HTTP contracts on supported Python versions."""

from __future__ import annotations

import asyncio
from pathlib import Path
import socket
import sys

import httpx
from pydantic import TypeAdapter
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import AgentConfig
from agent.contracts import ErrorInfo, FieldError, OperationResult, ProblemDetails
from agent.http_app import create_app
from agent.schemas import CommandResponse


def check_models() -> None:
    error = ErrorInfo(code="dependency.timeout", params={"attempt": 1, "seconds": 0.5, "retry": False})
    operation = OperationResult(
        action="certificate.deploy", phase="execution", outcome="failed", error=error,
        target={"host_id": 1, "target_name": "test", "certificate_ids": [2, 3]},
        facts={"saved": True, "count": 2}, succeeded=1, failed=1,
        children=[OperationResult(action="certificate.save", phase="execution", outcome="success")],
    )
    problem = ProblemDetails(
        type="tag:erocraft.com,2026-10-15:error:dependency.timeout", title="timeout",
        status=504, code=error.code, operation=operation, context={"host_id": 1},
        fields=[FieldError(code="validation.required", location="body", path=["items", 0])],
    )
    assert ProblemDetails.model_validate_json(problem.model_dump_json()) == problem
    assert type(operation.target["host_id"]) is int
    assert type(operation.facts["saved"]) is bool
    assert type(error.params["seconds"]) is float
    assert error.detail is None


async def check_http(role: str) -> None:
    cfg = AgentConfig.model_validate({"agent": {"token": "contract-check-token", "role": role}})
    app = create_app(cfg, "contract-check")
    schema = app.openapi()
    assert schema["components"]["schemas"]["OperationResult"]["properties"]["outcome"]["enum"] == ["success", "failed"]
    assert "application/problem+json" in schema["paths"]["/v1/commands"]["post"]["responses"]["4XX"]["content"]
    adapter = TypeAdapter(CommandResponse)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off", loop="asyncio", http="h11"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            for _ in range(100):
                if server.started:
                    break
                if task.done():
                    await task
                    raise AssertionError("测试 Agent 提前退出")
                await asyncio.sleep(0.05)
            assert server.started, "测试 Agent 启动超时"
            async with httpx.AsyncClient(base_url="http://127.0.0.1:%d" % port, trust_env=False) as client:
                assert (await client.get("/healthz")).json() == {"status": "ok"}
                response = await client.post("/v1/commands", json={"id": 1, "type": "ping"})
                assert response.status_code == 401
                assert response.headers["www-authenticate"] == "Bearer"
                assert ProblemDetails.model_validate(response.json()).code == "auth.invalid_token"
                client.headers["Authorization"] = "Bearer contract-check-token"
                for payload, status in (("{", 400), ("{}", 422)):
                    response = await client.post("/v1/commands", content=payload, headers={"Content-Type": "application/json"})
                    assert response.status_code == status
                    assert response.headers["content-type"].startswith("application/problem+json")
                    assert ProblemDetails.model_validate(response.json()).operation.outcome == "failed"
                for command, params, code in (
                    ("ping", {}, None),
                    ("contract-check.unsupported", {}, "agent.command_unsupported"),
                    ("cert.install", {"cert_id": {}}, "agent.command_invalid_params"),
                    ("wings.restart", {"timeout": {}}, "agent.command_invalid_params"),
                ):
                    response = await client.post("/v1/commands", json={"id": 2, "type": command, "params": params})
                    assert response.status_code == 200, response.text
                    result = adapter.validate_json(response.content)
                    assert result.id == 2 and result.operation.action == command
                    assert result.ok == (code is None)
                    if code is None:
                        assert result.output == "pong" and result.operation.outcome == "success"
                    else:
                        assert result.error.code == code and result.operation.outcome == "failed"
        finally:
            server.should_exit = True
            await task


async def main() -> None:
    check_models()
    for role in ("synology_dsm", "generic_host", "wings_node"):
        await check_http(role)
    print("Agent 契约检查通过：Python %s，三种角色的模型、OpenAPI、HTTP 错误和 RPC 结果均正常。" % sys.version.split()[0])


if __name__ == "__main__":
    asyncio.run(main())
