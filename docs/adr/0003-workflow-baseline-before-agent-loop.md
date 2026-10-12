# ADR-0003: Build a deterministic workflow baseline before the agent loop

- **Status:** Accepted
- **Date:** 2026-10-11

## Context

"Agent vs deterministic code" is a central design question. Without a baseline, any
claim that an agent is worth its extra cost, latency and variance is unfalsifiable.

## Decision

- **Phase 1a — workflow:** code decides the steps (`search_logs` → one LLM call → report).
- **Phase 1b — agent loop:** the model decides which tool calls to make (bounded steps).
- Both run against the **same versioned eval set**; compare root-cause accuracy,
  groundedness, latency, tokens and cost.

## Alternatives

- **Agent loop only** — less code, but no evidence it beats something simpler.
- **Workflow only** — cheapest, but cannot follow evidence across services.

## Trade-offs

Some duplicated effort in exchange for a measured, defensible decision and the first
use of the regression-comparison mechanism.

## Consequences

The likely outcome is a hybrid: deterministic steps where the path is known, model-driven
steps where the next action depends on evidence. Decided by numbers, recorded in a follow-up ADR.
