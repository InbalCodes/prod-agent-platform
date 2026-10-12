from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_live_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_after_startup(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_not_ready_before_startup(app: FastAPI) -> None:
    # Without `with`, TestClient does not run the lifespan -> startup never completed.
    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
