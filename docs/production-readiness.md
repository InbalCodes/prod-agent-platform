# Production Readiness Checklist

Legend: ✅ done & verified · 🟡 in progress · ⬜ not started · ➖ not applicable yet (phase noted)

## Architecture
- ✅ App factory, no import-time side effects
- ✅ Typed configuration, fail-fast validation
- ⬜ Clear separation: API / orchestration / LLM client / tools (Phase 1)
- ⬜ Architecture doc + ADRs kept current with every phase

## Deployment
- ➖ Container image (end of Phase 1)
- ➖ IaC, environments dev/staging/prod (V5)
- ➖ CI/CD pipeline with eval gate (V4–V5)

## Reliability
- ✅ Liveness vs readiness separated
- 🟡 Graceful shutdown hook (lifespan) — not yet verified with SIGTERM (needs a container)
- ✅ Timeouts on every outbound call: per-attempt LLM timeout + hard investigation deadline
- ⬜ Bounded agent loop (Phase 1b)
- ⬜ Retries with backoff + jitter, retry budget (V3)
- ➖ Idempotency, DLQ, checkpointing (V3)

## Security
- ✅ No internal details in error responses
- ✅ Untrusted request headers validated before logging (request ID)
- ✅ Secrets typed as `SecretStr`, never rendered; required outside `local`
- ⬜ Prompt-injection eval case (Phase 1)
- ➖ AuthN/AuthZ, rate limiting (before any deployment)
- ➖ Tool risk levels + human approval (V2)

## Observability
- ✅ Structured JSON logs, one format for all loggers
- ✅ Request ID on every log line and response
- ✅ Access log with status and duration
- ✅ Per model call: model, prompt_version, tokens, latency, cost, provider request id
- ⬜ Per tool call: args, latency, result count, error (Phase 1)
- ➖ Distributed tracing (V4)

## Evals
- ⬜ Versioned incident dataset (Phase 1)
- ⬜ Deterministic evaluators: grounding, tool usage (Phase 1)
- ⬜ Baseline recorded for workflow vs agent (Phase 1)
- ➖ Thresholds + CI gate (V4)

## Performance
- ⬜ No blocking calls in async code (ruff ASYNC rules enabled)
- ➖ Baseline latency measurements (Phase 1)

## Scaling
- ➖ Load test baseline (V6)

## Data
- ➖ Schema migrations, backups (V1)

## Cost
- ✅ Cost per model call computed from usage (versioned price table)
- ➖ Cost per successful task (Phase 1b onward)

## Operations
- ⬜ Runbook entries for each new failure mode

## Disaster / failure scenarios
- ✅ LLM timeout / 429 / 5xx / malformed output mapped to explicit statuses and tested (runbook)
