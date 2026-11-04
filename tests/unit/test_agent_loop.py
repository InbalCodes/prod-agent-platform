"""Spec for the agent loop exercise (src/agent_platform/agent/agent_loop.py)."""

import asyncio
from datetime import UTC, datetime

import pytest

from agent_platform.agent.agent_loop import PROMPT_ID, AgentInvestigator
from agent_platform.agent.report import Evidence, Hypothesis, InvestigationReport
from agent_platform.agent.run import InvestigationTimeoutError
from agent_platform.llm.client import Conversation, Turn
from agent_platform.llm.errors import LLMTimeoutError
from agent_platform.llm.fake import FakeConversation, FakeLLMClient, FakeTurn
from agent_platform.tools.logs import LogLine, LogStore

ALLOWED = ["checkout", "payments-gateway"]


def _line(id: str, minute: int, service: str) -> LogLine:
    return LogLine(
        id=id,
        timestamp=datetime(2026, 10, 13, 10, minute, tzinfo=UTC),
        service=service,
        level="ERROR",
        message=f"{service} error {id}",
    )


def _store() -> LogStore:
    return LogStore(
        [
            _line("c1", 1, "checkout"),
            _line("c2", 3, "checkout"),
            _line("p1", 0, "payments-gateway"),
            _line("p2", 2, "payments-gateway"),
            _line("s1", 0, "billing-secrets"),
        ]
    )


def _report(*log_ids: str) -> InvestigationReport:
    return InvestigationReport(
        summary="pool exhausted",
        status="conclusive",
        hypotheses=[
            Hypothesis(
                root_cause="db pool exhausted",
                category="resource_exhaustion",
                confidence=0.8,
                evidence=[Evidence(log_line_id=i, why_relevant="...") for i in log_ids],
            )
        ],
        next_steps=["inspect the pool"],
    )


def search(service: str, **args: object) -> tuple[str, dict[str, object]]:
    return ("search_logs", {"service": service, **args})


def _agent(fake: FakeLLMClient, **overrides: float) -> AgentInvestigator:
    options: dict[str, float] = {"timeout_s": 5, "synthesis_reserve_s": 0} | overrides
    return AgentInvestigator(
        fake,
        _store(),
        allowed_services=ALLOWED,
        timeout_s=options["timeout_s"],
        synthesis_reserve_s=options["synthesis_reserve_s"],
        max_steps=int(options.get("max_steps", 4)),
        max_tool_calls=int(options.get("max_tool_calls", 6)),
    )


def _conversation(fake: FakeLLMClient) -> FakeConversation:
    [conversation] = fake.conversations
    return conversation


# --- happy path ----------------------------------------------------------------------


@pytest.mark.anyio
async def test_searches_then_synthesizes_from_collected_lines() -> None:
    fake = FakeLLMClient([FakeTurn([search("checkout")]), FakeTurn(text="done"), _report("c1")])

    run = await _agent(fake).investigate("checkout returns 500", service="checkout")

    assert run.investigator == "agent"
    assert run.prompt_version == PROMPT_ID
    assert run.loop_stop_reason == "model_done"
    assert run.agent_steps == 2
    assert run.tool_calls == 1
    assert run.tool_errors == 0
    assert run.services_searched == ["checkout"]
    assert run.llm_calls == 3  # two loop turns + one synthesis call
    assert run.input_tokens == 3000
    assert run.final_grounded
    assert run.log_lines_sent == 2

    synthesis_input = fake.calls[0].user
    assert '"c1"' in synthesis_input and '"c2"' in synthesis_input
    assert '"p1"' not in synthesis_input  # never searched, never sent


@pytest.mark.anyio
async def test_conversation_gets_agent_prompt_allowlist_and_tool() -> None:
    fake = FakeLLMClient([FakeTurn(text="nothing to do")])

    await _agent(fake).investigate("checkout returns 500", service="checkout")

    conversation = _conversation(fake)
    assert "search_logs" in conversation.system
    assert "checkout, payments-gateway" in conversation.user
    assert "billing-secrets" not in conversation.user
    assert [tool.name for tool in conversation.tools] == ["search_logs"]


@pytest.mark.anyio
async def test_follows_the_dependency_and_grounds_against_both_services() -> None:
    fake = FakeLLMClient(
        [
            FakeTurn([search("checkout")]),
            FakeTurn([search("payments-gateway")]),
            FakeTurn(text="pool exhausted in payments-gateway"),
            _report("p1", "c2"),
        ]
    )

    run = await _agent(fake).investigate("checkout returns 500")

    assert run.services_searched == ["checkout", "payments-gateway"]
    assert run.first_attempt_grounded
    assert run.log_lines_sent == 4
    # Collected lines reach synthesis in chronological order across services.
    user = fake.calls[0].user
    assert user.index('"p1"') < user.index('"c1"') < user.index('"p2"') < user.index('"c2"')


