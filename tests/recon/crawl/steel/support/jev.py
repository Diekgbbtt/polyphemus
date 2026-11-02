"""Fakes for the Jev adapter seam.

`FakeAsyncTypeSafe` stands in for the committed async `TypeSafeSystemOne` client:
it records the state, the questions, the configured model, and the thread its
coroutine ran on, so the adapter's synchronous bridge and teardown are observable
without a provider. `FakeAskClient` stands in for the synchronous decision-client
port the policy asks; it queues one answer per question kind.
"""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


class AskQueueExhausted(RuntimeError):
    """The policy asked a question the fake never queued an answer for."""


class MissingAnswer:
    """A queued response with no answers object at all."""

    def __repr__(self) -> str:
        return "MISSING_ANSWER"


MISSING_ANSWER = MissingAnswer()


@dataclass(frozen=True)
class AsyncAskCall:
    """One call the adapter bridged onto the async client."""

    state: Mapping[str, Any]
    questions: Mapping[str, Any]
    model: str
    thread_id: int


@dataclass
class FakeAsyncTypeSafe:
    """A fake `TypeSafeSystemOne`: async `ask`/`close`, both recorded."""

    model: str = "jev-latest"
    response: Mapping[str, Any] = field(default_factory=dict)
    error: BaseException | None = None
    calls: list[AsyncAskCall] = field(default_factory=list)
    close_thread_id: int | None = None
    closed: bool = False

    async def ask(
        self,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
        *,
        model: str | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append(
            AsyncAskCall(
                state=state,
                questions=questions,
                model=model or self.model,
                thread_id=threading.get_ident(),
            )
        )
        if self.error is not None:
            raise self.error
        return self.response

    async def close(self) -> None:
        self.close_thread_id = threading.get_ident()
        self.closed = True


@dataclass(frozen=True)
class AskCall:
    """One question the synchronous decision client was asked."""

    state: Mapping[str, Any]
    questions: Mapping[str, Any]


class FakeAskClient:
    """A queued stand-in for the synchronous decision-client port.

    Each queued entry is one response for the kind the policy asks: a bare
    choice string (or `None` for `none`) becomes a well-formed `ChoiceAnswer`, a
    mapping becomes the raw `answers[kind]` payload, an exception is raised, and
    `MISSING_ANSWER` returns a response with no `answers` object at all.
    """

    def __init__(
        self,
        *,
        removed: Iterable[Any] = (),
        chosen: Iterable[Any] = (),
        values: Iterable[Any] = (),
    ) -> None:
        self._queues: dict[str, deque[Any]] = {
            "choose_removed": deque(removed),
            "choose_chosen": deque(chosen),
            "choose_value": deque(values),
        }
        self.calls: list[AskCall] = []

    def ask(
        self, state: Mapping[str, Any], questions: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        kind = next(iter(questions))
        self.calls.append(AskCall(state=state, questions=questions))
        queue = self._queues[kind]
        if not queue:
            raise AskQueueExhausted(f"no queued {kind} answer")
        answer = queue.popleft()
        if isinstance(answer, BaseException):
            raise answer
        if answer is MISSING_ANSWER:
            return {}
        if isinstance(answer, Mapping):
            return {"answers": {kind: dict(answer)}}
        return {
            "answers": {
                kind: {
                    "type": "choice",
                    "choice": "none" if answer is None else answer,
                }
            }
        }

    @property
    def asked(self) -> list[str]:
        return [next(iter(call.questions)) for call in self.calls]


__all__ = [
    "MISSING_ANSWER",
    "AskCall",
    "AskQueueExhausted",
    "AsyncAskCall",
    "FakeAskClient",
    "FakeAsyncTypeSafe",
    "MissingAnswer",
]
