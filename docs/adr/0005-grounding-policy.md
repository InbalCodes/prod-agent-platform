# ADR-0005: Grounding policy — layered defense, and never let a retry hide the signal

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

Structured outputs guarantee the report's *shape*, not its *truth*: a schema-valid report
can cite a `log_line_id` that was never given to the model. A citation that does not exist
is a hallucination, and the whole value of the report is that its claims are checkable.

## Decision

| Layer | Mechanism | Phase |
|---|---|---|
| 1. Prevent | Per-request schema where `log_line_id` is an `enum` of the IDs actually provided (constrained decoding) | Added as the first *measured* change after the baseline |
| 2. Detect | `validate_grounding()` always runs, for every provider | 1a |
| 3. Recover | At most **one** corrective retry that names the invalid IDs | 1a |
| 4. Degrade | Drop unknown evidence; drop hypotheses left without evidence; `status="inconclusive"` if none remain | 1a |
| 5. Observe | Log and report `grounding_violations_first_attempt` and `grounding_retry_used`; evals score first attempt and final result separately | 1a |

## Alternatives

- **Reject the whole report** — safe but throws away valid findings and wastes the call.
- **Always retry until grounded** — unbounded cost/latency; hides model quality regressions.
- **Strip silently** — cheap, but the user and the evals never learn the model fabricated evidence.

## Trade-offs

- A retry doubles cost and latency for the affected runs — acceptable only because it is bounded and measured.
- Layer 1 may add latency (per-request schema compilation) and has enum-size limits — to be measured, not assumed.
- Grounded ≠ relevant: an existing but irrelevant line passes all layers. Relevance is measured by the evals (`must_cite_log_ids`).

## Consequences

A rising `grounding_violations_first_attempt` rate after a prompt/model change is a
regression even when final groundedness stays at 100%.
