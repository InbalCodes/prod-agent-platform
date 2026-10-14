"""Phase 1a: deterministic investigation workflow (docs/adr/0003, 0005).

Code decides the steps — fetch logs, one structured model call, grounding check, at most
one corrective retry. The model never chooses what to look at; that is Phase 1b.
"""

import asyncio
import time

import structlog
from pydantic import BaseModel

from agent_platform.agent.grounding import GroundingResult, validate_grounding
from agent_platform.agent.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_grounding_correction,
    build_user_message,
)
from agent_platform.agent.report import InvestigationReport
from agent_platform.llm.client import LLMClient, LLMResult
from agent_platform.llm.errors import LLMError
from agent_platform.tools.logs import LogQuery, LogSearchResult, LogStore

log = structlog.get_logger(__name__)


class InvestigationTimeoutError(Exception):
    """The whole investigation exceeded its time budget."""


class InvestigationRun(BaseModel):
    report: InvestigationReport
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


class WorkflowInvestigator:
    def __init__(self, llm: LLMClient, logs: LogStore, timeout_s: float) -> None:
        self._llm = llm
        self._logs = logs
        self._timeout_s = timeout_s

    async def investigate(self, issue: str, service: str | None = None) -> InvestigationRun:
        start = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout_s):
                with structlog.contextvars.bound_contextvars(prompt_version=PROMPT_VERSION):
                    run = await self._run(issue, service, start)
        except TimeoutError:
            log.warning("investigation_timeout", timeout_s=self._timeout_s)
            raise InvestigationTimeoutError(
                f"investigation exceeded {self._timeout_s}s budget"
            ) from None

        log.info(
            "investigation_completed",
            **run.model_dump(exclude={"report"}),
            status=run.report.status,
            hypotheses=len(run.report.hypotheses),
        )
        return run

    async def _run(self, issue: str, service: str | None, start: float) -> InvestigationRun:
        query = LogQuery(service=service, min_level="INFO")
        logs = await self._logs.search(query)
        available_ids = {line.id for line in logs.lines}
        user = build_user_message(issue, query, logs)

        first = await self._generate(user)
        calls = [first]
        first_grounding = validate_grounding(first.parsed, available_ids)
        final_grounding = first_grounding
        retry_attempted = False

        if not first_grounding.is_grounded:
            retry_attempted = True
            log.warning(
                "grounding_violation",
                unknown_ids=first_grounding.unknown_ids,
                removed_hypotheses=first_grounding.removed_hypotheses,
            )
            correction = build_grounding_correction(
                first_grounding.unknown_ids, first_grounding.removed_hypotheses
            )
            try:
                retry = await self._generate(user + correction)
            except LLMError as exc:
                # Degrade: the cleaned first report is still usable.
                log.warning("grounding_retry_failed", error_type=type(exc).__name__)
            else:
                calls.append(retry)
                final_grounding = validate_grounding(retry.parsed, available_ids)

        return _build_run(
            calls,
            first=first_grounding,
            final=final_grounding,
            retry_attempted=retry_attempted,
            logs=logs,
            start=start,
        )

    async def _generate(self, user: str) -> LLMResult[InvestigationReport]:
        return await self._llm.generate_structured(
            system=SYSTEM_PROMPT, user=user, output_type=InvestigationReport
        )


def _build_run(
    calls: list[LLMResult[InvestigationReport]],
    *,
    first: GroundingResult,
    final: GroundingResult,
    retry_attempted: bool,
    logs: LogSearchResult,
    start: float,
) -> InvestigationRun:
    costs = [call.cost_usd for call in calls]
    return InvestigationRun(
        # Always the *cleaned* report: ungrounded evidence never reaches the user.
        report=final.report,
        prompt_version=PROMPT_VERSION,
        model=calls[-1].model,
        llm_calls=len(calls),
        input_tokens=sum(call.usage.input_tokens for call in calls),
        output_tokens=sum(call.usage.output_tokens for call in calls),
        cost_usd=None if None in costs else round(sum(c for c in costs if c is not None), 6),
        latency_ms=round((time.perf_counter() - start) * 1000, 2),
        log_lines_sent=len(logs.lines),
        logs_truncated=logs.truncated,
        first_attempt_grounded=first.is_grounded,
        grounding_retry_used=retry_attempted,
        final_grounded=final.is_grounded,
    )
