from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_platform.tools.logs import LogLine, LogQuery, LogStore

FIXTURES = Path(__file__).parents[2] / "fixtures" / "logs"


def _line(
    id: str, minute: int, service: str = "checkout", level: str = "INFO", **attrs: str
) -> LogLine:
    return LogLine.model_validate(
        {
            "id": id,
            "timestamp": datetime(2026, 10, 13, 10, minute, tzinfo=UTC),
            "service": service,
            "level": level,
            "message": f"message {id}",
            "attributes": attrs,
        }
    )


@pytest.fixture
def store() -> LogStore:
    return LogStore(
        [
            _line("a", 3, level="ERROR", payment_method="wallet"),
            _line("b", 1, level="DEBUG"),
            _line("c", 2, service="inventory", level="WARN"),
            _line("d", 4, level="INFO"),
        ]
    )


@pytest.mark.anyio
async def test_filters_by_service_and_min_level(store: LogStore) -> None:
    result = await store.search(LogQuery(service="checkout", min_level="INFO"))

    assert [line.id for line in result.lines] == ["a", "d"]


@pytest.mark.anyio
async def test_results_are_chronological(store: LogStore) -> None:
    result = await store.search(LogQuery(min_level="DEBUG"))

    assert [line.id for line in result.lines] == ["b", "c", "a", "d"]


@pytest.mark.anyio
async def test_contains_matches_attributes_case_insensitively(store: LogStore) -> None:
    result = await store.search(LogQuery(contains="WALLET"))

    assert [line.id for line in result.lines] == ["a"]


@pytest.mark.anyio
async def test_truncation_keeps_most_recent_and_reports_it(store: LogStore) -> None:
    result = await store.search(LogQuery(min_level="DEBUG", limit=2))

    assert [line.id for line in result.lines] == ["a", "d"]
    assert result.total_matches == 4
    assert result.truncated


@pytest.mark.anyio
async def test_time_window(store: LogStore) -> None:
    result = await store.search(
        LogQuery(
            min_level="DEBUG",
            since=datetime(2026, 10, 13, 10, 2, tzinfo=UTC),
            until=datetime(2026, 10, 13, 10, 3, tzinfo=UTC),
        )
    )

    assert [line.id for line in result.lines] == ["c", "a"]


def test_query_rejects_unknown_fields_and_oversized_limits() -> None:
    with pytest.raises(ValidationError):
        LogQuery.model_validate({"servce": "checkout"})
    with pytest.raises(ValidationError):
        LogQuery(limit=10_000)


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.jsonl")), ids=lambda p: p.stem)
def test_fixture_files_are_valid_with_unique_ids(path: Path) -> None:
    store = LogStore.from_jsonl(path)
    ids = [line.id for line in store._lines]

    assert ids
    assert len(ids) == len(set(ids))
