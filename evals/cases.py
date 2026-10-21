"""Eval case contract and dataset loading.

A dataset is versioned like code: changing expectations changes the dataset version
(file name), so results from different versions are never compared silently.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_platform.agent.report import RootCauseCategory
from agent_platform.tools.logs import LogStore

FIXTURES_DIR = Path("fixtures/logs")


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    log_fixture: str = Field(description="File name under fixtures/logs/")
    issue: str = Field(min_length=10, description="How a human would report the incident")
    service: str | None = Field(default=None, description="Service the reporter names, if any")

    # Root cause, judged on the top-ranked hypothesis.
    expected_categories: list[RootCauseCategory] = Field(min_length=1)
    partial_categories: list[RootCauseCategory] = Field(
        default_factory=list, description="Defensible but incomplete answers (partial credit)"
    )
    expected_status: Literal["conclusive", "inconclusive"] = "conclusive"

    # Evidence the report must cite (relevance), independent of grounding.
    must_cite_log_ids: list[str] = Field(default_factory=list)

    # Security / policy: case-insensitive substrings that must not appear in any
    # hypothesis root_cause or next step (quoting them in the summary is allowed).
    forbidden_phrases: list[str] = Field(default_factory=list)

    notes: str = ""


def load_dataset(path: Path, fixtures_dir: Path = FIXTURES_DIR) -> list[EvalCase]:
    """Load and validate a JSONL dataset. Fails loudly on a broken eval, not a broken model."""
    cases = [
        EvalCase.model_validate_json(raw)
        for raw in path.read_text(encoding="utf-8").splitlines()
        if raw.strip()
    ]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate case ids")

    for case in cases:
        fixture = fixtures_dir / case.log_fixture
        if not fixture.exists():
            raise ValueError(f"{case.id}: fixture {fixture} does not exist")
        known_ids = {line.id for line in LogStore.from_jsonl(fixture).lines}
        missing = set(case.must_cite_log_ids) - known_ids
        if missing:
            raise ValueError(f"{case.id}: must_cite_log_ids not in fixture: {sorted(missing)}")
        overlap = set(case.expected_categories) & set(case.partial_categories)
        if overlap:
            raise ValueError(f"{case.id}: categories both expected and partial: {overlap}")
    return cases
