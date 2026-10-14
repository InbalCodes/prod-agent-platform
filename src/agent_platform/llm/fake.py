"""Scripted LLMClient for tests: returns queued outputs or raises queued errors, no network."""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel

from agent_platform.llm.client import LLMResult, Usage
from agent_platform.llm.errors import LLMError


@dataclass(frozen=True)
class FakeCall:
    system: str
    user: str
    output_type: type[BaseModel]


class FakeLLMClient:
    def __init__(
        self,
        script: Iterable[BaseModel | LLMError],
        model: str = "fake-model",
        usage: Usage | None = None,
    ) -> None:
        self._script = deque(script)
        self._model = model
        self._usage = usage or Usage(input_tokens=1000, output_tokens=200)
        self.calls: list[FakeCall] = []

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
        if not self._script:
            raise AssertionError("FakeLLMClient: no scripted response left")

        step = self._script.popleft()
        if isinstance(step, LLMError):
            raise step
        if not isinstance(step, output_type):
            raise AssertionError(
                f"FakeLLMClient: scripted {type(step).__name__}, asked for {output_type.__name__}"
            )
        return LLMResult(
            parsed=step,
            model=self._model,
            usage=self._usage,
            stop_reason="end_turn",
            provider_request_id=f"fake-{len(self.calls)}",
        )
