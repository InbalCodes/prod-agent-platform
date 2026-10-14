from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.agent.report import Evidence, Hypothesis, InvestigationReport
from agent_platform.agent.workflow import WorkflowInvestigator
from agent_platform.api.investigations import get_investigator
from agent_platform.llm.errors import (
    LLMError,
    LLMOutputError,
    LLMRateLimitError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from agent_platform.llm.fake import FakeLLMClient
from agent_platform.tools.logs import LogLine, LogStore


def _store() -> LogStore:
    line = LogLine(
        id="L1",
        timestamp=datetime(2026, 10, 13, 10, 0, tzinfo=UTC),
        service="checkout",
        level="ERROR",
        message="error",
    )
    return LogStore([line])


REPORT = InvestigationReport(
    summary="deploy broke checkout",
    status="conclusive",
    hypotheses=[
        Hypothesis(
            root_cause="bad deploy",
            category="deployment_regression",
            confidence=0.9,
            evidence=[Evidence(log_line_id="L1", why_relevant="...")],
        )
    ],
    next_steps=["roll back"],
)


def _client_with(app: FastAPI, script: list[InvestigationReport | LLMError]) -> TestClient:
    investigator = WorkflowInvestigator(llm=FakeLLMClient(script), logs=_store(), timeout_s=5)
    app.dependency_overrides[get_investigator] = lambda: investigator
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def unconfigured(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def test_returns_report_and_run_metadata(app: FastAPI) -> None:
    client = _client_with(app, [REPORT])

    response = client.post("/v1/investigations", json={"issue": "checkout returns 500 errors"})

    assert response.status_code == 200
    body = response.json()
    assert body["report"]["hypotheses"][0]["category"] == "deployment_regression"
    assert body["llm_calls"] == 1
    assert body["final_grounded"] is True


def test_rejects_too_short_issue(app: FastAPI) -> None:
    client = _client_with(app, [])

    response = client.post("/v1/investigations", json={"issue": "500"})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


def test_unconfigured_llm_returns_503(unconfigured: TestClient) -> None:
    response = unconfigured.post("/v1/investigations", json={"issue": "checkout returns 500"})

    assert response.status_code == 503
    assert "APP_ANTHROPIC_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (LLMRateLimitError("quota"), 503),
        (LLMTimeoutError("slow"), 504),
        (LLMUnavailableError("down"), 503),
        (LLMOutputError("refusal"), 502),
        (LLMRequestError("bad key"), 500),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, Exception) else str(v),
)
def test_llm_errors_map_to_upstream_statuses(app: FastAPI, error: LLMError, status: int) -> None:
    client = _client_with(app, [error])

    response = client.post("/v1/investigations", json={"issue": "checkout returns 500 errors"})

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert str(error) not in response.text  # provider details stay in the logs
    assert "request_id" in response.json()


def test_rate_limit_propagates_retry_after(app: FastAPI) -> None:
    client = _client_with(app, [LLMRateLimitError("quota", retry_after_s=1.2)])

    response = client.post("/v1/investigations", json={"issue": "checkout returns 500 errors"})

    assert response.headers["Retry-After"] == "2"
