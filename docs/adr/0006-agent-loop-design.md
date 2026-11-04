# ADR-0006: Agent loop — two-phase (gather, then synthesize), own loop over our Protocol

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

The 1a baseline showed the workflow's structural limit: the code chooses what to search,
so on `checkout-upstream-timeouts` the root cause (in `payments-gateway`) is never seen.
Phase 1b lets the model choose its searches. Constraints: one provider today, a second
later (ADR-0002); one telemetry contract (ADR-0004); a 50 s investigation deadline;
Opus 5.5 cannot force a specific tool call, and its thinking blocks must be replayed
unchanged (append-only history).

## Decision

1. **Own manual loop over `LLMClient`**, not the SDK's Tool Runner.
2. **Opaque, adapter-owned `Conversation`.** The loop sees only normalized `ToolCall` /
   `ToolResult` / `Turn`; provider-native history (incl. thinking blocks) never leaves the adapter.
3. **Two phases:** (a) a bounded tool loop gathers log lines; (b) the 1a synthesis path
   (`generate_structured` + grounding + one corrective retry) writes the report from the
   collected lines. Hitting a loop limit still runs synthesis; `inconclusive` is decided there.
4. **Tool surface** (`search_logs`):

   | Field | Who decides | Enforcement |
   |---|---|---|
   | `service` | model, from a per-investigation allowlist | checked in code; unknown and forbidden get the *same* error |
   | `min_level` | model, enum | schema + validation |
   | `contains` | model, ≤ 200 chars | validation |
   | `since` / `until` | model may only narrow | clamped to the investigation window |
   | `limit` | code | not exposed |

   The allowlist is given in the investigation context (small, known list) — no `list_services` tool.
5. **Bounds:** `max_steps`, `max_tool_calls`, and a time reserve for synthesis inside the
   existing deadline. Every `tool_use` gets a `tool_result`, including refused ones.

## Alternatives

- **SDK Tool Runner** — least code; but Anthropic-only (beta) and bypasses `InstrumentedLLMClient`.
  The right default for a single-provider product.
- **`submit_report` terminal tool** — one call fewer, but the model may end without calling it
  (forced `tool_choice` is unavailable). To be compared later on measured quality/cost/latency.
- **Provider-neutral message model** — would drop or corrupt provider-specific blocks.

## Trade-offs

- An extra model call (synthesis) per run; in exchange the report path is the already-tested 1a code.
- Grounding now checks against the union of lines *returned by tool calls*, not lines the code chose.

## Consequences

- Run metadata gains trajectory fields (steps, tool calls, tool errors, services searched, loop stop reason).
- Evals gain trajectory dimensions (did it search the right service; how many calls).
- Deadline math (≈10–17 s per call) limits the loop to ~2–3 steps; to be measured, not assumed.
