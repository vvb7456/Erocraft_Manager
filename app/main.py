"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.routers import api_router
from app.core.config import get_settings
from app.core.csrf import OriginCheckMiddleware
from app.core.exceptions import register_exception_handlers
from app.core.operation import OperationMiddleware
from app.core.logging import configure_logging
from app.core.rate_limit import limiter
from app.db.session import dispose_engine
from app.core.contract_openapi import PROBLEM_RESPONSES, install_contract_openapi


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        from app.services.llm_provision.newapi_client import close_client
        await close_client()
        await dispose_engine()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.enable_api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_api_docs else None,
        lifespan=lifespan,
        responses=PROBLEM_RESPONSES,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age,
        same_site=settings.session_same_site,
        https_only=settings.session_cookie_secure,
    )
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(OperationMiddleware)
    app.state.limiter = limiter
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api")
    install_contract_openapi(app)
    return app


app = create_app()
