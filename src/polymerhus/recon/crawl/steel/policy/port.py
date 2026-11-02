"""The policy port: three choice questions, one answer, nothing executed.

Spec: `docs/design/steel-crawl-spec.md` sections 6.6, 6.7, 7, 8.2, and 12.

The policy is the one authority on what happens next. It answers exactly three
questions - which candidate to remove, which candidate to exercise, and which
catalogue key fills a field - and it owns nothing else: it never executes, never
records, and never ranks on its own.

The answer to one question is one `answers[kind]` object: a `choice` key (an
element id, a catalogue key, or `none`), a confidence, and probabilities. There
is no probability threshold - `choice` is the answer, and the probabilities are
recorded evidence, never a scoring gate. A choice outside the question's answer
space is a protocol error, never an execution: `PolicyStaleRemoval` when a
removal names an id that is no longer a live candidate, and `PolicyInvalidChoice`
when a choice or a value names anything outside its candidates or catalogue.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from polymerhus.recon.crawl.steel.enumerate import Element
from polymerhus.recon.crawl.steel.state import PageInstance

# The three question kinds the crawl asks, in the order it asks them (spec 7,
# 8.2). The kind tags the question and the answer: a client answers `answers[kind]`.
QuestionKind = Literal["choose_removed", "choose_chosen", "choose_value"]

# The decline answer. It is a valid answer to every question and never an error.
NONE_CHOICE = "none"


@runtime_checkable
class Policy(Protocol):
    """The three questions the crawl asks, and nothing else (spec 3.2, 6.6, 7).

    The port is synchronous by design: the crawl asks one question at a time,
    and the decision client's own concurrency belongs to the adapter (SC-07).
    `choose_removed` and `choose_chosen` answer with the whole candidate, so the
    loop never re-derives identity; an answer outside the question's space is a
    protocol error, never a partial candidate.
    """

    def choose_removed(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None: ...

    def choose_chosen(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None: ...

    def choose_value(
        self, field: Mapping[str, Any], catalogue: Mapping[str, Any]
    ) -> str | None: ...


class ChoiceQuestion(BaseModel):
    """One typed choice question: the instructions and the bounded answer space.

    `criteria` maps every answerable key to its one-line description, and it is
    the guarantee that the model can only answer inside it. The `none` key is
    always present: declining is a valid answer (spec 6.6, 7, 8.2).
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["choice"] = "choice"
    instructions: str
    criteria: Mapping[str, str]


class DecisionRequest(BaseModel):
    """One SystemOne request: the compact state and its single named question.

    `kind` tags the question and the answer: the client answers `answers[kind]`
    with one `ChoiceAnswer`. `state` is the compact context the model reads;
    `questions` is what it may answer, keyed by the same kind and carrying one
    question only, so one request always has exactly one answer.
    """

    model_config = ConfigDict(frozen=True)

    kind: QuestionKind
    state: Mapping[str, Any]
    questions: Mapping[str, ChoiceQuestion]

    @model_validator(mode="after")
    def _one_question_keyed_by_kind(self) -> "DecisionRequest":
        if tuple(self.questions) != (self.kind,):
            raise ValueError(
                f"a {self.kind} request carries exactly one {self.kind} question"
            )
        return self


class PolicyProtocolError(RuntimeError):
    """A policy answer broke the answer protocol; it is never executed.

    Spec section 12 maps both codes to "protocol error; do not execute": the
    stage records the failure and stops the affected loop. The answer is not a
    candidate and never a reason to act. Only the two concrete codes below are
    emitted.
    """


class PolicyStaleRemoval(PolicyProtocolError):
    """The removal answer names a candidate that is no longer live (spec 7, 12).

    A stale removal is not a choice error: the loop already removed that
    candidate, so executing the answer again would act twice on one element.
    The page visit id, the answered id, and the live ids ride on the failure so
    the record can say exactly what went stale.
    """

    code = "policy_stale_removal"

    def __init__(self, page: PageInstance, choice: str, live: Sequence[str]) -> None:
        self.page_visit_id = page.page_visit_id
        self.choice = choice
        self.live = tuple(live)
        super().__init__(
            f"the removal answer names {choice!r}, which is not a live candidate "
            f"on page {page.page_visit_id!r} "
            f"(live: {', '.join(self.live) or 'none'})"
        )


