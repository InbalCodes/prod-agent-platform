# ADR-0002: LLM provider — Anthropic primary, behind an `LLMClient` Protocol

- **Status:** Accepted
- **Date:** 2026-10-11

## Context

The spec requires model replaceability. We have API access to both Anthropic and OpenAI.

## Decision

- Define a narrow `LLMClient` Protocol owned by us (messages in; text/tool calls/usage out).
- **Anthropic** is the first implementation.
- **OpenAI** is added as a second implementation (end of Phase 1 or V3).
- A `FakeLLMClient` with scripted responses is used in unit tests — no network in CI.

## Alternatives

- **Single provider, no abstraction** — simplest, but makes model comparison and fallback a rewrite.
- **Multi-provider library (LiteLLM, Pydantic AI)** — uniform API for free, but hides the
  provider differences we want to understand first.

## Trade-offs

A second real implementation is extra work, but it is what proves the abstraction is
right — one implementation only proves it compiles.

## Consequences

Enables: model A vs model B in the eval suite, provider fallback on 429/5xx, and cost
comparison per successful task.
