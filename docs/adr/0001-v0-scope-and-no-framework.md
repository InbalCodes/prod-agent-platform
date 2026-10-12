# ADR-0001: V0 scope — synchronous API, no agent framework, no database

- **Status:** Accepted
- **Date:** 2026-10-11

## Context

We need a first working version that turns an incident description into an
evidence-backed answer, while learning the underlying mechanics (tool calling,
structured output, failure modes) rather than hiding them.

## Decision

- **Synchronous HTTP** request with a bounded run (max steps + overall timeout).
- **Provider SDK directly**, behind our own thin `LLMClient` Protocol. No LangChain / LangGraph.
- **No database, queue, Redis, MCP, auth or Docker Compose.** Logs come from local fixture files.
- Python service: FastAPI + uvicorn, Pydantic / pydantic-settings, structlog, managed with uv.

## Alternatives

- **LangChain / LangGraph from the start** — faster to a demo, but hides prompts, token usage
  and control flow exactly where we need visibility. Revisit in V2 when checkpoints,
  resume and human-approval interrupts are real requirements.
- **Async job + queue from the start** — correct for long runs, but V0 runs are short and
  bounded; a queue adds infrastructure without a problem to solve yet.

## Trade-offs

- We write ~40 lines of orchestration ourselves and own their bugs.
- A synchronous request loses work on client disconnect or deploy; acceptable while runs are short and cheap.

## Consequences

Move to async jobs when any of these becomes true (see V3):
P95 run duration approaches infrastructure timeouts (ALB 60s, API Gateway 29s);
a run must wait for human approval; losing a run mid-way is too expensive; provider rate
limits require load leveling.