class PolicyInvalidChoice(PolicyProtocolError):
    """The answer names a key outside the question's answer space (spec 12).

    The kind, the answered key, and the valid criteria ride on the failure, so
    the record names the question that could not be answered rather than a
    downstream "no candidate" symptom.
    """

    code = "policy_invalid_choice"

    def __init__(self, kind: str, choice: str, valid: Sequence[str]) -> None:
        self.kind = kind
        self.choice = choice
        self.valid = tuple(valid)
        super().__init__(
            f"the {kind} answer names {choice!r}, which is not one of the "
            f"criteria ({', '.join(self.valid) or 'none'})"
        )


class ChoiceAnswer(BaseModel):
    """The answer to one choice question (Jev-inference-client section 4.3).

    `choice` is the answer itself: an element id, a catalogue key, or `none`.
    `probabilities` is evidence for the trial record, never a gate: the crawl
    executes `choice` whatever its confidence, because there is no probability
    threshold (spec 6.6, workbench Q22).
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["choice"] = "choice"
    choice: str = Field(min_length=1)
    confidence: float = 0.0
    probabilities: Mapping[str, float] = Field(default_factory=dict)


def select_removed(
    page: PageInstance, candidates: Sequence[Element], answer: ChoiceAnswer
) -> Element | None:
    """The one candidate to remove, or `None` to end the removal loop.

    The live candidate set is the only truth: an answered id that left it was
    already removed, so the answer is stale and is never re-executed (spec 7).
    """
    if answer.choice == NONE_CHOICE:
        return None
    live = _by_element_id(candidates)
    removed = live.get(answer.choice)
    if removed is None:
        raise PolicyStaleRemoval(page, answer.choice, tuple(live))
    return removed


def _by_element_id(candidates: Sequence[Element]) -> dict[str, Element]:
    return {candidate.element_id: candidate for candidate in candidates}


def select_chosen(
    candidates: Sequence[Element], answer: ChoiceAnswer
) -> Element | None:
    """The one candidate to exercise, or `None` to backtrack (spec 6.6).

    Unlike a removal, a chosen id outside the live set is an invalid choice, not
    stale: the removal stage already took the live set down to what may be
    exercised, so an id outside it was never a legal answer.
    """
    if answer.choice == NONE_CHOICE:
        return None
    live = _by_element_id(candidates)
    chosen = live.get(answer.choice)
    if chosen is None:
        raise PolicyInvalidChoice(
            "choose_chosen", answer.choice, _answer_space(live)
        )
    return chosen


def select_value(
    catalogue: Mapping[str, Any], answer: ChoiceAnswer
) -> str | None:
    """The chosen catalogue key, or `None` to skip the field (spec 8.2).

    The key is validated against the catalogue and never against the field: the
    executor checks the typed value against the pattern, min, max, and options,
    because the value itself never enters the request.
    """
    if answer.choice == NONE_CHOICE:
        return None
    if answer.choice not in catalogue:
        raise PolicyInvalidChoice(
            "choose_value", answer.choice, _answer_space(catalogue)
        )
    return answer.choice


def _answer_space(keys: Iterable[str]) -> tuple[str, ...]:
    """The answer space, with `none` present exactly once and the keys in order."""
    valid = tuple(keys)
    return valid if NONE_CHOICE in valid else (*valid, NONE_CHOICE)


__all__ = [
    "NONE_CHOICE",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "DecisionRequest",
    "Policy",
    "PolicyInvalidChoice",
    "PolicyProtocolError",
    "PolicyStaleRemoval",
    "QuestionKind",
    "select_chosen",
    "select_removed",
    "select_value",
]
