"""FastAPI app for the agent.

Endpoints:
  GET  /healthz                — no auth
  GET  /v1/metrics             — Bearer
  GET  /v1/wings/config        — Bearer
  POST /v1/commands            — Bearer
  GET  /v1/status              — Bearer
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status

from . import __version__
from .auth import make_auth_dependency
from .collectors.snapshot import SnapshotProvider
from .collectors import wings_config as wings_config_collector
from .commands import HANDLERS, execute as execute_command
from .config import AgentConfig
from .schemas import (
    AgentStatus,
    CommandRequest,
    CommandResponse,
    MetricsSnapshot,
    WingsConfigSummary,
)


log = logging.getLogger("agent.http")


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
