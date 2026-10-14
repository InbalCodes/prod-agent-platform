"""Grounding check — layers 2 (detect) and 4 (degrade) of docs/adr/0005-grounding-policy.md.

EXERCISE (Phase 1a) — implement `validate_grounding`.
The executable spec is tests/unit/test_grounding.py.

Requirements:
- Every `Evidence.log_line_id` must be one of `available_ids` (the lines we actually sent).
- Unknown evidence is removed. `unknown_ids` lists the unknown IDs in order of first
  appearance, without duplicates.
- A hypothesis left with no evidence is removed — including one that had none to begin
  with: an unsupported claim is not grounded. Count removals in `removed_hypotheses`.
- If no hypotheses remain, the cleaned report's status is "inconclusive".
- The input report is never mutated.
- Pure function: no I/O, no logging. The caller decides whether to log, retry or degrade.
"""

from collections.abc import Collection

from pydantic import BaseModel

from agent_platform.agent.report import Hypothesis, InvestigationReport


class GroundingResult(BaseModel):
    report: InvestigationReport  # the cleaned report
    unknown_ids: list[str]
    removed_hypotheses: int

    @property
    def is_grounded(self) -> bool:
        return not self.unknown_ids and self.removed_hypotheses == 0


def validate_grounding(
    report: InvestigationReport, available_ids: Collection[str]
) -> GroundingResult:

    valid_ids = set(available_ids)
    cleaned_report = report.model_copy(deep=True)

    unknown_ids: list[str] = []
    removed_hypotheses = 0
    valid_hypotheses: list[Hypothesis] = []

    for hypothesis in cleaned_report.hypotheses:
        valid_evidence = []

        for evidence in hypothesis.evidence:
            if evidence.log_line_id in valid_ids:
                valid_evidence.append(evidence)
            else:
                unknown_ids.append(evidence.log_line_id)

        hypothesis.evidence = valid_evidence
        if not valid_evidence:
            removed_hypotheses += 1
        else:
            valid_hypotheses.append(hypothesis)

    cleaned_report.hypotheses = valid_hypotheses
    if not valid_hypotheses:
        cleaned_report.status = "inconclusive"

    unique_unknown_ids = list(dict.fromkeys(unknown_ids))

    return GroundingResult(
        report=cleaned_report,
        unknown_ids=unique_unknown_ids,
        removed_hypotheses=removed_hypotheses,
    )
