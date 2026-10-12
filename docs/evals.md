# Evals

> Status: planned for Phase 1. No evals exist yet.

## Principles

- Evals are built alongside the first AI feature, not after it.
- **Measure before setting thresholds.** Phase 1 records a baseline; targets come from data.
- Prefer **deterministic evaluators**; use LLM-as-judge only where determinism is impossible,
  and validate the judge against human labels.

## Phase 1 plan

- **Dataset:** `evals/datasets/incidents_v0.jsonl`, 5–8 hand-written incidents over fixture logs.
  Each case: `issue`, `expected_root_cause_category`, `must_cite_log_ids`, `expected_tools`.
- **Includes one security case:** a log line containing a prompt-injection attempt.
- **Deterministic evaluators:**
  - groundedness — every cited `log_line_id` exists in the fixtures
  - citation recall — `must_cite_log_ids` ⊆ cited ids
  - root-cause category match
  - tool usage — expected tools called, no out-of-scope calls
  - policy — injection instruction not followed
- **Operational dimensions per run:** latency, input/output tokens, cost.
- **Comparison:** workflow (1a) vs agent loop (1b) on the same dataset version ([ADR-0003](adr/0003-workflow-baseline-before-agent-loop.md)).
- Results are written to `evals/results/` (not versioned); summaries recorded here.

## Results

_None yet._
