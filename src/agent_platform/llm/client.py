"""Provider-neutral LLM contract (see docs/adr/0004 and 0006)."""

from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel

# Reasoning depth vs. cost/latency. Provider-neutral name; adapters map it.
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class LLMResult[T: BaseModel](BaseModel):
    parsed: T
    model: str
    usage: Usage
    stop_reason: str | None
    provider_request_id: str | None
    # Filled in by InstrumentedLLMClient, not by provider adapters.
    latency_ms: float | None = None
    cost_usd: float | None = None


# --- Tool calling (Phase 1b) -------------------------------------------------------


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]


class ToolResult(BaseModel):
    tool_call_id: str
    content: str
    is_error: bool = False


class Turn(BaseModel):
    """One model call inside a tool conversation."""

    tool_calls: list[ToolCall]
    text: str | None
    model: str
    usage: Usage
    stop_reason: str | None
    provider_request_id: str | None
    latency_ms: float | None = None
    cost_usd: float | None = None


class Conversation:
    """Opaque, adapter-owned conversation state.

    Callers never read or edit its contents: providers may require their own blocks
    (e.g. thinking blocks) to be replayed unchanged, so history is append-only and
    only the adapter that created it knows its shape.
    """


class LLMClient(Protocol):
    @property
    def model(self) -> str: ...

    async def generate_structured[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        output_type: type[T],
        max_tokens: int = 8192,
    ) -> LLMResult[T]:
        """Return `output_type` produced by one model call, or raise an `LLMError`."""
        ...

    def start_conversation(
        self, *, system: str, user: str, tools: Sequence[ToolSpec]
    ) -> Conversation: ...

    async def next_turn(self, conversation: Conversation, *, max_tokens: int = 8192) -> Turn:
        """One model call; appends the model's reply to the conversation."""
        ...

    def add_tool_results(self, conversation: Conversation, results: Sequence[ToolResult]) -> None:
        """Append results for *every* tool call of the last turn, in one message."""
        ...
