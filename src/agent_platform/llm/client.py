"""Provider-neutral LLM contract (see docs/adr/0004-llm-client-protocol.md)."""

from typing import Protocol

from pydantic import BaseModel


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
