# Learning Backlog

Concepts encountered while building. Confidence is self-assessed (1 = heard of it, 5 = can teach it).

| Concept | Why it matters | Status | Implemented? | Confidence (1–5) |
|---|---|---|---|---|
| Python packaging: uv, pyproject, venv, src layout | Reproducible builds; tests import the installed package, not cwd | Introduced | Yes (Phase 0) | |
| ASGI + uvicorn vs FastAPI | Server/framework split; workers & GIL determine how we scale | Introduced | Yes (Phase 0) | |
| async Python vs Node event loop | One blocking call in `async def` freezes every request | Introduced | Partially | |
| GIL and processes vs threads | Why Python scales CPU with processes | Introduced | No | |
| Pydantic / pydantic-settings | Single schema for API, tool definitions and LLM output validation | Exercise | Phase 0 exercise | |
| `contextvars` (≈ AsyncLocalStorage) | Request-scoped context without parameter drilling | Exercise | Phase 0 exercise | |
| FastAPI lifespan | Where pools/clients are created and closed | Introduced | Yes (Phase 0) | |
| Liveness vs readiness | Wrong probes cause restart cascades or traffic to unready pods | Introduced | Yes (Phase 0) | |
| Graceful shutdown | Deploys must not kill in-flight work | Introduced | Partially | |
| Structured logging | Logs are queryable data, not text | Introduced | Yes (Phase 0) | |
| problem+json (RFC 9457) | Stable error contract; no internal leakage | Introduced | Yes (Phase 0) | |
| Log injection via untrusted headers | Attacker-controlled values in logs can forge entries | Exercise | Phase 0 exercise | |
| Workflow vs agent | Agents cost more and vary more; justify with measurements | Discussed | Phase 1 | |
| Sync vs async jobs: when to switch | Infra timeouts, HITL, durability, load leveling | Discussed | V3 | |
| LLM framework landscape (LangChain, LangGraph, …) | Know what each abstraction buys and costs | Discussed | V2 decision | |
