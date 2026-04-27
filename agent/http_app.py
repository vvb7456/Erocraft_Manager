"""FastAPI app for the agent.

All endpoints require Bearer auth except /healthz.
Wings-specific routes are only registered when role=wings_node.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from . import __version__
from .auth import make_auth_dependency
from .collectors.snapshot import SnapshotProvider
from .collectors import certificates as cert_collector
from .collectors import wings_config as wings_config_collector
from .collectors import wings_service as wings_service_collector
from .commands import HANDLERS, execute as execute_command, handlers as command_handlers
from .config import AgentConfig
from .schemas import (
    AgentCapabilities,
    AgentStatus,
    CommandRequest,
    CommandResponse,
    MetricsSnapshot,
    WingsConfigSummary,
    WingsServiceStatus,
)


log = logging.getLogger("agent.http")

_LOG_STREAM_LIMIT = 4


class _LogStreamGuard:
    """Admission control for concurrent SSE log streams.

    Uses a counter + lock (not a Semaphore) so that check-and-acquire is atomic:
    if the cap is reached the request is rejected immediately with 503.
    """

    def __init__(self, limit: int = _LOG_STREAM_LIMIT) -> None:
        self._limit = limit
        self._count = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            if self._count >= self._limit:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"too many concurrent log streams (limit={self._limit})",
                )
            self._count += 1

    async def release(self) -> None:
        async with self._lock:
            self._count -= 1


def _compute_capabilities(cfg: AgentConfig) -> AgentCapabilities:
    is_wings = cfg.agent.is_wings
    has_targets = len(cfg.cert_install_targets) > 0
    has_certs = is_wings or has_targets
    return AgentCapabilities(
        metrics_system=True,
        metrics_wings=is_wings,
        cert_status=has_certs,
        cert_expiry_warning=has_certs,
        cert_install=has_certs,
        cert_targets=has_targets,
        wings_config=is_wings,
        wings_restart=is_wings,
        wings_service=is_wings,
        wings_logs=is_wings,
    )


def create_app(cfg: AgentConfig, config_path: str) -> FastAPI:
    app = FastAPI(
        title="Erocraft Agent",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    auth = make_auth_dependency(cfg)
    snapshot = SnapshotProvider(cfg)
    started_at = datetime.now(timezone.utc)
    capabilities = _compute_capabilities(cfg)

    command_handlers.set_config(cfg)

    # ---- shared routes ----

    @app.get("/healthz")
    async def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/metrics", response_model=MetricsSnapshot, dependencies=[Depends(auth)])
    async def get_metrics() -> MetricsSnapshot:
        return await snapshot.get()

    @app.get("/v1/cert/status", dependencies=[Depends(auth)])
    async def get_cert_status() -> Dict[str, Any]:
        try:
            return await cert_collector.status_with_targets(
                cfg.wings.config_path,
                cfg.cert_install_targets,
            )
        except wings_config_collector.WingsConfigError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    @app.post("/v1/commands", response_model=CommandResponse, dependencies=[Depends(auth)])
    async def post_command(req: CommandRequest) -> CommandResponse:
        log.info("command id=%d type=%s", req.id, req.type)
        if req.type not in HANDLERS:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"command type not implemented in this agent version: {req.type}",
            )
        return await execute_command(req)

    @app.get("/v1/status", response_model=AgentStatus, dependencies=[Depends(auth)])
    async def get_status() -> AgentStatus:
        return AgentStatus(
            version=__version__,
            started_at=started_at,
            config_path=config_path,
            wings_config_path=cfg.wings.config_path if cfg.agent.is_wings else None,
            bind=cfg.agent.bind,
            role=cfg.agent.role,
            capabilities=capabilities,
        )

    # ---- wings-only routes ----

    if cfg.agent.is_wings:
        _register_wings_routes(app, cfg, auth)

    return app


def _register_wings_routes(app: FastAPI, cfg: AgentConfig, auth: Any) -> None:
    log_guard = _LogStreamGuard()

    @app.get("/v1/wings/config", response_model=WingsConfigSummary, dependencies=[Depends(auth)])
    async def get_wings_config() -> WingsConfigSummary:
        try:
            return wings_config_collector.read_summary(cfg.wings.config_path)
        except wings_config_collector.WingsConfigError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    @app.get("/v1/wings/service", response_model=WingsServiceStatus, dependencies=[Depends(auth)])
    async def get_wings_service() -> WingsServiceStatus:
        return await wings_service_collector.status(cfg.wings.service_name)

    @app.get("/v1/wings/logs/stream", dependencies=[Depends(auth)])
    async def stream_wings_logs(
        request: Request,
        lines: int = Query(100, ge=0, le=1000),
    ) -> StreamingResponse:
        await log_guard.acquire()

        async def event_source():
            try:
                yield b"retry: 5000\n\n"
                async for chunk in wings_service_collector.stream_logs(
                    cfg.wings.service_name, lines=lines
                ):
                    if await request.is_disconnected():
                        break
                    text = chunk.decode("utf-8", "replace").rstrip("\n")
                    yield f"data: {text}\n\n".encode("utf-8")
            finally:
                await log_guard.release()

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
