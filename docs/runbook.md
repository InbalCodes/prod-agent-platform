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

_More entries are added with each failure mode we introduce (LLM 429, timeouts, queue backlog, …)._
