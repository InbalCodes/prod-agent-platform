"""Application factory.

Run locally:
    uv run uvicorn agent_platform.main:create_app --factory --reload

There is deliberately no module-level `app = create_app()`: importing this module
must not read configuration or touch logging. Tests build their own app with
their own Settings.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agent_platform import __version__
from agent_platform.api import health
from agent_platform.config import Settings, get_settings
from agent_platform.core.errors import register_exception_handlers
from agent_platform.core.logging import configure_logging
from agent_platform.core.request_context import RequestContextMiddleware

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: later this is where DB pools and HTTP clients are created.
    settings: Settings = app.state.settings
    log.info("startup", environment=settings.environment, version=__version__)
    app.state.ready = True

    yield

    # Shutdown: uvicorn has already stopped accepting connections and drained
    # in-flight requests (graceful shutdown). Close pools/clients here.
    app.state.ready = False
    log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.ready = False

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)

    return app
