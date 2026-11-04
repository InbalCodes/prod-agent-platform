# Production Engineering Support Agent Platform

An LLM agent that investigates production incidents — *"checkout started returning HTTP 500
after the latest deployment"* — by searching logs and producing an evidence-backed root-cause
report in which every claim cites a log line.

This is a learning project built in small, measured phases. The agent itself is the easy part.
The focus is on what makes it production-grade: **evals, grounding, observability, bounded
execution, security and cost**. Every design decision is recorded as an ADR, and every
change in behaviour is measured on an eval set before it is believed.

## What it does today

```text
POST /v1/investigations {"issue": "...", "service": "checkout"}
        │
        ├─ Workflow (1a): code fetches logs → one structured LLM call
        └─ Agent    (1b): model calls search_logs in a bounded loop → same synthesis step
                │
                ▼
        grounding check ── every cited log_line_id must exist in what the model saw
                │           (one corrective retry, then ungrounded hypotheses are dropped)
                ▼
        InvestigationReport: summary, ranked hypotheses + evidence, next steps,
                             security_findings (prompt injections found in the logs)
```

Highlights:

- **Provider-agnostic LLM layer.** An `LLMClient` Protocol, an Anthropic adapter, and a
  telemetry decorator that logs tokens, cost, latency and the provider request ID for every
  call. Provider errors are translated into one error hierarchy with retryability.
- **Grounding as a layered defence** ([ADR-0005](docs/adr/0005-grounding-policy.md)).
  The defence detects fabricated citations, recovers from them once, and degrades when that
  fails. It also reports the first-attempt grounding rate, so retries cannot hide
  fabrication.
- **A bounded agent loop** ([ADR-0006](docs/adr/0006-agent-loop-design.md)).
  - Limits: max steps, a tool-call budget, and a time reserve for synthesis inside the
    request deadline.
  - The tool surface is an allowlist. Unknown and forbidden services return the same error.
    Time windows are clamped and limits are set by code, not by the model.
- **Untrusted input handling.** Log content is treated as data, never as instructions. One
  eval case contains a prompt-injection attack hidden inside a log line.
- **Deterministic evals.**
  - The evals score root cause (with partial credit), citation recall, grounding, service
    coverage and security, plus the cost per *successful* task, failures included.
  - Each run is recorded with its git commit, prompt version and model.

## Results so far

Three hand-written incident cases, `claude-opus-5-5`, effort `medium`
(details in [docs/evals.md](docs/evals.md)):

| | Workflow (1a, 3 repeats) | Agent (1b, 1 run) |
|---|---|---|
| Success rate | 0.667 | 1.0 |
| Root cause | 0.833 | 1.0 |
| Latency P50 | 9.7 s | 21.7 s |
| Cost per successful task | $0.050 | $0.077 |

The agent wins on the case where the root cause lives in an *upstream* service the reporter
never mentioned. The workflow cannot see that service's logs, so its answer is capped. That
win costs about 1.5× more and takes about 2× longer.

Three cases are anecdotes, not statistics. A repeated agent run is the next step.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 — Walking skeleton | FastAPI app factory, typed config, JSON logs with request IDs, problem+json errors, health checks | ✅ |
| 1a — Workflow baseline | LLM client layer, grounding, eval harness, baseline with variance | ✅ |
| 1b — Agent loop | Bounded tool-calling loop, trajectory metrics, comparison against 1a | 🟡 |

Roadmap (RAG, human approval for write actions, async workers, tracing, AWS deployment):
[docs/architecture.md](docs/architecture.md).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14.

```bash
uv sync
cp .env.example .env        # set APP_ANTHROPIC_API_KEY for real model calls
uv run uvicorn agent_platform.main:create_app --factory --reload
```

```bash
uv run python -m pytest                     # unit tests (no network, fake LLM)
uv run ruff check . && uv run ruff format --check .
uv run python -m mypy src tests evals       # strict
```

Evals call the real API and **cost money**. Always set a cap:

```bash
uv run python -m evals.run --max-cost-usd 0.50
uv run python -m evals.run --investigator agent --repeat 3 --max-cost-usd 1.00
```

> **Windows note:** Smart App Control may block the Python builds that uv downloads. Use a
> python.org install (`uv venv --python <path-to-python.exe>`), and run tools as
> `python -m <tool>` if their `.exe` shim is blocked.

## Project layout

```text
src/agent_platform/
  api/        HTTP routes
  core/       logging, request context, error mapping
  llm/        LLMClient Protocol, Anthropic adapter, telemetry decorator, fake, pricing
  tools/      log store and the search_logs tool
  agent/      workflow, agent loop, synthesis, grounding, prompts, report schema
evals/        dataset, deterministic evaluators, runner
fixtures/     synthetic incident logs
docs/         architecture, ADRs, evals, observability, security, cost, runbook
```

## Documentation

| Doc | Purpose |
|---|---|
| [architecture.md](docs/architecture.md) | Current architecture, phase log, planned evolution |
| [adr/](docs/adr/) | Architecture Decision Records |
| [evals.md](docs/evals.md) | Eval design, scored dimensions, results history |
| [production-readiness.md](docs/production-readiness.md) | Readiness checklist |
| [observability.md](docs/observability.md) | Log contracts for requests, model calls and tool calls |
| [security.md](docs/security.md) | Threat model and controls |
| [cost.md](docs/cost.md) | Cost model |
| [scaling.md](docs/scaling.md) | Scaling decisions |
| [runbook.md](docs/runbook.md) | Operational playbooks |
| [learning-backlog.md](docs/learning-backlog.md) | Concepts encountered along the way |
