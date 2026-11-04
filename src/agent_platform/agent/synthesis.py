"""Report synthesis: one structured call, grounding check, at most one corrective retry.

Shared by the workflow (1a) and the agent's second phase (1b). See ADR-0005.
"""

from collections.abc import Collection
from dataclasses import dataclass

import structlog

from agent_platform.agent.grounding import GroundingResult, validate_grounding
from agent_platform.agent.prompts import SYSTEM_PROMPT, build_grounding_correction
from agent_platform.agent.report import InvestigationReport
from agent_platform.llm.client import LLMClient, LLMResult
from agent_platform.llm.errors import LLMError

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Synthesis:
    calls: list[LLMResult[InvestigationReport]]
    first: GroundingResult
    final: GroundingResult
    retry_attempted: bool


async def synthesize_report(
    llm: LLMClient, user_message: str, available_ids: Collection[str]
) -> Synthesis:
    first = await _generate(llm, user_message)
    calls = [first]
    first_grounding = validate_grounding(first.parsed, available_ids)
    final_grounding = first_grounding

    if not first_grounding.is_grounded:
        log.warning(
            "grounding_violation",
            unknown_ids=first_grounding.unknown_ids,
            removed_hypotheses=first_grounding.removed_hypotheses,
        )
        correction = build_grounding_correction(
            first_grounding.unknown_ids, first_grounding.removed_hypotheses
        )
        try:
            retry = await _generate(llm, user_message + correction)
        except LLMError as exc:
            # Degrade: the cleaned first report is still usable.
            log.warning("grounding_retry_failed", error_type=type(exc).__name__)
        else:
            calls.append(retry)
            final_grounding = validate_grounding(retry.parsed, available_ids)

    return Synthesis(
        calls=calls,
        first=first_grounding,
        final=final_grounding,
        retry_attempted=not first_grounding.is_grounded,
    )


async def _generate(llm: LLMClient, user: str) -> LLMResult[InvestigationReport]:
    return await llm.generate_structured(
        system=SYSTEM_PROMPT, user=user, output_type=InvestigationReport
    )
