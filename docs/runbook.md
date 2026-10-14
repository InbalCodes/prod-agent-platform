# Runbook

Each entry: **Symptom → How to confirm → Likely causes → Mitigation → Follow-up.**

## Finding all logs for one failing request

1. Get the `request_id` from the `X-Request-ID` response header or the error body.
2. Filter logs by `request_id` — every line of that request carries it, including the
   `http_request` access line (status, duration) and any `unhandled_exception` with stack trace.

## Service not receiving traffic after deploy

- **Confirm:** `GET /health/live` → 200 but `GET /health/ready` → 503.
- **Likely cause:** startup (lifespan) did not complete; check `startup` log line and errors before it.
- **Note:** a failing readiness probe should stop traffic, not restart the container. Only liveness failures restart.

## `POST /v1/investigations` returns 503 / 504 / 502

The status tells you which layer failed; the `llm_error_response` log line (same `request_id`) has the exact error.

| Status | `error_type` in logs | Meaning | First checks |
|---|---|---|---|
| 503 "not configured" | — (`llm_not_configured` at startup) | No `APP_ANTHROPIC_API_KEY` | Secret injected? Only allowed in `local` |
| 503 + `Retry-After` | `LLMRateLimitError` | **We** exceeded provider quota | Rate of `llm_call` lines, tokens/request trend, retry storms (`llm_max_retries`) |
| 503 | `LLMUnavailableError` | Provider 5xx/529 or network | Provider status page; is it all requests or a spike? |
| 504 | `LLMTimeoutError` | One model call exceeded `APP_LLM_TIMEOUT_S` | `latency_ms` of recent `llm_call`s; did input size (`log_lines_sent`) grow? |
| 504 "time budget" | `investigation_timeout` | Whole run exceeded `APP_INVESTIGATION_TIMEOUT_S` | `grounding_retry_used` rate — retries double latency |
| 502 | `LLMOutputError` | Refusal, `max_tokens`, or unparseable output | `stop_reason` in the failure; prompt or model change recently? |
| 500 | `LLMRequestError` | Provider rejected the request (400/401/403) | Key revoked? Model name valid? Schema change in `InvestigationReport`? |

## Grounding violations rising

- **Confirm:** share of `investigation_completed` with `first_attempt_grounded=false`, and `grounding_violation` lines.
- **Likely causes:** prompt/model/effort change (check `prompt_version`, `model`), larger or truncated log input (`logs_truncated=true`).
- **Note:** final groundedness can stay at 100% while this rises — the retry hides it, and cost/latency rise instead (ADR-0005).

_More entries are added with each failure mode we introduce._
