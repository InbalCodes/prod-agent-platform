"""Phase 1b: agent investigation — gather with tools, then synthesize (docs/adr/0006).

EXERCISE (Phase 1b) — implement `AgentInvestigator.investigate`.
The executable spec is tests/unit/test_agent_loop.py.

Requirements:
1. Deadline. The whole run is bounded by `timeout_s` (asyncio.timeout), exactly like
   WorkflowInvestigator; on expiry raise InvestigationTimeoutError.

2. Gathering phase. Start a conversation with AGENT_SYSTEM_PROMPT,
   build_agent_user_message(...) and `self._tool.spec`. Then loop:
   a. Before each model call, stop with:
        "time_budget" if the time left is below `synthesis_reserve_s`
        "max_steps"   if `max_steps` model calls were already made
   b. One `next_turn`. A turn without tool calls -> stop with "model_done".
   c. Answer EVERY tool call of the turn, in the same order, with ONE add_tool_results call:
        - unknown tool name            -> error result, not executed
        - beyond the max_tool_calls budget -> error result, not executed
        - otherwise                    -> self._tool.execute(call)
      Tool calls within one turn may run concurrently.
   d. If the budget is used up after answering a turn -> stop with "max_tool_calls".

3. Evidence. Keep every line returned by searches, deduplicated by id, in chronological
   order. Record the services successfully searched, in first-seen order.

4. Synthesis phase.
   - No lines collected -> do NOT call the model: build an "inconclusive" report in code
     (deterministic code where an LLM adds nothing).
   - Otherwise: synthesize_report(llm, build_evidence_message(...), ids of collected lines).

5. Result. Return build_run(investigator="agent", prompt_version=PROMPT_ID, ...) including
   the turns and the trajectory: agent_steps (model calls in the loop), tool_calls (calls
   the model requested), tool_errors (error results returned), services_searched,
   loop_stop_reason. Log `investigation_completed` like the workflow does.
"""

import asyncio
import time
from collections.abc import Collection

import structlog

from agent_platform.agent.prompts import (
    AGENT_PROMPT_VERSION,
    AGENT_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_agent_user_message,
    build_evidence_message,
)
from agent_platform.agent.report import InvestigationReport
from agent_platform.agent.run import (
    InvestigationRun,
    InvestigationTimeoutError,
    LoopStopReason,
    ToolTrace,
    build_run,
)
from agent_platform.agent.synthesis import synthesize_report
from agent_platform.llm.client import LLMClient, ToolResult, Turn
from agent_platform.tools.logs import LogLine, LogStore
from agent_platform.tools.search_logs import SearchLogsTool

log = structlog.get_logger(__name__)

PROMPT_ID = f"{AGENT_PROMPT_VERSION}+{PROMPT_VERSION}"


