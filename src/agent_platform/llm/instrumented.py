"""Telemetry decorator for any LLMClient.

Every model call — any provider — produces exactly one `llm_call` or `llm_call_failed`
log line with the same fields. Adapters stay free of logging and cost logic.
"""

import time

import structlog
from pydantic import BaseModel

from agent_platform.llm.client import LLMClient, LLMResult
from agent_platform.llm.errors import LLMError
from agent_platform.llm.pricing import estimate_cost_usd

log = structlog.get_logger(__name__)


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
            log.warning(
                "llm_call_failed",
                model=self.model,
                output_type=output_type.__name__,
                error_type=type(exc).__name__,
                retryable=exc.retryable,
                latency_ms=_elapsed_ms(start),
            )
            raise

        latency_ms = _elapsed_ms(start)
        cost_usd = estimate_cost_usd(result.model, result.usage)
        if cost_usd is None:
            log.warning("llm_price_unknown", model=result.model)

        log.info(
            "llm_call",
            model=result.model,
            output_type=output_type.__name__,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_input_tokens=result.usage.cache_read_input_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            stop_reason=result.stop_reason,
            provider_request_id=result.provider_request_id,
        )
        return result.model_copy(update={"latency_ms": latency_ms, "cost_usd": cost_usd})


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
