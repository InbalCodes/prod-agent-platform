"""Scripted LLMClient for tests: returns queued outputs or raises queued errors, no network.

The script is consumed in call order, across both call types:
- a `BaseModel` answers the next `generate_structured` call,
- a `FakeTurn` answers the next `next_turn` call,
- an `LLMError` is raised by whichever call comes next.
"""

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from agent_platform.llm.client import (
    Conversation,
    LLMResult,
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
    Usage,
)
from agent_platform.llm.errors import LLMError


@dataclass(frozen=True)
class FakeCall:
    system: str
    user: str
    output_type: type[BaseModel]


@dataclass(frozen=True)
class FakeTurn:
    """A scripted model turn: tool calls (name, input) and/or final text."""

    tool_calls: Sequence[tuple[str, dict[str, Any]]] = ()
    text: str | None = None


@dataclass
class FakeConversation(Conversation):
    system: str
    user: str
    tools: list[ToolSpec]
    turns: list[Turn] = field(default_factory=list)
    tool_results: list[list[ToolResult]] = field(default_factory=list)


class FakeLLMClient:
    def __init__(
        self,
        script: Iterable[BaseModel | FakeTurn | LLMError],
        model: str = "fake-model",
        usage: Usage | None = None,
    ) -> None:
        self._script = deque(script)
        self._model = model
        self._usage = usage or Usage(input_tokens=1000, output_tokens=200)
        self._call_count = 0
        self.calls: list[FakeCall] = []
        self.conversations: list[FakeConversation] = []

    @property
    def model(self) -> str:
        return self._model

    async def generate_structured[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        output_type: type[T],
        max_tokens: int = 8192,
    ) -> LLMResult[T]:
        self.calls.append(FakeCall(system=system, user=user, output_type=output_type))
        step = self._next_step()
        if not isinstance(step, output_type):
            raise AssertionError(
                f"FakeLLMClient: scripted {type(step).__name__}, asked for {output_type.__name__}"
            )
        return LLMResult(
            parsed=step,
            model=self._model,
            usage=self._usage,
            stop_reason="end_turn",
            provider_request_id=f"fake-{self._call_count}",
        )

    def start_conversation(
        self, *, system: str, user: str, tools: Sequence[ToolSpec]
    ) -> Conversation:
        conversation = FakeConversation(system=system, user=user, tools=list(tools))
        self.conversations.append(conversation)
        return conversation

    async def next_turn(self, conversation: Conversation, *, max_tokens: int = 8192) -> Turn:
        assert isinstance(conversation, FakeConversation)
        if conversation.turns and conversation.turns[-1].tool_calls:
            answered = len(conversation.tool_results) == len(
                [t for t in conversation.turns if t.tool_calls]
            )
            assert answered, "FakeLLMClient: next_turn before answering the last tool calls"

        step = self._next_step()
        if not isinstance(step, FakeTurn):
            raise AssertionError(f"FakeLLMClient: scripted {type(step).__name__}, asked for a turn")
        turn = Turn(
            tool_calls=[
                ToolCall(id=f"call-{self._call_count}-{i}", name=name, input=args)
                for i, (name, args) in enumerate(step.tool_calls)
            ],
            text=step.text,
            model=self._model,
            usage=self._usage,
            stop_reason="tool_use" if step.tool_calls else "end_turn",
            provider_request_id=f"fake-{self._call_count}",
        )
        conversation.turns.append(turn)
        return turn

    def add_tool_results(self, conversation: Conversation, results: Sequence[ToolResult]) -> None:
        assert isinstance(conversation, FakeConversation)
        expected = {call.id for call in conversation.turns[-1].tool_calls}
        got = {result.tool_call_id for result in results}
        assert got == expected, f"FakeLLMClient: tool results {got} != tool calls {expected}"
        conversation.tool_results.append(list(results))

    def _next_step(self) -> BaseModel | FakeTurn:
        self._call_count += 1
        if not self._script:
            raise AssertionError("FakeLLMClient: no scripted response left")
        step = self._script.popleft()
        if isinstance(step, LLMError):
            raise step
        return step
