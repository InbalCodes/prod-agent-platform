import json

import pytest
from pydantic import BaseModel

from agent_platform.core.logging import configure_logging
from agent_platform.llm.client import Usage
from agent_platform.llm.errors import LLMRateLimitError
from agent_platform.llm.fake import FakeLLMClient
from agent_platform.llm.instrumented import InstrumentedLLMClient
from agent_platform.llm.pricing import estimate_cost_usd


class Answer(BaseModel):
    value: str


def _log_events(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_cost_estimate_uses_versioned_prices() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000)

    assert estimate_cost_usd("claude-opus-5-5", usage) == pytest.approx(4.0 + 2.0)
    assert estimate_cost_usd("unknown-model", usage) is None


@pytest.mark.anyio
async def test_successful_call_is_logged_and_enriched(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json_logs=True)
    fake = FakeLLMClient(
        [Answer(value="ok")],
        model="claude-opus-5-5",
        usage=Usage(input_tokens=2000, output_tokens=500),
    )

    result = await InstrumentedLLMClient(fake).generate_structured(
        system="s", user="u", output_type=Answer
    )

    assert result.parsed == Answer(value="ok")
    assert result.latency_ms is not None
    assert result.cost_usd == pytest.approx((2000 * 4 + 500 * 20) / 1_000_000)

    [event] = [e for e in _log_events(capsys.readouterr().out) if e["event"] == "llm_call"]
    assert event["model"] == "claude-opus-5-5"
    assert event["input_tokens"] == 2000
    assert event["output_tokens"] == 500
    assert event["output_type"] == "Answer"
    assert event["provider_request_id"] == "fake-1"


@pytest.mark.anyio
async def test_failed_call_is_logged_and_reraised(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json_logs=True)
    fake = FakeLLMClient([LLMRateLimitError("slow down", retry_after_s=2)])

    with pytest.raises(LLMRateLimitError):
        await InstrumentedLLMClient(fake).generate_structured(
            system="s", user="u", output_type=Answer
        )

    [event] = [e for e in _log_events(capsys.readouterr().out) if e["event"] == "llm_call_failed"]
    assert event["error_type"] == "LLMRateLimitError"
    assert event["retryable"] is True
