"""Telemetry decorator for any LLMClient.

Every model call — any provider — produces exactly one `llm_call` or `llm_call_failed`
log line with the same fields. Adapters stay free of logging and cost logic.
"""

import time
from collections.abc import Sequence
from typing import Any

import structlog
from pydantic import BaseModel

from agent_platform.llm.client import (
    Conversation,
    LLMClient,
    LLMResult,
    ToolResult,
    ToolSpec,
    Turn,
    Usage,
)
from agent_platform.llm.errors import LLMError
from agent_platform.llm.pricing import estimate_cost_usd

log = structlog.get_logger(__name__)

TOOL_TURN = "tool_turn"  # `output_type` value for model calls inside a tool loop


class InstrumentedLLMClient:
    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner

    @property
    def model(self) -> str:
        return self._inner.model

    async def generate_structured[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        output_type: type[T],
        max_tokens: int = 8192,
    ) -> LLMResult[T]:
        start = time.perf_counter()
        try:
            result = await self._inner.generate_structured(
                system=system, user=user, output_type=output_type, max_tokens=max_tokens
            )
        except LLMError as exc:
            self._log_failure(exc, start, output_type=output_type.__name__)
            raise

        latency_ms, cost_usd = self._log_success(
            start,
            model=result.model,
            usage=result.usage,
            stop_reason=result.stop_reason,
            provider_request_id=result.provider_request_id,
            output_type=output_type.__name__,
        )
        return result.model_copy(update={"latency_ms": latency_ms, "cost_usd": cost_usd})

    def start_conversation(
        self, *, system: str, user: str, tools: Sequence[ToolSpec]
    ) -> Conversation:
        return self._inner.start_conversation(system=system, user=user, tools=tools)

    async def next_turn(self, conversation: Conversation, *, max_tokens: int = 8192) -> Turn:
        start = time.perf_counter()
        try:
            turn = await self._inner.next_turn(conversation, max_tokens=max_tokens)
        except LLMError as exc:
            self._log_failure(exc, start, output_type=TOOL_TURN)
            raise

        latency_ms, cost_usd = self._log_success(
            start,
            model=turn.model,
            usage=turn.usage,
            stop_reason=turn.stop_reason,
            provider_request_id=turn.provider_request_id,
            output_type=TOOL_TURN,
            tool_calls=len(turn.tool_calls),
        )
        return turn.model_copy(update={"latency_ms": latency_ms, "cost_usd": cost_usd})

    def add_tool_results(self, conversation: Conversation, results: Sequence[ToolResult]) -> None:
        self._inner.add_tool_results(conversation, results)

    def _log_failure(self, exc: LLMError, start: float, *, output_type: str) -> None:
        log.warning(
            "llm_call_failed",
            model=self.model,
            output_type=output_type,
            error_type=type(exc).__name__,
            retryable=exc.retryable,
            latency_ms=_elapsed_ms(start),
        )

    def _log_success(
        self,
        start: float,
        *,
        model: str,
        usage: Usage,
        stop_reason: str | None,
        provider_request_id: str | None,
        output_type: str,
        **extra: Any,
    ) -> tuple[float, float | None]:
        latency_ms = _elapsed_ms(start)
        cost_usd = estimate_cost_usd(model, usage)
        if cost_usd is None:
            log.warning("llm_price_unknown", model=model)

        log.info(
            "llm_call",
            model=model,
            output_type=output_type,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            stop_reason=stop_reason,
            provider_request_id=provider_request_id,
            **extra,
        )
        return latency_ms, cost_usd


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
