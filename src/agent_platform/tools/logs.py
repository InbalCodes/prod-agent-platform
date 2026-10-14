"""Log search over a fixed set of log lines.

V0 reads JSONL fixtures into memory. The query/result contract is what matters:
it stays the same when the backend becomes a real log platform (CloudWatch, Loki, ...).
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR"]
_LEVEL_ORDER: dict[LogLevel, int] = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

MAX_RESULTS = 50


class LogLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    timestamp: datetime
    service: str
    level: LogLevel
    message: str
    attributes: dict[str, str] = Field(default_factory=dict)


class LogQuery(BaseModel):
    # forbid: an unknown filter (e.g. a typo from a model-generated call) is an error,
    # not a silently ignored field that returns everything.
    model_config = ConfigDict(extra="forbid")

    service: str | None = None
    min_level: LogLevel = "INFO"
    contains: str | None = Field(default=None, max_length=200)
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=MAX_RESULTS, ge=1, le=MAX_RESULTS)


class LogSearchResult(BaseModel):
    lines: list[LogLine]
    total_matches: int
    truncated: bool


class LogStore:
    def __init__(self, lines: Sequence[LogLine]) -> None:
        self._lines = sorted(lines, key=lambda line: line.timestamp)

    @classmethod
    def from_jsonl(cls, path: Path) -> "LogStore":
        with path.open(encoding="utf-8") as file:
            return cls([LogLine.model_validate_json(raw) for raw in file if raw.strip()])

    async def search(self, query: LogQuery) -> LogSearchResult:
        matches = [line for line in self._lines if _matches(line, query)]
        # Keep the most recent lines when truncating: the current state of an incident
        # matters more than its oldest lines. Output stays in chronological order.
        selected = matches[-query.limit :]
        return LogSearchResult(
            lines=selected,
            total_matches=len(matches),
            truncated=len(matches) > len(selected),
        )


def _matches(line: LogLine, query: LogQuery) -> bool:
    if query.service is not None and line.service != query.service:
        return False
    if _LEVEL_ORDER[line.level] < _LEVEL_ORDER[query.min_level]:
        return False
    if query.since is not None and line.timestamp < query.since:
        return False
    if query.until is not None and line.timestamp > query.until:
        return False
    if query.contains is not None:
        needle = query.contains.lower()
        haystack = [line.message, *line.attributes.values()]
        if not any(needle in text.lower() for text in haystack):
            return False
    return True
