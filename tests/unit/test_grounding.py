"""Spec for the grounding exercise (src/agent_platform/agent/grounding.py)."""

from agent_platform.agent.grounding import validate_grounding
from agent_platform.agent.report import Evidence, Hypothesis, InvestigationReport

AVAILABLE = {"L1", "L2", "L3"}


def _hypothesis(*log_ids: str, root_cause: str = "deploy broke it") -> Hypothesis:
    return Hypothesis(
        root_cause=root_cause,
        category="deployment_regression",
        confidence=0.8,
        evidence=[Evidence(log_line_id=i, why_relevant="...") for i in log_ids],
    )


def _report(*hypotheses: Hypothesis) -> InvestigationReport:
    return InvestigationReport(
        summary="...",
        status="conclusive",
        hypotheses=list(hypotheses),
        next_steps=["roll back"],
    )


def test_fully_grounded_report_is_unchanged() -> None:
    report = _report(_hypothesis("L1", "L2"))

    result = validate_grounding(report, AVAILABLE)

    assert result.is_grounded
    assert result.unknown_ids == []
    assert result.removed_hypotheses == 0
    assert result.report == report


def test_unknown_evidence_is_removed_and_reported() -> None:
    report = _report(_hypothesis("L1", "L999"))

    result = validate_grounding(report, AVAILABLE)

    assert not result.is_grounded
    assert result.unknown_ids == ["L999"]
    assert [e.log_line_id for e in result.report.hypotheses[0].evidence] == ["L1"]
    assert result.report.status == "conclusive"


def test_unknown_ids_are_deduplicated_in_order_of_appearance() -> None:
    report = _report(_hypothesis("X2", "L1", "X1"), _hypothesis("X1", "L2", "X2"))

    result = validate_grounding(report, AVAILABLE)

    assert result.unknown_ids == ["X2", "X1"]


def test_hypothesis_without_remaining_evidence_is_removed() -> None:
    report = _report(
        _hypothesis("L999", root_cause="made up"),
        _hypothesis("L2", root_cause="real"),
    )

    result = validate_grounding(report, AVAILABLE)

    assert [h.root_cause for h in result.report.hypotheses] == ["real"]
    assert result.removed_hypotheses == 1


def test_hypothesis_without_any_evidence_is_not_grounded() -> None:
    report = _report(_hypothesis(root_cause="no evidence at all"), _hypothesis("L1"))

    result = validate_grounding(report, AVAILABLE)

    assert not result.is_grounded
    assert result.unknown_ids == []
    assert result.removed_hypotheses == 1


def test_report_becomes_inconclusive_when_nothing_remains() -> None:
    report = _report(_hypothesis("L998"), _hypothesis("L999"))

    result = validate_grounding(report, AVAILABLE)

    assert result.report.hypotheses == []
    assert result.report.status == "inconclusive"


def test_input_report_is_not_mutated() -> None:
    report = _report(_hypothesis("L1", "L999"), _hypothesis("L998"))
    before = report.model_dump()

    validate_grounding(report, AVAILABLE)

    assert report.model_dump() == before


def test_empty_inconclusive_report_is_grounded() -> None:
    report = InvestigationReport(summary="...", status="inconclusive", hypotheses=[], next_steps=[])

    result = validate_grounding(report, AVAILABLE)

    assert result.is_grounded
    assert result.report.status == "inconclusive"
