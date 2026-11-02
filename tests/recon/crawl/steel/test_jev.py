"""Seam under test: the Jev adapter, through a fake async TypeSafe client.

Spec: `docs/design/steel-crawl-spec.md` sections 6.7, 7, 8.2, and 12; seam 5 of
`docs/design/steel-crawl-implementation-plan.md` section 3.

The crawl is synchronous and the TypeSafe client is async. These tests prove the
adapter owns that difference: every ask runs on the adapter's private loop thread
and returns to the caller as a plain mapping, the client's configured model is
used, and `close` releases both the client and the loop thread. The decision
policy tests drive the same adapter through a fake synchronous decision client,
so the request shape the provider sees is asserted without a provider call.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from polymerhus.recon.crawl.steel.command import CaptureChannel, ImpactClass
from polymerhus.recon.crawl.steel.enumerate import (
    ChangeSemantics,
    Element,
    ElementType,
)
from polymerhus.recon.crawl.steel.policy.jev import (
    DecisionClient,
    JevPolicy,
    PolicyProviderError,
    TypeSafeDecisionClient,
)
from polymerhus.recon.crawl.steel.policy.port import (
    Policy,
    PolicyInvalidChoice,
    PolicyProtocolError,
)
from polymerhus.recon.crawl.steel.state import (
    BrowserState,
    PageInstance,
    SnapshotFacts,
)
from tests.recon.crawl.steel.support.jev import (
    MISSING_ANSWER,
    FakeAskClient,
    FakeAsyncTypeSafe,
)

STATE: dict[str, Any] = {
    "page": {"url": "https://example.test/products", "title": "Products"}
}
QUESTIONS: dict[str, Any] = {
    "choose_chosen": {
        "type": "choice",
        "instructions": "Choose the next element to exercise.",
        "criteria": {"e23": 'button "Add to cart"', "none": "no candidate remains"},
    }
}
RESPONSE: dict[str, Any] = {
    "answers": {"choose_chosen": {"type": "choice", "choice": "e23"}}
}


def test_the_adapter_runs_the_async_ask_on_its_own_loop_thread():
    fake = FakeAsyncTypeSafe(response=RESPONSE)
    adapter = TypeSafeDecisionClient(fake)
    before = {thread.ident for thread in threading.enumerate()}

    try:
        response = adapter.ask(STATE, QUESTIONS)
        loop_threads = {thread.ident for thread in threading.enumerate()} - before
        call = fake.calls[0]
    finally:
        adapter.close()

    assert response == RESPONSE
    assert call.state == STATE
    assert call.questions == QUESTIONS
    # No override was passed, so the client's configured model is the one used.
    assert call.model == "jev-latest"
    assert call.thread_id != threading.get_ident()
    assert call.thread_id in loop_threads


def test_close_closes_the_async_client_and_stops_the_loop_thread():
    fake = FakeAsyncTypeSafe(response=RESPONSE)
    adapter = TypeSafeDecisionClient(fake)
    before = {thread.ident for thread in threading.enumerate()}

    adapter.ask(STATE, QUESTIONS)
    ask_thread = fake.calls[0].thread_id
    loop_threads = [
        thread
        for thread in threading.enumerate()
        if thread.ident not in before
    ]

    adapter.close()

    assert fake.closed is True
    # The close coroutine runs on the same owned loop, not on the caller's thread.
    assert fake.close_thread_id == ask_thread
    assert all(not thread.is_alive() for thread in loop_threads)


def test_close_before_any_ask_still_closes_the_client():
    fake = FakeAsyncTypeSafe()
    adapter = TypeSafeDecisionClient(fake)

    adapter.close()

    assert fake.closed is True


def open_page(
    url: str = "https://example.test/products",
    *,
    facts: SnapshotFacts | None = None,
) -> tuple[BrowserState, PageInstance]:
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_1",
        url=url,
        final_url=url,
        title="Products",
        snapshot=(),
        facts=facts,
    )
    return state, page


def element(
    element_id: str,
    label: str,
    *,
    impact: ImpactClass = "local_state",
    capture: CaptureChannel = "dom",
) -> Element:
    """One candidate carrying the identity and change semantics the policy reads."""
    return Element(
        element_id=element_id,
        fingerprint=f"fingerprint_{element_id}",
        element_type=ElementType.BUTTON,
        name=label,
        impact=impact,
        capture=capture,
        change=ChangeSemantics(impact=impact, capture=capture),
    )


def test_the_policy_removes_the_answered_candidate_then_declines():
    state, page = open_page()
    add = element("e23", "Add to cart")
    delete = element("e24", "Delete item", impact="write")
    client = FakeAskClient(removed=["e24", None])
    policy = JevPolicy(client, state=state)

    first = policy.choose_removed(page, [add, delete])
    second = policy.choose_removed(page, [add])

    assert first == delete
    assert second is None
    assert client.asked == ["choose_removed", "choose_removed"]
    # The second question saw only the candidate that remained.
    assert list(client.calls[1].questions["choose_removed"]["criteria"]) == [
        "e23",
        "none",
    ]


def test_the_removal_question_states_the_categories_and_the_registration_exception():
    state, page = open_page()
    add = element("e23", "Add to cart")
    delete = element("e24", "Delete item", impact="write")
    client = FakeAskClient(removed=[None])
    policy = JevPolicy(client, state=state)

    policy.choose_removed(page, [add, delete])

    request = client.calls[0]
    question = request.questions["choose_removed"]
    assert (
        "Forbidden categories: auth state, payment, destruction."
        in question["instructions"]
    )
    assert (
        "Account registration is a safe write, not auth state."
        in question["instructions"]
    )
    assert "Do not remove a registration form." in question["instructions"]
    assert request.state["forbidden"] == ["auth state", "payment", "destruction"]
    assert (
        request.state["safe_exception"]
        == "account registration is a safe write, not auth state"
    )


def test_the_removal_question_carries_the_cached_overlays_of_the_page():
    facts = SnapshotFacts(
        overlay_flags=frozenset({"Newsletter", "Cookie banner"})
    )
    state, page = open_page(facts=facts)
    add = element("e23", "Add to cart")
    client = FakeAskClient(removed=[None])
    policy = JevPolicy(client, state=state)

    policy.choose_removed(page, [add])

    assert client.calls[0].state["overlays"] == ["Cookie banner", "Newsletter"]


def test_the_removal_question_carries_no_overlays_without_a_state():
    _, page = open_page()
    add = element("e23", "Add to cart")
    client = FakeAskClient(removed=[None])
    policy = JevPolicy(client)

    policy.choose_removed(page, [add])

    assert client.calls[0].state["overlays"] == []


def test_the_policy_chooses_the_answered_candidate_then_declines():
    _, page = open_page()
    add = element("e23", "Add to cart")
    home = element("e20", "Home", impact="navigate")
    client = FakeAskClient(chosen=["e23", None])
    policy = JevPolicy(client)

    assert policy.choose_chosen(page, [add, home]) == add
    assert policy.choose_chosen(page, [home]) is None
    assert client.asked == ["choose_chosen", "choose_chosen"]
    # The second question is over the candidate that remained only.
    assert list(client.calls[1].questions["choose_chosen"]["criteria"]) == [
        "e20",
        "none",
    ]


def test_a_chosen_id_outside_the_candidates_is_an_invalid_choice():
    _, page = open_page()
    add = element("e23", "Add to cart")
    client = FakeAskClient(chosen=["e99"])
    policy = JevPolicy(client)

    with pytest.raises(PolicyInvalidChoice) as excinfo:
        policy.choose_chosen(page, [add])

    assert excinfo.value.code == "policy_invalid_choice"
    assert excinfo.value.kind == "choose_chosen"
    assert excinfo.value.choice == "e99"


def test_the_policy_chooses_a_catalogue_key_and_none_for_a_field():
    client = FakeAskClient(values=["email", None])
    policy = JevPolicy(client)
    field = {"name": "contact", "type": "email"}
    catalogue = {
        "email": {"kind": "email", "description": "valid email"},
        "none": {"kind": "none", "description": "leave empty"},
    }

    assert policy.choose_value(field, catalogue) == "email"
    assert policy.choose_value(field, catalogue) is None
    question = client.calls[0].questions["choose_value"]
    assert "Choose one catalogue key for the form field." in question["instructions"]
    assert question["criteria"] == {
        "email": "valid email",
        "none": "leave empty",
    }


def test_the_jev_policy_satisfies_the_policy_protocol():
    assert isinstance(JevPolicy(FakeAskClient()), Policy)


def test_the_fake_ask_client_satisfies_the_decision_client_protocol():
    assert isinstance(FakeAskClient(), DecisionClient)


def test_a_missing_answer_is_an_invalid_choice_protocol_error():
    _, page = open_page()
    add = element("e23", "Add to cart")
    client = FakeAskClient(removed=[MISSING_ANSWER])
    policy = JevPolicy(client)

    with pytest.raises(PolicyInvalidChoice) as excinfo:
        policy.choose_removed(page, [add])

    assert excinfo.value.code == "policy_invalid_choice"
    assert excinfo.value.kind == "choose_removed"
    assert excinfo.value.valid == ("e23", "none")


def test_a_malformed_answer_is_an_invalid_choice_protocol_error():
    _, page = open_page()
    add = element("e23", "Add to cart")
    # An empty choice cannot name a candidate, so it broke the answer protocol.
    client = FakeAskClient(removed=[{"type": "choice", "choice": ""}])
    policy = JevPolicy(client)

    with pytest.raises(PolicyInvalidChoice) as excinfo:
        policy.choose_removed(page, [add])

    assert excinfo.value.code == "policy_invalid_choice"
    assert excinfo.value.kind == "choose_removed"
    assert excinfo.value.valid == ("e23", "none")


def test_a_provider_error_is_a_typed_policy_failure_distinct_from_a_protocol_error():
    _, page = open_page()
    add = element("e23", "Add to cart")
    failure = TimeoutError("typesafe timed out")
    client = FakeAskClient(removed=[failure])
    policy = JevPolicy(client)

    with pytest.raises(PolicyProviderError) as excinfo:
        policy.choose_removed(page, [add])

    assert excinfo.value.code == "policy_provider_error"
    assert excinfo.value.kind == "choose_removed"
    assert excinfo.value.cause is failure
    assert excinfo.value.__cause__ is failure
    assert not isinstance(excinfo.value, PolicyProtocolError)
    assert "typesafe timed out" in str(excinfo.value)


def test_a_client_failure_across_the_bridge_is_a_typed_policy_failure():
    _, page = open_page()
    add = element("e23", "Add to cart")
    fake = FakeAsyncTypeSafe(error=RuntimeError("provider down"))
    adapter = TypeSafeDecisionClient(fake)
    policy = JevPolicy(adapter)

    try:
        with pytest.raises(PolicyProviderError) as excinfo:
            policy.choose_removed(page, [add])
    finally:
        adapter.close()

    assert excinfo.value.code == "policy_provider_error"
    assert excinfo.value.kind == "choose_removed"
    assert isinstance(excinfo.value.cause, RuntimeError)
