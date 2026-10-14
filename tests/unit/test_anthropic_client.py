"""Spec for the Anthropic adapter exercise (src/agent_platform/llm/anthropic_client.py).

No network: the SDK client is replaced by a stub whose `messages.parse` returns a
canned response or raises a real SDK exception.
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx2
import pytest
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from agent_platform.llm.anthropic_client import AnthropicClient
from agent_platform.llm.client import LLMClient
from agent_platform.llm.errors import (
    LLMError,
    LLMOutputError,
    LLMRateLimitError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class Answer(BaseModel):
    value: str


OK = Answer(value="ok")


def _response(parsed: Answer | None = OK, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        parsed_output=parsed,
        model="claude-opus-5-5",
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=1200,
            output_tokens=300,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
        ),
        _request_id="req_abc123",
    )


class _StubMessages:
    def __init__(self, outcome: SimpleNamespace | Exception) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _client(outcome: SimpleNamespace | Exception) -> tuple[AnthropicClient, _StubMessages]:
    messages = _StubMessages(outcome)
    sdk = cast(AsyncAnthropic, SimpleNamespace(messages=messages))
    return AnthropicClient(sdk, model="claude-opus-5-5", effort="medium"), messages


async def _call(client: AnthropicClient) -> Any:
    return await client.generate_structured(system="sys", user="usr", output_type=Answer)


def _status_error(cls: type[anthropic.APIStatusError], status: int, **headers: str) -> Exception:
    response = httpx2.Response(status, headers=headers, request=REQUEST)
    return cls("error", response=response, body=None)


def test_satisfies_the_llm_client_protocol() -> None:
    client: LLMClient = _client(_response())[0]  # checked by mypy, structurally
    assert client.model == "claude-opus-5-5"


@pytest.mark.anyio
async def test_calls_parse_with_model_effort_and_output_type() -> None:
    client, messages = _client(_response())

    await _call(client)

    [kwargs] = messages.calls
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["system"] == "sys"
    assert kwargs["messages"] == [{"role": "user", "content": "usr"}]
    assert kwargs["output_format"] is Answer
    assert kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["max_tokens"] == 8192


@pytest.mark.anyio
async def test_maps_response_to_result() -> None:
    client, _ = _client(_response())

    result = await _call(client)

    assert result.parsed == Answer(value="ok")
    assert result.model == "claude-opus-5-5"
    assert result.stop_reason == "end_turn"
    assert result.provider_request_id == "req_abc123"
    assert result.usage.input_tokens == 1200
    assert result.usage.output_tokens == 300
    assert result.usage.cache_read_input_tokens == 0
    assert result.usage.cache_creation_input_tokens == 0


@pytest.mark.anyio
@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
async def test_unusable_stop_reason_is_an_output_error(stop_reason: str) -> None:
    client, _ = _client(_response(stop_reason=stop_reason))

    with pytest.raises(LLMOutputError):
        await _call(client)


@pytest.mark.anyio
async def test_missing_parsed_output_is_an_output_error() -> None:
    client, _ = _client(_response(parsed=None))

    with pytest.raises(LLMOutputError):
        await _call(client)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("make_error", "expected"),
    [
        (lambda: anthropic.APITimeoutError(request=REQUEST), LLMTimeoutError),
        (lambda: anthropic.APIConnectionError(request=REQUEST), LLMUnavailableError),
        (lambda: _status_error(anthropic.RateLimitError, 429), LLMRateLimitError),
        (lambda: _status_error(anthropic.InternalServerError, 500), LLMUnavailableError),
        (lambda: _status_error(anthropic.OverloadedError, 529), LLMUnavailableError),
        (lambda: _status_error(anthropic.BadRequestError, 400), LLMRequestError),
        (lambda: _status_error(anthropic.AuthenticationError, 401), LLMRequestError),
    ],
    ids=["timeout", "connection", "429", "500", "529", "400", "401"],
)
async def test_sdk_errors_are_translated(
    make_error: Callable[[], Exception], expected: type[LLMError]
) -> None:
    original = make_error()
    client, _ = _client(original)

    with pytest.raises(expected) as exc_info:
        await _call(client)

    assert type(exc_info.value) is expected
    assert exc_info.value.__cause__ is original


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("7", 7.0),
        ("1.5", 1.5),
        ("0", 0.0),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
        # float() accepts these; a sleep(retry_after) on them would hang or crash.
        ("inf", None),
        ("-inf", None),
        ("nan", None),
        ("-5", None),
        ("", None),
    ],
)
async def test_rate_limit_carries_numeric_retry_after(header: str, expected: float | None) -> None:
    client, _ = _client(_status_error(anthropic.RateLimitError, 429, **{"retry-after": header}))

    with pytest.raises(LLMRateLimitError) as exc_info:
        await _call(client)

    assert exc_info.value.retry_after_s == expected


@pytest.mark.anyio
async def test_rate_limit_without_retry_after_header() -> None:
    client, _ = _client(_status_error(anthropic.RateLimitError, 429))

    with pytest.raises(LLMRateLimitError) as exc_info:
        await _call(client)

    assert exc_info.value.retry_after_s is None
