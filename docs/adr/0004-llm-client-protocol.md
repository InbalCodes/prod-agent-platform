# ADR-0004: `LLMClient` Protocol — structured generation first, telemetry as a decorator

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

ADR-0002 commits us to a provider abstraction. Phase 1a needs exactly one capability:
one model call that returns a validated Pydantic object. Phase 1b will need tool calling;
a second provider (OpenAI) comes later. Telemetry (latency, tokens, cost) must be
identical for every provider.

## Decision

1. **Protocol shape (option B):** one method,
   `generate_structured(system, user, output_type) -> LLMResult[T]`.
   Each adapter uses its provider's native structured-output mechanism.
   `LLMResult` carries `parsed`, `model`, normalized `Usage`, `stop_reason`, `provider_request_id`.
2. **Provider errors are translated** into our own `LLMError` hierarchy
   (`LLMTimeoutError`, `LLMRateLimitError`, `LLMUnavailableError`, `LLMOutputError`,
   `LLMRequestError`), each with a `retryable` flag. No SDK exception crosses the adapter boundary.
3. **Telemetry lives in `InstrumentedLLMClient`**, a decorator that wraps any `LLMClient`.
   Adapters only translate; they never log or compute cost.
4. Tool calling is added to the Protocol in Phase 1b; message/tool normalization across
   providers is designed only when the second provider is implemented.

## Alternatives

- **(A) text-only `complete()`** — parsing outside the client loses the provider's
  constrained decoding, which is the main reliability benefit of structured outputs.
- **(C) full provider-neutral message + tool model now** — designed against one provider
  whose tool format we have not used yet. A wrong abstraction is more expensive than
  temporary duplication, because new code grows around it.

## Trade-offs

- The Protocol will change in 1b. Python `Protocol`s are structural (like TS interfaces),
  so adding a method is a local change, not a hierarchy refactor.
- One extra wrapper layer; in exchange, every provider gets the same `llm_call` log contract for free.

## Consequences

- Tests use `FakeLLMClient` (scripted results / errors) — no network.
- Retry *policy* (how many attempts, which errors) belongs to the caller, not the adapter;
  the adapter only reports `retryable`. SDK-level retries stay at their default for now
  and will be revisited with the reliability work (V3).