class AgentInvestigator:
    def __init__(
        self,
        llm: LLMClient,
        logs: LogStore,
        *,
        allowed_services: Collection[str] | None = None,
        timeout_s: float = 50.0,
        max_steps: int = 4,
        max_tool_calls: int = 6,
        synthesis_reserve_s: float = 20.0,
    ) -> None:
        self._allowed = sorted(
            allowed_services if allowed_services is not None else logs.services()
        )
        self._tool = SearchLogsTool(
            logs,
            allowed_services=self._allowed,
        )
        self._llm = llm
        self._timeout_s = timeout_s
        self._max_steps = max_steps
        self._max_tool_calls = max_tool_calls
        self._synthesis_reserve_s = synthesis_reserve_s

    async def investigate(
        self,
        issue: str,
        service: str | None = None,
    ) -> InvestigationRun:

        start = time.perf_counter()
        deadline = start + self._timeout_s

        agent_steps = 0
        tool_calls = 0
        executed_tool_calls = 0
        tool_errors = 0

        turns: list[Turn] = []
        lines_by_id: dict[str, LogLine] = {}
        services_searched: list[str] = []
        tool_trace: list[ToolTrace] = []

        logs_truncated = False

        loop_stop_reason: LoopStopReason = "model_done"

        try:
            async with asyncio.timeout(self._timeout_s):
                # 1. Start conversation
                conversation = self._llm.start_conversation(
                    system=AGENT_SYSTEM_PROMPT,
                    user=build_agent_user_message(
                        issue,
                        service,
                        self._allowed,
                        self._max_tool_calls,
                    ),
                    tools=[self._tool.spec],
                )

                # 2. Gathering phase
                while True:
                    remaining = deadline - time.perf_counter()

                    if remaining < self._synthesis_reserve_s:
                        loop_stop_reason = "time_budget"
                        break

                    if agent_steps >= self._max_steps:
                        loop_stop_reason = "max_steps"
                        break

                    # Ask the model for the next turn
                    turn = await self._llm.next_turn(conversation)

                    agent_steps += 1
                    turns.append(turn)

                    if not turn.tool_calls:
                        loop_stop_reason = "model_done"
                        break

                    results = []
                    returned_ids: dict[str, list[str]] = {}  # tool_call_id -> line ids

                    # 3. Answer every tool call
                    for call in turn.tool_calls:
                        tool_calls += 1

                        # Unknown tool
                        if call.name != self._tool.spec.name:
                            results.append(
                                ToolResult(
                                    tool_call_id=call.id,
                                    content="Unknown tool",
                                    is_error=True,
                                )
                            )
                            tool_errors += 1
                            continue

                        # Tool execution budget exhausted
                        if executed_tool_calls >= self._max_tool_calls:
                            results.append(
                                ToolResult(
                                    tool_call_id=call.id,
                                    content="Tool call budget exceeded",
                                    is_error=True,
                                )
                            )
                            tool_errors += 1
                            continue

                        # Execute authorized tool
                        executed_tool_calls += 1

                        try:
                            execution = await self._tool.execute(call)

                        except Exception:
                            log.exception(
                                "tool_execution_failed",
                                tool=call.name,
                                tool_call_id=call.id,
                            )

                            results.append(
                                ToolResult(
                                    tool_call_id=call.id,
                                    content="Tool execution failed",
                                    is_error=True,
                                )
                            )
                            tool_errors += 1
                            continue

                        results.append(execution.result)

                        if execution.result.is_error:
                            tool_errors += 1
                            continue

                        returned_ids[call.id] = [line.id for line in execution.lines]

                        # 4. Collect evidence, deduplicated by ID
                        for line in execution.lines:
                            lines_by_id.setdefault(line.id, line)

                        # Track successfully searched services
                        if (
                            execution.service is not None
                            and execution.service not in services_searched
                        ):
                            services_searched.append(execution.service)

                        logs_truncated |= execution.truncated

                    # Trace in the same order as the calls, including refused ones.
                    tool_trace.extend(
                        ToolTrace(
                            tool=call.name,
                            args=call.input,
                            is_error=result.is_error,
                            line_ids=returned_ids.get(call.id, []),
                        )
                        for call, result in zip(turn.tool_calls, results, strict=True)
                    )

                    # Every tool_use must receive a tool_result.
                    # One call, preserving the original order.
                    self._llm.add_tool_results(
                        conversation,
                        results,
                    )

                    # Stop only after answering the entire turn
                    if executed_tool_calls >= self._max_tool_calls:
                        loop_stop_reason = "max_tool_calls"
                        break

                # 5. Prepare chronological evidence
                collected_lines = sorted(
                    lines_by_id.values(),
                    key=lambda line: (line.timestamp, line.id),
                )

                # 6. Synthesis phase
                synthesis = None
                report = None

                if collected_lines:
                    evidence_message = build_evidence_message(
                        issue,
                        collected_lines,
                        loop_stop_reason,
                    )

                    synthesis = await synthesize_report(
                        self._llm,
                        evidence_message,
                        set(lines_by_id),
                    )

                else:
                    # No evidence: no additional LLM call.
                    report = InvestigationReport(
                        summary=(
                            "No log evidence was collected to support a root cause determination."
                        ),
                        status="inconclusive",
                        hypotheses=[],
                        next_steps=[
                            "Verify the service and investigation time window.",
                            "Check log availability and search permissions.",
                        ],
                        security_findings=[],
                    )

                # 7. Build the complete investigation result
                run = build_run(
                    investigator="agent",
                    prompt_version=PROMPT_ID,
                    model=self._llm.model,
                    synthesis=synthesis,
                    turns=turns,
                    report=report,
                    log_lines_sent=len(collected_lines),
                    log_line_ids_sent=[line.id for line in collected_lines],
                    tool_trace=tool_trace,
                    logs_truncated=logs_truncated,
                    start=start,
                    agent_steps=agent_steps,
                    tool_calls=tool_calls,
                    tool_errors=tool_errors,
                    services_searched=services_searched,
                    loop_stop_reason=loop_stop_reason,
                )

                log.info(
                    "investigation_completed",
                    investigator="agent",
                    model=run.model,
                    agent_steps=run.agent_steps,
                    tool_calls=run.tool_calls,
                    tool_errors=run.tool_errors,
                    services_searched=run.services_searched,
                    loop_stop_reason=run.loop_stop_reason,
                    log_lines_sent=run.log_lines_sent,
                    status=run.report.status,
                    llm_calls=run.llm_calls,
                    latency_ms=run.latency_ms,
                    cost_usd=run.cost_usd,
                    final_grounded=run.final_grounded,
                )

                return run

        except TimeoutError as exc:
            raise InvestigationTimeoutError("Agent investigation exceeded its deadline") from exc
