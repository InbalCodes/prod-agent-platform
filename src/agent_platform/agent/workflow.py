"""Phase 1a: deterministic investigation workflow (docs/adr/0003, 0005).

Code decides the steps — fetch logs, then synthesis (one structured model call, grounding
check, at most one corrective retry). The model never chooses what to look at.
"""

import asyncio
import time

import structlog

from agent_platform.agent.prompts import PROMPT_VERSION, build_user_message
from agent_platform.agent.run import InvestigationRun, InvestigationTimeoutError, build_run
from agent_platform.agent.synthesis import synthesize_report
from agent_platform.llm.client import LLMClient
from agent_platform.tools.logs import LogQuery, LogStore

log = structlog.get_logger(__name__)

__all__ = ["InvestigationRun", "InvestigationTimeoutError", "WorkflowInvestigator"]


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
        synthesis = await synthesize_report(
            self._llm,
            build_user_message(issue, query, logs),
            available_ids={line.id for line in logs.lines},
        )
        return build_run(
            investigator="workflow",
            prompt_version=PROMPT_VERSION,
            model=self._llm.model,
            synthesis=synthesis,
            log_lines_sent=len(logs.lines),
            logs_truncated=logs.truncated,
            start=start,
            # Recorded so service coverage is comparable with the agent.
            services_searched=[service] if service else sorted(self._logs.services()),
        )
