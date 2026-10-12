"""Spec for the request-context exercise (src/agent_platform/core/request_context.py)."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from agent_platform.config import Settings
from agent_platform.core.request_context import REQUEST_ID_HEADER, get_request_id
from agent_platform.main import create_app


def test_generates_request_id_when_missing(client: TestClient) -> None:
    response = client.get("/health/live")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers[REQUEST_ID_HEADER])


def test_each_request_gets_a_different_id(client: TestClient) -> None:
    first = client.get("/health/live").headers[REQUEST_ID_HEADER]
    second = client.get("/health/live").headers[REQUEST_ID_HEADER]

    assert first != second


def test_reuses_valid_incoming_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={REQUEST_ID_HEADER: "upstream-abc.123"})

    assert response.headers[REQUEST_ID_HEADER] == "upstream-abc.123"


@pytest.mark.parametrize(
    "untrusted",
    [
        "x" * 129,  # too long
        "id with spaces",
        '{"level":"error"}',  # tries to forge a JSON log line
        "<script>alert(1)</script>",
    ],
)
def test_replaces_invalid_incoming_request_id(client: TestClient, untrusted: str) -> None:
    response = client.get("/health/live", headers={REQUEST_ID_HEADER: untrusted})

    assert response.headers[REQUEST_ID_HEADER] != untrusted
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers[REQUEST_ID_HEADER])


def test_request_id_is_available_inside_the_request(client: TestClient) -> None:
    response = client.get("/_test/request-id")

    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_no_request_id_outside_a_request() -> None:
    assert get_request_id() is None


def test_unhandled_error_still_carries_request_id(client: TestClient) -> None:
    response = client.get("/_test/boom", headers={REQUEST_ID_HEADER: "trace-500"})

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "trace-500"
    assert response.json()["request_id"] == "trace-500"


def test_writes_one_access_log_line_per_request(capsys: pytest.CaptureFixture[str]) -> None:
    app = create_app(Settings(_env_file=None, log_json=True))
    with TestClient(app) as client:
        client.get("/health/live", headers={REQUEST_ID_HEADER: "trace-log"})

    output = capsys.readouterr().out
    lines = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    access = [
        line
        for line in lines
        if line.get("event") == "http_request" and line.get("request_id") == "trace-log"
    ]

    assert len(access) == 1
    assert access[0]["method"] == "GET"
    assert access[0]["path"] == "/health/live"
    assert access[0]["status_code"] == 200
    assert access[0]["duration_ms"] >= 0
