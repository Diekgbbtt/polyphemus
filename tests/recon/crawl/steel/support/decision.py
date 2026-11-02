"""A queued stand-in for the Jev decision client.

The policy asks three question kinds. The fake answers each from its own
queue and records every question, so a policy test can assert the exact
criteria the model was shown without calling a provider.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


class DecisionQueueExhausted(RuntimeError):
    """The policy asked a question the fake never queued an answer for."""


@dataclass(frozen=True)
class DecisionQuestion:
    """One question the policy asked, captured for assertion."""

    kind: str
    state: Any = None
    candidates: tuple[Any, ...] = ()
    field: Any = None
    catalogue: Mapping[str, Any] | None = None


class FakeDecisionClient:
    """Callable policy seam: three question methods, three answer queues."""

    def __init__(
        self,
        *,
        removed: Iterable[Any] = (),
        chosen: Iterable[Any] = (),
        values: Iterable[str | None] = (),
    ) -> None:
        self._removed: deque[Any] = deque(removed)
        self._chosen: deque[Any] = deque(chosen)
        self._values: deque[str | None] = deque(values)
        self.questions: list[DecisionQuestion] = []

    def choose_removed(self, state: Any, candidates: Iterable[Any]) -> Any | None:
        self.questions.append(
            DecisionQuestion(kind="choose_removed", state=state, candidates=tuple(candidates))
        )
        return self._take(self._removed, "choose_removed")

    def choose_chosen(self, state: Any, candidates: Iterable[Any]) -> Any | None:
        self.questions.append(
            DecisionQuestion(kind="choose_chosen", state=state, candidates=tuple(candidates))
        )
        return self._take(self._chosen, "choose_chosen")

    def choose_value(self, field: Any, catalogue: Mapping[str, Any]) -> str | None:
        self.questions.append(
            DecisionQuestion(kind="choose_value", field=field, catalogue=dict(catalogue))
        )
        return self._take(self._values, "choose_value")

    @staticmethod
    def _take(queue: deque[Any], kind: str) -> Any | None:
        if not queue:
            raise DecisionQueueExhausted(f"no queued {kind} answer")
        return queue.popleft()

    @property
    def asked(self) -> list[str]:
        return [question.kind for question in self.questions]
