"""Seam under test: the policy port, through the fake decision client.

Spec: `docs/design/steel-crawl-spec.md` sections 6.6, 6.7, 7, 8.2, and 12;
seam 5 of `docs/design/steel-crawl-implementation-plan.md` section 3.

The crawl asks three questions and executes one answer. These tests drive the
protocol the way the crawl will - a removal loop and a choice loop through the
fake decision client - and prove that an answer outside the question's answer
space is a protocol error that never executes, while `none` is a valid answer
that ends a loop.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from polymerhus.recon.crawl.steel.command import CaptureChannel, ImpactClass
from polymerhus.recon.crawl.steel.enumerate import (
    ChangeSemantics,
    Element,
    ElementType,
)
from polymerhus.recon.crawl.steel.policy.port import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    Policy,
    PolicyInvalidChoice,
    PolicyStaleRemoval,
    select_chosen,
    select_removed,
    select_value,
)
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance
from tests.recon.crawl.steel.support import FakeDecisionClient


def open_page(url: str = "https://example.test/products") -> PageInstance:
    state = BrowserState()
    return state.open_page(
        page_visit_id="page_1", url=url, final_url=url, title="Products", snapshot=()
    )


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


def answer(choice: str, **fields: Any) -> ChoiceAnswer:
    return ChoiceAnswer(choice=choice, **fields)


def test_a_removal_answer_selects_the_candidate_it_names():
    page = open_page()
    candidates = [element("e23", "Add to cart"), element("e24", "Delete item")]

    assert select_removed(page, candidates, answer("e24")) is candidates[1]


def test_a_removal_answer_that_names_an_already_removed_candidate_is_stale():
    page = open_page()
    candidates = [element("e23", "Add to cart")]

    with pytest.raises(PolicyStaleRemoval) as excinfo:
        select_removed(page, candidates, answer("e24"))

    assert excinfo.value.code == "policy_stale_removal"
    assert excinfo.value.choice == "e24"
    assert excinfo.value.page_visit_id == "page_1"
    assert "e24" in str(excinfo.value)


def test_none_is_a_valid_removal_answer_and_ends_the_loop():
    page = open_page()
    candidates = [element("e23", "Add to cart")]

    assert select_removed(page, candidates, answer("none")) is None


def test_a_choice_outside_the_candidates_is_an_invalid_choice_protocol_error():
    candidates = [element("e23", "Add to cart"), element("e20", "Home")]

    with pytest.raises(PolicyInvalidChoice) as excinfo:
        select_chosen(candidates, answer("e99"))

    assert excinfo.value.code == "policy_invalid_choice"
    assert excinfo.value.kind == "choose_chosen"
    assert excinfo.value.choice == "e99"
    assert excinfo.value.valid == ("e23", "e20", "none")
    assert "e99" in str(excinfo.value)


def test_the_chosen_answer_wins_whatever_its_probability():
    # There is no probability threshold: the choice field is the answer, and the
    # probabilities stay evidence, so a certain-looking runner-up never wins.
    candidates = [element("e23", "Add to cart"), element("e20", "Home")]

    answered = answer(
        "e20",
        confidence=0.01,
        probabilities={"e23": 0.99, "e20": 0.01},
    )

    assert select_chosen(candidates, answered) is candidates[1]


def test_none_is_a_valid_chosen_answer_and_ends_the_choice_loop():
    assert select_chosen([element("e23", "Add to cart")], answer("none")) is None


def test_a_value_key_outside_the_catalogue_is_an_invalid_choice_protocol_error():
    catalogue = {
        "email": {"kind": "email", "description": "valid email"},
        "none": {"kind": "none", "description": "leave empty"},
    }

    with pytest.raises(PolicyInvalidChoice) as excinfo:
        select_value(catalogue, answer("password"))

    assert excinfo.value.code == "policy_invalid_choice"
    assert excinfo.value.kind == "choose_value"
    assert excinfo.value.valid == ("email", "none")


def test_a_value_answer_is_the_catalogue_key_and_none_skips_the_field():
    catalogue = {
        "email": {"kind": "email", "description": "valid email"},
        "none": {"kind": "none", "description": "leave empty"},
    }

    assert select_value(catalogue, answer("email")) == "email"
    assert select_value(catalogue, answer("none")) is None


def test_the_fake_decision_client_satisfies_the_policy_protocol():
    policy: Policy = FakeDecisionClient(
        removed=[element("e24", "Delete item"), None],
        chosen=[element("e23", "Add to cart"), None],
        values=["email", None],
    )
    field = {"name": "contact", "type": "email"}
    catalogue = {"email": {"kind": "email", "description": "valid email"}}

    assert isinstance(policy, Policy)
    assert policy.choose_value(field, catalogue) == "email"


def test_a_decision_request_carries_one_question_keyed_by_its_kind():
    question = ChoiceQuestion(
        instructions="Choose the next element.",
        criteria={"e23": "button Add to cart", "none": "no candidate remains"},
    )

    request = DecisionRequest(
        kind="choose_chosen",
        state={"page": {"url": "https://example.test/products"}},
        questions={"choose_chosen": question},
    )

    assert request.kind == "choose_chosen"
    assert request.state["page"]["url"] == "https://example.test/products"
    assert request.questions["choose_chosen"].type == "choice"
    assert request.questions["choose_chosen"].criteria["none"] == "no candidate remains"


def test_a_request_whose_questions_do_not_match_its_kind_is_rejected():
    question = ChoiceQuestion(instructions="Choose one.", criteria={"none": "nothing"})

    with pytest.raises(ValidationError):
        DecisionRequest(kind="choose_chosen", state={}, questions={})

    with pytest.raises(ValidationError):
        DecisionRequest(
            kind="choose_chosen",
            state={},
            questions={"choose_removed": question},
        )

    with pytest.raises(ValidationError):
        DecisionRequest(
            kind="choose_chosen",
            state={},
            questions={"choose_chosen": question, "choose_value": question},
        )


def test_the_fake_policy_drives_a_removal_loop_one_candidate_at_a_time():
    # The spec's removal loop (section 7): ask, remove one, ask again, stop on
    # `none`. The fake records each question, so the shrinking candidate set is
    # observable: a removed element is never shown to the next question.
    page = open_page()
    add = element("e23", "Add to cart")
    delete = element("e24", "Delete item", impact="write")
    register = element("e25", "Register", impact="write")
    policy = FakeDecisionClient(removed=[delete, register, None])

    remaining = [add, delete, register]
    removed: list[str] = []
    while True:
        candidate = policy.choose_removed(page, remaining)
        if candidate is None:
            break
        assert (
            select_removed(page, remaining, answer(candidate.element_id)) is candidate
        )
        removed.append(candidate.element_id)
        remaining.remove(candidate)

    assert removed == ["e24", "e25"]
    assert remaining == [add]
    assert policy.asked == ["choose_removed"] * 3
    assert [len(question.candidates) for question in policy.questions] == [3, 2, 1]
    assert policy.questions[0].state is page


def test_the_fake_policy_drives_a_choice_loop_until_none():
    # The choice loop (section 5): ask for the next candidate, exercise it, ask
    # again, and backtrack on `none`.
    page = open_page()
    add = element("e23", "Add to cart")
    home = element("e20", "Home", impact="navigate")
    policy = FakeDecisionClient(chosen=[home, add, None])

    candidates = [add, home]
    chosen: list[str] = []
    while True:
        candidate = policy.choose_chosen(page, candidates)
        if candidate is None:
            break
        assert select_chosen(candidates, answer(candidate.element_id)) is candidate
        chosen.append(candidate.element_id)
        candidates.remove(candidate)

    assert chosen == ["e20", "e23"]
    assert candidates == []
    assert policy.asked == ["choose_chosen"] * 3


def test_a_stale_removal_answer_ends_the_loop_without_executing():
    page = open_page()
    add = element("e23", "Add to cart")
    delete = element("e24", "Delete item", impact="write")
    # The second answer repeats the candidate the first iteration removed.
    policy = FakeDecisionClient(removed=[delete, delete, None])

    remaining = [add, delete]
    executed: list[str] = []
    while True:
        candidate = policy.choose_removed(page, remaining)
        if candidate is None:
            break
        try:
            removal = select_removed(page, remaining, answer(candidate.element_id))
        except PolicyStaleRemoval:
            break
        executed.append(removal.element_id)
        remaining.remove(candidate)

    assert executed == ["e24"]
    assert remaining == [add]
