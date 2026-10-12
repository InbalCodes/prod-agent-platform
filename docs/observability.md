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

## Planned

- **Phase 1** — model-call log: `model`, `prompt_version`, `input_tokens`, `output_tokens`,
  `latency_ms`, `cost_usd`, `stop_reason`; tool-call log: `tool`, `args`, `latency_ms`,
  `result_count`, `error`. Field names chosen to map onto OpenTelemetry GenAI semantic conventions later.
- **V4** — distributed tracing (OpenTelemetry) + LLM tracing backend (Langfuse / LangSmith — decision pending ADR).
- Application observability vs LLM/agent observability will be documented here once both exist.
