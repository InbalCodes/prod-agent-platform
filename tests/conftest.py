from collections.abc import Iterator

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agent_platform.config import Settings
from agent_platform.core.request_context import get_request_id
from agent_platform.main import create_app

# Routes that exist only in tests, to observe behavior from inside a request.
test_router = APIRouter(prefix="/_test")


@test_router.get("/request-id")
async def echo_request_id() -> dict[str, str | None]:
    return {"request_id": get_request_id()}


@test_router.get("/boom")
async def boom() -> None:
    raise RuntimeError("secret internal detail")


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests must not depend on a developer's local .env
    return Settings(_env_file=None)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    app = create_app(settings)
    app.include_router(test_router)
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # `with` runs the lifespan (startup/shutdown), like a real server.
    # raise_server_exceptions=False: return the 500 response instead of re-raising.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
