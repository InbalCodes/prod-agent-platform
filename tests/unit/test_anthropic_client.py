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
from pydantic import BaseModel, ValidationError

from agent_platform.llm.anthropic_client import AnthropicClient
from agent_platform.llm.client import Conversation, LLMClient, ToolCall, ToolResult, ToolSpec
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
        # Snapshot `messages`: the adapter passes its live, growing history list.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    create = parse  # tool turns use messages.create; same stub behavior


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


# --- Phase 1b additions -------------------------------------------------------------


@pytest.mark.anyio
async def test_client_side_validation_error_is_an_output_error() -> None:
    try:
        Answer.model_validate({})
    except ValidationError as exc:
        validation_error = exc
    client, _ = _client(validation_error)

    with pytest.raises(LLMOutputError) as exc_info:
        await _call(client)

    assert exc_info.value.__cause__ is validation_error


def _turn_response(*blocks: SimpleNamespace, stop_reason: str = "tool_use") -> SimpleNamespace:
    response = _response(stop_reason=stop_reason)
    response.content = list(blocks)
    return response


THINKING = SimpleNamespace(type="thinking", thinking="", signature="sig-opaque")
TEXT = SimpleNamespace(type="text", text="Checking the gateway.")
TOOL_USE = SimpleNamespace(
    type="tool_use", id="toolu_1", name="search_logs", input={"service": "checkout"}
)
SPEC = ToolSpec(name="search_logs", description="d", input_schema={"type": "object"})


@pytest.mark.anyio
async def test_next_turn_maps_tool_calls_and_text() -> None:
    client, _ = _client(_turn_response(THINKING, TEXT, TOOL_USE))
    conversation = client.start_conversation(system="sys", user="usr", tools=[SPEC])

    turn = await client.next_turn(conversation)

    assert turn.tool_calls == [
        ToolCall(id="toolu_1", name="search_logs", input={"service": "checkout"})
    ]
    assert turn.text == "Checking the gateway."
    assert turn.stop_reason == "tool_use"
    assert turn.usage.input_tokens == 1200
    assert turn.provider_request_id == "req_abc123"


@pytest.mark.anyio
async def test_history_is_append_only_and_replays_blocks_unchanged() -> None:
    first = _turn_response(THINKING, TOOL_USE)
    client, messages = _client(first)
    conversation = client.start_conversation(system="sys", user="usr", tools=[SPEC])

    await client.next_turn(conversation)
    client.add_tool_results(conversation, [ToolResult(tool_call_id="toolu_1", content="{}")])
    messages.outcome = _turn_response(TEXT, stop_reason="end_turn")
    await client.next_turn(conversation)

    sent = messages.calls[1]["messages"]
    assert sent[0] == {"role": "user", "content": "usr"}
    assert sent[1]["role"] == "assistant"
    assert sent[1]["content"] is first.content  # the provider's own blocks, untouched
    assert sent[2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}", "is_error": False}
        ],
    }
    assert messages.calls[1]["tools"] == [
        {"name": "search_logs", "description": "d", "input_schema": {"type": "object"}}
    ]


@pytest.mark.anyio
async def test_truncated_turn_is_an_output_error_and_not_recorded() -> None:
    client, messages = _client(_turn_response(TOOL_USE, stop_reason="max_tokens"))
    conversation = client.start_conversation(system="sys", user="usr", tools=[SPEC])

    with pytest.raises(LLMOutputError):
        await client.next_turn(conversation)

    messages.outcome = _turn_response(TEXT, stop_reason="end_turn")
    await client.next_turn(conversation)
    assert len(messages.calls[1]["messages"]) == 1  # the truncated turn was never appended


@pytest.mark.anyio
async def test_next_turn_translates_sdk_errors() -> None:
    client, _ = _client(_status_error(anthropic.RateLimitError, 429, **{"retry-after": "3"}))
    conversation = client.start_conversation(system="sys", user="usr", tools=[SPEC])

    with pytest.raises(LLMRateLimitError) as exc_info:
        await client.next_turn(conversation)

    assert exc_info.value.retry_after_s == 3.0


def test_rejects_a_conversation_from_another_client() -> None:
    client, _ = _client(_response())

    with pytest.raises(TypeError):
        client.add_tool_results(Conversation(), [])
