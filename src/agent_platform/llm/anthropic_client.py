"""Anthropic adapter for LLMClient (docs/adr/0004-llm-client-protocol.md).

EXERCISE (Phase 1a) — implement `AnthropicClient.generate_structured`.
The executable spec is tests/unit/test_anthropic_client.py.

Requirements:
1. One call to `self._client.messages.parse(...)` with: model, max_tokens, system, a single
   user message, `output_format=output_type`, and `output_config={"effort": self._effort}`.
   The SDK turns the Pydantic model into a JSON Schema (constrained decoding), merges it
   into `output_config`, and validates the response back into `output_type`.
2. Map the response to `LLMResult`: `parsed_output`, `model`, `stop_reason`, usage
   (the cache token fields may be None -> 0), and `_request_id` -> `provider_request_id`.
3. No usable output -> `LLMOutputError`: stop_reason "refusal" or "max_tokens",
   or `parsed_output` is None.
4. Translate SDK exceptions — no `anthropic.*` exception may escape this class:
     APITimeoutError                              -> LLMTimeoutError
     RateLimitError                               -> LLMRateLimitError
                                                     (retry_after_s from the `retry-after`
                                                     header when it is a number, else None)
     APIConnectionError, APIStatusError >= 500    -> LLMUnavailableError  (includes 529 overloaded)
     any other APIStatusError                     -> LLMRequestError
   Mind the class hierarchy: APITimeoutError is a subclass of APIConnectionError.
5. Chain the original exception (`raise ... from exc`), so stack traces keep the SDK error.

No logging, timing or cost here — InstrumentedLLMClient does that for every provider.
"""

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    RateLimitError,
)
from anthropic.types import MessageParam, ToolParam
from pydantic import BaseModel, ValidationError

from agent_platform.llm.client import (
    Conversation,
    Effort,
    LLMResult,
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
    Usage,
)
from agent_platform.llm.errors import (
    LLMOutputError,
    LLMRateLimitError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None

    try:
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return seconds
    except ValueError:
        return None


@contextmanager
def _translated_errors() -> Iterator[None]:
    """Map SDK exceptions to LLMError. Shared by every call this adapter makes."""
    try:
        yield
    except APITimeoutError as exc:
        raise LLMTimeoutError("Anthropic request timed out") from exc

    except RateLimitError as exc:
        retry_after = _parse_retry_after(exc.response.headers.get("retry-after"))
        raise LLMRateLimitError(
            "Anthropic request rate limited", retry_after_s=retry_after
        ) from exc

    except APIConnectionError as exc:
        raise LLMUnavailableError("Anthropic connection failed") from exc

    except APIStatusError as exc:
        if exc.status_code >= 500:
            raise LLMUnavailableError(f"Anthropic server error: {exc.status_code}") from exc
        raise LLMRequestError(f"Anthropic request failed: {exc.status_code}") from exc


def _usage(usage: Any) -> Usage:
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_input_tokens=usage.cache_read_input_tokens or 0,
        cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
    )


@dataclass
class _AnthropicConversation(Conversation):
    system: str
    tools: list[ToolParam]
    # Append-only: assistant turns are stored exactly as returned (incl. thinking blocks).
    messages: list[MessageParam] = field(default_factory=list)


class AnthropicClient:
    def __init__(self, client: AsyncAnthropic, model: str, effort: Effort = "medium") -> None:
        self._client = client
        self._model = model
        self._effort = effort

    @property
    def model(self) -> str:
        return self._model

    async def generate_structured[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        output_type: type[T],
        max_tokens: int = 8192,
    ) -> LLMResult[T]:

        try:
            with _translated_errors():
                response = await self._client.messages.parse(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_format=output_type,
                    output_config={"effort": self._effort},
                )
        except ValidationError as exc:
            # Constraints the API cannot enforce (e.g. confidence ge/le) are validated
            # client-side by the SDK; a violation is unusable output, not a crash.
            raise LLMOutputError(f"Anthropic {self._model} output failed validation") from exc

        # Validate output
        if response.parsed_output is None or response.stop_reason in ("refusal", "max_tokens"):
            raise LLMOutputError(
                f"Anthropic {self._model} produced no usable output "
                f"(stop_reason={response.stop_reason})"
            )

        return LLMResult(
            parsed=response.parsed_output,
            model=response.model,
            stop_reason=response.stop_reason,
            provider_request_id=response._request_id,
            usage=_usage(response.usage),
        )

    # --- Tool conversations (Phase 1b, ADR-0006) -----------------------------------

    def start_conversation(
        self, *, system: str, user: str, tools: Sequence[ToolSpec]
    ) -> Conversation:
        return _AnthropicConversation(
            system=system,
            tools=[
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ],
            messages=[{"role": "user", "content": user}],
        )

    async def next_turn(self, conversation: Conversation, *, max_tokens: int = 8192) -> Turn:
        conv = _own(conversation)
        with _translated_errors():
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=conv.system,
                tools=conv.tools,
                messages=conv.messages,
                output_config={"effort": self._effort},
            )
        if response.stop_reason in ("refusal", "max_tokens"):
            # A truncated turn may hold a half-written tool call; never execute it.
            raise LLMOutputError(
                f"Anthropic {self._model} turn unusable (stop_reason={response.stop_reason})"
            )

        conv.messages.append({"role": "assistant", "content": response.content})
        texts = [block.text for block in response.content if block.type == "text"]
        return Turn(
            tool_calls=[
                ToolCall(id=block.id, name=block.name, input=dict(block.input))
                for block in response.content
                if block.type == "tool_use"
            ],
            text="\n".join(texts) or None,
            model=response.model,
            usage=_usage(response.usage),
            stop_reason=response.stop_reason,
            provider_request_id=response._request_id,
        )

    def add_tool_results(self, conversation: Conversation, results: Sequence[ToolResult]) -> None:
        _own(conversation).messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in results
                ],
            }
        )


def _own(conversation: Conversation) -> _AnthropicConversation:
    if not isinstance(conversation, _AnthropicConversation):
        raise TypeError("conversation was not created by AnthropicClient")
    return conversation
