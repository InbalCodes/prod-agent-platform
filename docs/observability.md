# Observability

## Current (Phase 0): structured logs

All logs — application and third-party (uvicorn) — go through one structlog formatter.
JSON when `APP_LOG_JSON=true`, console otherwise.

Every line has: `timestamp` (ISO, UTC), `level`, `logger`, `event`, and `request_id` when inside a request.

### Request ID

- Accepted from `X-Request-ID` if it matches `[A-Za-z0-9._-]{1,128}`, otherwise generated (uuid4 hex).
- Stored in a `ContextVar` → added to every log line automatically.
- Returned in the `X-Request-ID` response header and in every problem+json error body.

### Access log contract

One line per request:

| Field | Example |
|---|---|
| `event` | `http_request` |
| `method` | `GET` |
| `path` | `/health/live` |
| `status_code` | `200` |
| `duration_ms` | `1.42` |

uvicorn's own access log is disabled to avoid duplicates without request IDs.

### Model-call log contract (Phase 1a)

Emitted by `InstrumentedLLMClient` for every provider — adapters never log.

| Event | Fields |
|---|---|
| `llm_call` | `model`, `output_type`, `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `latency_ms`, `cost_usd`, `stop_reason`, `provider_request_id` |
| `llm_call_failed` | `model`, `output_type`, `error_type`, `retryable`, `latency_ms` |
| `llm_price_unknown` | `model` — cost could not be computed; update `llm/pricing.py` |

Model calls inside the agent loop log `output_type="tool_turn"` plus `tool_calls` (count).

### Tool-call log contract (Phase 1b)

| Event | Fields |
|---|---|
| `tool_call` | `tool`, `args` (model-chosen input), `latency_ms`, `result_count`, `error` (null on success) |

`args` are logged as the model sent them — including refused ones — so misuse attempts are visible.

`provider_request_id` is the provider's own request ID — the key for a support ticket with the provider.
Cost is an estimate from the versioned price table (`PRICES_AS_OF`), not billing data.

## Planned

- **Phase 1a** — `prompt_version` and grounding fields (`grounding_violations_first_attempt`,
  `grounding_retry_used`) on the investigation-level log line.
- **Phase 1b** — tool-call log: `tool`, `args`, `latency_ms`, `result_count`, `error`.
  Field names chosen to map onto OpenTelemetry GenAI semantic conventions later.
- **V4** — distributed tracing (OpenTelemetry) + LLM tracing backend (Langfuse / LangSmith — decision pending ADR).
- Application observability vs LLM/agent observability will be documented here once both exist.
