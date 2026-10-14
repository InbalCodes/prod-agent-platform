# Production Engineering Support Agent Platform

An AI agent platform that investigates production incidents — e.g. *"Checkout API started
returning HTTP 500 after the latest deployment"* — by gathering evidence from logs, code,
documentation and tickets, and proposing an evidence-backed root cause.

The emphasis is on what makes an agent production-grade, not on the agent itself:
**Evals, observability, reliability, security, scale and cost** are first-class concerns.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 — Walking skeleton | FastAPI service, config, structured logging, request IDs, health, error handling | ✅ done |
| 1a — Workflow baseline | `search_logs` → one LLM call → structured `InvestigationReport` | ⏳ |
| 1b — Agent loop | Bounded tool-calling loop, compared against 1a on the same eval set | ⏳ |

Roadmap and architecture evolution: [docs/architecture.md](docs/architecture.md).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                                         # create .venv, install deps
cp .env.example .env
uv run uvicorn agent_platform.main:create_app --factory --reload
```

```bash
uv run python -m pytest           # tests
uv run ruff check .      # lint
uv run ruff format .     # format
uv run python -m mypy src tests   # type check
```

> **Windows note:** Smart App Control blocks the unsigned Python builds that uv downloads
> (`DLL load failed ... Application Control policy`). Use a python.org install instead:
> `uv venv --python <path-to-python.exe>` then `uv sync`. For the same reason, run tools as
> `python -m <tool>` when their `.exe` shim is blocked.

## Documentation

| Doc | Purpose |
|---|---|
| [architecture.md](docs/architecture.md) | Current architecture and planned evolution |
| [adr/](docs/adr/) | Architecture Decision Records |
| [production-readiness.md](docs/production-readiness.md) | Production readiness checklist |
| [evals.md](docs/evals.md) | Evaluation strategy, datasets, thresholds |
| [observability.md](docs/observability.md) | Logging, tracing, metrics contracts |
| [security.md](docs/security.md) | Threat model and controls |
| [scaling.md](docs/scaling.md) | Load tests and scaling decisions |
| [cost.md](docs/cost.md) | Cost model and cost per successful task |
| [runbook.md](docs/runbook.md) | Operational playbooks |
| [learning-backlog.md](docs/learning-backlog.md) | Concepts encountered and confidence |
