# Architecture

## Current state — Phase 0 (walking skeleton)

A single FastAPI process with no AI and no external dependencies. Its job is to make
every later feature observable and debuggable from day one.

```text
HTTP ──► uvicorn (ASGI server)
           │
           ▼
         ServerErrorMiddleware        ← renders unhandled exceptions as problem+json
           │
         RequestContextMiddleware     ← request_id (contextvars) + access log
           │
         ExceptionMiddleware          ← HTTPException / validation → problem+json
           │
         Router ── /health/live
                └─ /health/ready      ← 503 until lifespan startup completes
```

Key properties:

- **App factory** (`create_app(settings)`), no import-time side effects; tests inject their own `Settings`.
- **Typed configuration** from `APP_*` env vars; invalid config fails at startup.
- **One log format** for our logs and third-party logs (JSON in deployed envs), every line carries `request_id`.
- **Stable error contract**: RFC 9457 `application/problem+json`, no internal details leaked.

## Next — Phase 1 (first vertical slice)

```text
POST /v1/investigations {"issue": "..."}
        │
        ▼
Investigator ──► LLMClient (Protocol) ──► Anthropic SDK  (OpenAI later)
        │                               └─ FakeLLMClient (tests)
        └──────► search_logs tool ──► fixtures/logs/*.jsonl
        │
        ▼
InvestigationReport (Pydantic): summary, hypotheses, evidence[log_line_id], next_steps
```

- 1a: deterministic workflow (code decides the steps). See [ADR-0003](adr/0003-workflow-baseline-before-agent-loop.md).
- 1b: bounded agent loop (model decides the steps), compared against 1a on the same eval set.

## Planned evolution

| Version | Adds | Trigger for adding it |
|---|---|---|
| V0 | FastAPI + LLM + one tool | — |
| V1 | RAG, PostgreSQL + pgvector, Docker Compose | Documentation becomes an evidence source |
| V2 | MCP/tools, state, human approval | First write action (MEDIUM/HIGH risk) |
| V3 | Queue + workers, reliability patterns | Runs exceed infra timeouts / need durability / wait for humans |
| V4 | Evals in CI, tracing (OTel + LLM tracing) | Regressions must be caught before deploy |
| V5 | AWS deployment, IaC, CI/CD | — |
| V6 | Load testing, scaling | Baseline measurements exist |
| V7 | Security hardening, cost optimization | Measured cost/risk profile exists |

## Phase log

Phases are the incremental steps inside a version. Each row says what was actually delivered.

| Phase | Version | Status | What we did |
|---|---|---|---|
| 0 — Walking skeleton | V0 | ✅ done | FastAPI app factory, fail-fast settings, JSON logging with request IDs, problem+json errors, liveness/readiness, 23 tests. No AI. |
| 1a — Workflow baseline | V0 | 🟡 in progress | Code decides the steps: `search_logs` → one structured-output LLM call → grounding check, plus model-call telemetry and the first eval run. |
| 1b — Agent loop | V0 | ⏳ planned | Model decides the steps in a bounded tool-calling loop; compared against 1a on the same eval set. |

## Decisions

See [adr/](adr/).
