"""Seam under test: the removal loop, through a fake policy and a fake collector.

Spec: `docs/design/steel-crawl-spec.md` sections 2.4, 6.7, 7, and 12; seam 5 of
`docs/design/steel-crawl-implementation-plan.md` section 3.

The removal stage is the structural guard against declassification. These tests
drive `remove_forbidden` the way the crawl will - a policy answers, the loop
consumes and collects one candidate, then asks again - and prove that a stale
answer is a recorded protocol error that never executes, while the loop always
terminates and never touches the caller's candidate sequence.
"""
from __future__ import annotations

from typing import Any

import pytest

from polymerhus.recon.crawl.steel.command import CaptureChannel, ImpactClass
from polymerhus.recon.crawl.steel.enumerate import (
    ChangeSemantics,
    Element,
    ElementType,
)
from polymerhus.recon.crawl.steel.policy.jev import JevPolicy, PolicyProviderError
from polymerhus.recon.crawl.steel.policy.port import PolicyStaleRemoval
from polymerhus.recon.crawl.steel.safety import (
    Collector,
    RemovalResult,
    remove_forbidden,
)
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance
from tests.recon.crawl.steel.support import FakeDecisionClient
from tests.recon.crawl.steel.support.jev import FakeAskClient


def open_page(
    url: str = "https://example.test/products",
) -> tuple[BrowserState, PageInstance]:
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_1", url=url, final_url=url, title="Products", snapshot=()
    )
    return state, page


def element(
    element_id: str,
    label: str,
    *,
    impact: ImpactClass = "local_state",
    capture: CaptureChannel = "dom",
) -> Element:
    """One candidate carrying the identity and change semantics the loop needs."""
    return Element(
        element_id=element_id,
        fingerprint=f"fingerprint_{element_id}",
        element_type=ElementType.BUTTON,
        name=label,
        impact=impact,
        capture=capture,
        change=ChangeSemantics(impact=impact, capture=capture),
    )


class RecordingCollector:
    """The DOM collector seam: records each candidate it is handed."""

    def __init__(self) -> None:
        self.collected: list[Element] = []

    def collect(self, element: Element) -> None:
        self.collected.append(element)


class StaleRaisingPolicy:
    """A policy that raises the stale-removal protocol error directly."""

    def __init__(self, error: PolicyStaleRemoval) -> None:
        self.error = error

    def choose_removed(self, page: PageInstance, candidates: Any) -> Element | None:
        raise self.error


class GreedyPolicy:
    """A misbehaving policy: it never answers `none`, even once the set is empty."""

    def __init__(self) -> None:
        self.asked = 0
        self._last: Element | None = None

    def choose_removed(self, page: PageInstance, candidates: Any) -> Element | None:
        self.asked += 1
        if candidates:
            self._last = candidates[0]
            return self._last
        return self._last


class ExecutorSpy:
    """The action seam a removal must never reach."""

    def __init__(self) -> None:
        self.executed: list[Element] = []

    def execute(self, element: Element) -> None:
        self.executed.append(element)


def test_the_recording_collector_satisfies_the_collector_protocol():
    assert isinstance(RecordingCollector(), Collector)


def test_one_removal_then_none_consumes_and_collects_the_removed_candidate():
    state, page = open_page()
    add = element("e23", "Add to cart")
    delete = element("e24", "Delete item", impact="write")
    candidates: list[Element] = [add, delete]
    policy = FakeDecisionClient(removed=[delete, None])
    collector = RecordingCollector()

    result = remove_forbidden(page, candidates, policy, state, collector)

    assert result == RemovalResult(remaining=(add,), removed=(delete,), stale=None)
    assert collector.collected == [delete]
    assert state.unconsumed(page, [delete]) == []
    assert state.unconsumed(page, [add]) == [add]
    # The loop owns its working copy: the caller's sequence is never mutated.
    assert candidates == [add, delete]
    # One question per removal, plus the terminal `none`; each later question
    # sees only the candidates that remain.
    assert [question.candidates for question in policy.questions] == [
        (add, delete),
        (add,),
    ]


