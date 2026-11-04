"""Result of one investigation, shared by the workflow (1a) and the agent (1b)."""

import time
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from agent_platform.agent.report import InvestigationReport
from agent_platform.agent.synthesis import Synthesis
from agent_platform.llm.client import LLMResult, Turn

LoopStopReason = Literal["model_done", "max_steps", "max_tool_calls", "time_budget"]


class InvestigationTimeoutError(Exception):
    """The whole investigation exceeded its time budget."""


class InvestigationRun(BaseModel):
    report: InvestigationReport
    investigator: Literal["workflow", "agent"]
    prompt_version: str
    model: str
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: float
    log_lines_sent: int
    logs_truncated: bool
    first_attempt_grounded: bool
    grounding_retry_used: bool
    final_grounded: bool
    # Trajectory (agent only; zero/empty for the workflow).
    agent_steps: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    services_searched: list[str] = []
    loop_stop_reason: LoopStopReason | None = None


def build_run(
    *,
    investigator: Literal["workflow", "agent"],
    prompt_version: str,
    model: str,
    synthesis: Synthesis | None,
    turns: Sequence[Turn] = (),
    report: InvestigationReport | None = None,
    log_lines_sent: int,
    logs_truncated: bool,
    start: float,
    agent_steps: int = 0,
    tool_calls: int = 0,
    tool_errors: int = 0,
    services_searched: Sequence[str] = (),
    loop_stop_reason: LoopStopReason | None = None,
) -> InvestigationRun:
    """Aggregate cost/tokens over every model call (tool turns + synthesis calls).

    Pass `synthesis=None` with an explicit `report` when no synthesis call was made.
    """
    calls: list[Turn | LLMResult[InvestigationReport]] = [
        *turns,
        *(synthesis.calls if synthesis else []),
    ]
    costs = [call.cost_usd for call in calls]
    if synthesis is not None:
        report = synthesis.final.report  # always the *cleaned* report
    assert report is not None, "build_run needs a synthesis or an explicit report"

    return InvestigationRun(
        report=report,
        investigator=investigator,
        prompt_version=prompt_version,
        model=calls[-1].model if calls else model,
        llm_calls=len(calls),
        input_tokens=sum(call.usage.input_tokens for call in calls),
        output_tokens=sum(call.usage.output_tokens for call in calls),
        cost_usd=None if None in costs else round(sum(c for c in costs if c is not None), 6),
        latency_ms=round((time.perf_counter() - start) * 1000, 2),
        log_lines_sent=log_lines_sent,
        logs_truncated=logs_truncated,
        first_attempt_grounded=synthesis.first.is_grounded if synthesis else True,
        grounding_retry_used=synthesis.retry_attempted if synthesis else False,
        final_grounded=synthesis.final.is_grounded if synthesis else True,
        agent_steps=agent_steps,
        tool_calls=tool_calls,
        tool_errors=tool_errors,
        services_searched=list(services_searched),
        loop_stop_reason=loop_stop_reason,
    )