@pytest.mark.anyio
async def test_parallel_tool_calls_are_answered_in_one_message_in_order() -> None:
    fake = FakeLLMClient(
        [
            FakeTurn([search("checkout"), search("payments-gateway")]),
            FakeTurn(text="done"),
            _report("c1"),
        ]
    )

    run = await _agent(fake).investigate("checkout returns 500")

    [results] = _conversation(fake).tool_results
    calls = _conversation(fake).turns[0].tool_calls
    assert [r.tool_call_id for r in results] == [c.id for c in calls]
    assert run.tool_calls == 2


# --- untrusted model requests ---------------------------------------------------------


@pytest.mark.anyio
async def test_tool_errors_go_back_to_the_model_and_the_loop_continues() -> None:
    fake = FakeLLMClient(
        [
            FakeTurn([search("billing-secrets")]),  # not allowed
            FakeTurn([search("checkout")]),
            FakeTurn(text="done"),
            _report("c1"),
        ]
    )

    run = await _agent(fake).investigate("checkout returns 500")

    first_results = _conversation(fake).tool_results[0]
    assert first_results[0].is_error
    assert run.tool_errors == 1
    assert run.services_searched == ["checkout"]
    assert '"s1"' not in fake.calls[0].user


@pytest.mark.anyio
async def test_unknown_tool_is_an_error_result_not_executed() -> None:
    fake = FakeLLMClient(
        [FakeTurn([("delete_namespace", {"name": "production"})]), FakeTurn(text="ok")]
    )

    run = await _agent(fake).investigate("checkout returns 500")

    [[result]] = _conversation(fake).tool_results
    assert result.is_error
    assert run.tool_errors == 1


# --- bounds ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_max_steps_stops_the_loop_but_still_synthesizes() -> None:
    fake = FakeLLMClient(
        [FakeTurn([search("checkout")]), FakeTurn([search("payments-gateway")]), _report("c1")]
    )

    run = await _agent(fake, max_steps=2).investigate("checkout returns 500")

    assert run.loop_stop_reason == "max_steps"
    assert run.agent_steps == 2
    assert run.llm_calls == 3
    assert run.report.status == "conclusive"


@pytest.mark.anyio
async def test_tool_budget_refuses_extra_calls_and_stops() -> None:
    fake = FakeLLMClient(
        [
            FakeTurn([search("checkout"), search("payments-gateway"), search("checkout")]),
            _report("c1"),
        ]
    )

    run = await _agent(fake, max_tool_calls=2).investigate("checkout returns 500")

    [results] = _conversation(fake).tool_results
    assert [r.is_error for r in results] == [False, False, True]
    assert run.tool_calls == 3
    assert run.tool_errors == 1
    assert run.loop_stop_reason == "max_tool_calls"
    assert run.agent_steps == 1


@pytest.mark.anyio
async def test_time_reserve_stops_before_the_first_model_call() -> None:
    fake = FakeLLMClient([])

    run = await _agent(fake, timeout_s=5, synthesis_reserve_s=6).investigate("checkout 500s")

    assert run.loop_stop_reason == "time_budget"
    assert run.agent_steps == 0
    assert run.llm_calls == 0


@pytest.mark.anyio
async def test_no_evidence_is_inconclusive_without_a_synthesis_call() -> None:
    fake = FakeLLMClient([FakeTurn(text="I don't think logs will help.")])

    run = await _agent(fake).investigate("checkout returns 500")

    assert fake.calls == []  # generate_structured never called
    assert run.report.status == "inconclusive"
    assert run.report.hypotheses == []
    assert run.llm_calls == 1


class _SlowTurns(FakeLLMClient):
    def __init__(self) -> None:
        super().__init__([])

    async def next_turn(self, conversation: Conversation, *, max_tokens: int = 8192) -> Turn:
        await asyncio.sleep(10)
        raise AssertionError("unreachable")


@pytest.mark.anyio
async def test_deadline_is_enforced() -> None:
    agent = AgentInvestigator(
        _SlowTurns(), _store(), allowed_services=ALLOWED, timeout_s=0.05, synthesis_reserve_s=0
    )

    with pytest.raises(InvestigationTimeoutError):
        await agent.investigate("checkout returns 500")


# --- grounding and failures -----------------------------------------------------------


@pytest.mark.anyio
async def test_grounding_only_accepts_lines_a_search_returned() -> None:
    fake = FakeLLMClient(
        [
            FakeTurn([search("checkout")]),
            FakeTurn(text="done"),
            _report("p1"),  # exists in the store, but was never returned to the model
            _report("c1"),
        ]
    )

    run = await _agent(fake).investigate("checkout returns 500")

    assert not run.first_attempt_grounded
    assert run.grounding_retry_used
    assert run.final_grounded


@pytest.mark.anyio
async def test_llm_error_in_the_loop_propagates() -> None:
    fake = FakeLLMClient([LLMTimeoutError("slow")])

    with pytest.raises(LLMTimeoutError):
        await _agent(fake).investigate("checkout returns 500")