def test_an_answer_naming_a_removed_candidate_is_stale_and_never_collected():
    state, page = open_page()
    add = element("e23", "Add to cart")
    ghost = element("e99", "Delete item", impact="write")
    policy = FakeDecisionClient(removed=[ghost, None])
    collector = RecordingCollector()

    result = remove_forbidden(page, [add], policy, state, collector)

    assert result.remaining == (add,)
    assert result.removed == ()
    assert result.stale is not None
    assert result.stale.code == "policy_stale_removal"
    assert result.stale.choice == "e99"
    assert result.stale.live == ("e23",)
    assert collector.collected == []
    assert state.unconsumed(page, [add]) == [add]


def test_a_policy_raising_a_stale_removal_records_it_and_stops():
    state, page = open_page()
    add = element("e23", "Add to cart")
    stale = PolicyStaleRemoval(page, "e24", ("e23",))
    collector = RecordingCollector()

    result = remove_forbidden(page, [add], StaleRaisingPolicy(stale), state, collector)

    assert result.remaining == (add,)
    assert result.removed == ()
    assert result.stale is stale
    assert collector.collected == []


def test_the_loop_terminates_within_the_candidate_count_even_if_the_policy_misbehaves():
    state, page = open_page()
    candidates = [
        element("e23", "Add to cart"),
        element("e24", "Delete item"),
        element("e25", "Register"),
    ]
    policy = GreedyPolicy()
    collector = RecordingCollector()

    result = remove_forbidden(page, candidates, policy, state, collector)

    # Three candidates, three removals, then one final question that can only
    # name a candidate outside the now-empty set: the stale guard stops it.
    assert len(result.removed) == len(candidates)
    assert result.remaining == ()
    assert result.stale is not None
    assert result.stale.code == "policy_stale_removal"
    assert policy.asked == len(candidates) + 1
    assert collector.collected == candidates


def test_the_removal_stage_collects_but_never_executes():
    state, page = open_page()
    add = element("e23", "Add to cart")
    delete = element("e24", "Delete item", impact="write")
    policy = FakeDecisionClient(removed=[delete, None])
    collector = RecordingCollector()
    executor = ExecutorSpy()

    result = remove_forbidden(page, [add, delete], policy, state, collector)

    # Collecting is the only effect a removed candidate can have; an action is
    # never built or executed for it (spec S3).
    assert executor.executed == []
    assert collector.collected == [delete]
    assert result.remaining == (add,)


def test_a_removed_candidate_is_absent_from_the_next_choice_question():
    state, page = open_page()
    add = element("e23", "Add to cart")
    delete = element("e24", "Delete item", impact="write")
    client = FakeAskClient(removed=["e24", None], chosen=[None])
    policy = JevPolicy(client, state=state)
    collector = RecordingCollector()

    result = remove_forbidden(page, [add, delete], policy, state, collector)
    chosen = policy.choose_chosen(page, result.remaining)

    assert chosen is None
    assert result.removed == (delete,)
    assert collector.collected == [delete]
    # The only question the choice model saw is over the surviving candidate.
    question = client.calls[-1].questions["choose_chosen"]
    assert list(question["criteria"]) == ["e23", "none"]
    candidates = client.calls[-1].state["candidates"]
    assert [criterion["element_id"] for criterion in candidates] == ["e23"]
    assert client.asked == ["choose_removed", "choose_removed", "choose_chosen"]


def test_a_provider_error_stops_the_stage_without_consuming_or_collecting():
    state, page = open_page()
    add = element("e23", "Add to cart")
    delete = element("e24", "Delete item", impact="write")
    failure = TimeoutError("typesafe timed out")
    client = FakeAskClient(removed=[failure])
    policy = JevPolicy(client, state=state)
    collector = RecordingCollector()

    with pytest.raises(PolicyProviderError) as excinfo:
        remove_forbidden(page, [add, delete], policy, state, collector)

    assert excinfo.value.code == "policy_provider_error"
    assert excinfo.value.kind == "choose_removed"
    assert excinfo.value.cause is failure
    assert collector.collected == []
    assert state.unconsumed(page, [add, delete]) == [add, delete]
