"""FastAPI app for the agent.

Endpoints:
  GET  /healthz                     — no auth
  GET  /v1/metrics                  — Bearer
  GET  /v1/wings/config             — Bearer
  GET  /v1/wings/service            — Bearer (PR-A)
  GET  /v1/wings/logs/stream        — Bearer (PR-A, SSE)
  GET  /v1/cert/status              — Bearer (PR-B)
  POST /v1/commands                 — Bearer (incl. wings.restart / wings.status)
  GET  /v1/status                   — Bearer
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

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
    AgentStatus,
    CommandRequest,
    CommandResponse,
    MetricsSnapshot,
    WingsConfigSummary,
    WingsServiceStatus,
)


log = logging.getLogger("agent.http")


# Cap concurrent SSE log streams. journalctl -f holds a fd + a goroutine in
# systemd-journald per follower; 4 in flight is plenty for ops use.
#
# Implemented as a counter + lock (NOT an asyncio.Semaphore) because we want
# atomic "check-and-acquire": if the cap is reached we must reject with 503
# *immediately*, never let the second arrival sit and wait for a slot. A
# Semaphore's ``locked() + acquire()`` pair has a race window where two
# concurrent requests both pass ``locked()`` and the second blocks instead
# of being rejected.
_LOG_STREAM_LIMIT = 4
_log_stream_count = 0
_log_stream_lock = asyncio.Lock()


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

    # Inject config into command handlers (used by wings.restart / wings.status).
    command_handlers.set_config(cfg)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/metrics", response_model=MetricsSnapshot, dependencies=[Depends(auth)])
    async def get_metrics() -> MetricsSnapshot:
        return await snapshot.get()

    @app.get("/v1/wings/config", response_model=WingsConfigSummary, dependencies=[Depends(auth)])
    async def get_wings_config() -> WingsConfigSummary:
        try:
            return wings_config_collector.read_summary(cfg.wings.config_path)
        except wings_config_collector.WingsConfigError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    @app.get("/v1/wings/service", response_model=WingsServiceStatus, dependencies=[Depends(auth)])
    async def get_wings_service() -> WingsServiceStatus:
        return await wings_service_collector.status(cfg.wings.service_name)

    @app.get("/v1/cert/status", dependencies=[Depends(auth)])
    async def get_cert_status() -> dict:
        try:
            return cert_collector.status_with_targets(
                cfg.wings.config_path,
                cfg.cert_install_targets,
            )
        except wings_config_collector.WingsConfigError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    @app.get("/v1/wings/logs/stream", dependencies=[Depends(auth)])
    async def stream_wings_logs(
        request: Request,
        lines: int = Query(100, ge=0, le=1000),
    ) -> StreamingResponse:
        global _log_stream_count
        # Atomic admission control: check-and-increment under the lock so a
        # second arrival cannot squeeze through after the count check.
        async with _log_stream_lock:
            if _log_stream_count >= _LOG_STREAM_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"too many concurrent log streams (limit={_LOG_STREAM_LIMIT})",
                )
            _log_stream_count += 1

        async def event_source():
            global _log_stream_count
            try:
                # SSE preamble: tell client to retry after 5s if disconnected.
                yield b"retry: 5000\n\n"
                async for chunk in wings_service_collector.stream_logs(
                    cfg.wings.service_name, lines=lines
                ):
                    if await request.is_disconnected():
                        break
                    # journalctl emits one line per chunk; SSE-frame it.
                    text = chunk.decode("utf-8", "replace").rstrip("\n")
                    yield f"data: {text}\n\n".encode("utf-8")
            finally:
                async with _log_stream_lock:
                    _log_stream_count -= 1

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",   # tell nginx not to buffer
            },
        )

    @app.post("/v1/commands", response_model=CommandResponse, dependencies=[Depends(auth)])
    async def post_command(req: CommandRequest) -> CommandResponse:
        log.info("command id=%d type=%s", req.id, req.type)
        if req.type not in HANDLERS:
            # Surface unknown command types at the HTTP layer so clients can
            # alert / route based on status code instead of parsing the body.
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
            wings_config_path=cfg.wings.config_path,
            bind=cfg.agent.bind,
        )

    return app
