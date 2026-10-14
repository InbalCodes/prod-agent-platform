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
from anthropic import AsyncAnthropic
from fastapi import FastAPI

from agent_platform import __version__
from agent_platform.agent.workflow import WorkflowInvestigator
from agent_platform.api import health, investigations
from agent_platform.config import Settings, get_settings
from agent_platform.core.errors import register_exception_handlers
from agent_platform.core.logging import configure_logging
from agent_platform.core.request_context import RequestContextMiddleware
from agent_platform.llm.anthropic_client import AnthropicClient
from agent_platform.llm.instrumented import InstrumentedLLMClient
from agent_platform.tools.logs import LogStore

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    sdk_client: AsyncAnthropic | None = None

    # One SDK client per process: it owns an HTTP connection pool that every request reuses.
    if settings.anthropic_api_key is not None:
        sdk_client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )
        llm = InstrumentedLLMClient(
            AnthropicClient(sdk_client, model=settings.llm_model, effort=settings.llm_effort)
        )
        app.state.investigator = WorkflowInvestigator(
            llm=llm,
            logs=LogStore.from_jsonl(settings.log_fixture_path),
            timeout_s=settings.investigation_timeout_s,
        )
    else:
        log.warning("llm_not_configured", reason="APP_ANTHROPIC_API_KEY is not set")

    log.info(
        "startup",
        environment=settings.environment,
        version=__version__,
        llm_model=settings.llm_model if sdk_client else None,
    )
    app.state.ready = True

    yield

    # Shutdown: uvicorn has already stopped accepting connections and drained
    # in-flight requests (graceful shutdown). Close pools/clients here.
    app.state.ready = False
    if sdk_client is not None:
        await sdk_client.close()
    log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.ready = False
    app.state.investigator = None

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(investigations.router)

    return app
