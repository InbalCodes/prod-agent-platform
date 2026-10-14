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
from typing import Literal

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    RateLimitError,
)
from pydantic import BaseModel

from agent_platform.llm.client import LLMResult, Usage
from agent_platform.llm.errors import (
    LLMOutputError,
    LLMRateLimitError,
    LLMRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)

Effort = Literal["low", "medium", "high", "xhigh", "max"]


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
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=output_type,
                output_config={"effort": self._effort},
            )
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
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_read_input_tokens=response.usage.cache_read_input_tokens or 0,
                cache_creation_input_tokens=response.usage.cache_creation_input_tokens or 0,
            ),
        )
