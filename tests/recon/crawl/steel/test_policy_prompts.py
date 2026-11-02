"""Seam under test: the prompt contract, through the three request builders.

Spec: `docs/design/steel-crawl-spec.md` sections 6.5, 6.6, 6.7, 7, 8.2, and
Appendix B; seam 5 of `docs/design/steel-crawl-implementation-plan.md` section 3.

Every test asserts the request a decision client would receive: the compact state
the model reads, the instructions it answers by, and the bounded answer space it
may choose from. The expected text and the expected keys come from the spec and
the element map, never from re-reading the builder.
"""
from __future__ import annotations

from collections.abc import Sequence

from polymerhus.recon.crawl.steel.enumerate import Element, ElementMap, SnapshotNode
from polymerhus.recon.crawl.steel.policy.prompts import (
    IMPACT_ORDER,
    build_choice_request,
    build_removal_request,
    build_value_request,
)
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance

# A page with one safe control, one destructive control, and the registration
# form the removal prompt must never remove (spec 6.7, 7).
NODES = (
    SnapshotNode(
        tag="button",
        ref="e23",
        role="button",
        name="Add to cart",
        attributes={"type": "button", "onclick": "addToCart()"},
    ),
    SnapshotNode(
        tag="button",
        ref="e24",
        role="button",
        name="Delete item",
        attributes={"type": "button"},
    ),
    SnapshotNode(
        tag="form",
        ref="e25",
        role="form",
        name="Register",
        attributes={"action": "/register", "method": "post"},
    ),
)


def project(
    nodes: Sequence[SnapshotNode] = NODES,
    *,
    url: str = "https://example.test/products",
    title: str = "Products",
    final_url: str | None = None,
) -> tuple[PageInstance, list[Element]]:
    """Open one page and project its candidates through the element map."""
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_1",
        url=url,
        final_url=final_url or url,
        title=title,
        snapshot=tuple(nodes),
    )
    return page, ElementMap().project(
        tuple(nodes), page=page, state=state, page_url=url
    )


def test_the_removal_request_carries_the_page_the_categories_and_the_candidates():
    page, candidates = project()

    request = build_removal_request(page, candidates, overlays=("Newsletter",))

    assert request.kind == "choose_removed"
    assert request.state["page"] == {
        "url": "https://example.test/products",
        "title": "Products",
    }
    assert request.state["overlays"] == ["Newsletter"]
    assert request.state["forbidden"] == ["auth state", "payment", "destruction"]
    assert (
        request.state["safe_exception"]
        == "account registration is a safe write, not auth state"
    )
    assert [criterion["element_id"] for criterion in request.state["candidates"]] == [
        "e23",
        "e24",
        "e25",
    ]


def test_the_removal_request_carries_no_overlay_by_default():
    page, candidates = project()

    request = build_removal_request(page, candidates)

    assert request.state["overlays"] == []


def test_the_removal_instructions_are_the_spec_prompt():
    page, candidates = project()

    question = build_removal_request(page, candidates).questions["choose_removed"]

    assert question.type == "choice"
    assert (
        "You are removing unsafe elements from the crawl candidate set."
        in question.instructions
    )
    assert (
        "Forbidden categories: auth state, payment, destruction."
        in question.instructions
    )
    assert "Account registration is a safe write, not auth state." in (
        question.instructions
    )
    assert "Do not remove a registration form." in question.instructions
    assert (
        "Choose none if no candidate belongs to a forbidden category."
        in question.instructions
    )


def test_the_page_state_names_the_document_the_candidates_came_from():
    page, candidates = project(
        url="https://example.test/start",
        final_url="https://example.test/products",
    )

    request = build_removal_request(page, candidates)

    assert request.state["page"]["url"] == "https://example.test/products"


def test_the_removal_answer_space_is_the_candidate_ids_and_none():
    page, candidates = project()

    question = build_removal_request(page, candidates).questions["choose_removed"]

    assert list(question.criteria) == ["e23", "e24", "e25", "none"]
    assert "Delete item" in question.criteria["e24"]
    assert question.criteria["none"] == "no forbidden element remains"


def test_the_impact_order_is_the_offer_order_of_the_spec():
    assert IMPACT_ORDER == ("observe", "local_state", "read", "write", "navigate")


def test_the_choice_request_carries_the_page_the_impact_order_and_the_candidates():
    page, candidates = project()

    request = build_choice_request(page, candidates)

    assert request.kind == "choose_chosen"
    assert request.state["page"] == {
        "url": "https://example.test/products",
        "title": "Products",
    }
    assert request.state["impact_order"] == [
        "observe",
        "local_state",
        "read",
        "write",
        "navigate",
    ]
    assert [criterion["element_id"] for criterion in request.state["candidates"]] == [
        "e23",
        "e24",
        "e25",
    ]


def test_each_choice_criterion_carries_the_change_semantics_of_the_element():
    page, candidates = project()

    criteria = build_choice_request(page, candidates).state["candidates"]

    assert set(criteria[0]) == {
        "element_id",
        "element_type",
        "label",
        "impact",
        "capture",
        "href",
        "action",
        "change",
    }
    assert criteria[0]["element_type"] == "BUTTON"
    assert criteria[0]["label"] == "Add to cart"
    assert criteria[0]["impact"] == "local_state"
    assert criteria[0]["capture"] == "dom"
    assert criteria[0]["change"]["impact"] == "local_state"
    assert criteria[0]["change"]["capture"] == "dom"
    assert criteria[0]["change"]["handler"] == "onclick"
    assert criteria[2]["change"]["impact"] == "write"
    assert criteria[2]["change"]["handler"] == "onsubmit"


def test_the_choice_instructions_are_the_spec_decision_tree():
    page, candidates = project()

    question = build_choice_request(page, candidates).questions["choose_chosen"]

    assert (
        "You are choosing the next element to exercise on the current page."
        in question.instructions
    )
    assert (
        "Impact order: observe, local_state, read, write, navigate."
        in question.instructions
    )
    assert "Choose the lowest non-empty impact class." in question.instructions
    assert "Choose none if no candidate remains." in question.instructions
    assert list(question.criteria) == ["e23", "e24", "e25", "none"]
    assert question.criteria["none"] == "no candidate remains"


def test_a_long_label_is_bounded_and_the_dom_never_enters_the_criteria():
    long_label = " ".join(["Load more"] * 40)
    nodes = (
        SnapshotNode(
            tag="button",
            ref="e30",
            role="button",
            name=long_label,
            attributes={"type": "button", "onclick": "loadMore()"},
        ),
    )
    page, candidates = project(nodes)

    criterion = build_choice_request(page, candidates).state["candidates"][0]

    assert len(criterion["label"]) <= 60
    assert criterion["label"].endswith("...")
    assert "attributes" not in criterion
    assert criterion["change"]["controls"] == []


# A field contract plus the value the form already carries, and a catalogue whose
# values must never reach the request (spec 8.2).
FIELD = {
    "name": "contact",
    "type": "email",
    "label": "Contact email",
    "pattern": ".+@.+",
    "min": "3",
    "max": "120",
    "value": "should-not-leak",
}
CATALOGUE = {
    "email": {
        "value": "qa-crawl+run42@example.test",
        "kind": "email",
        "description": "valid email",
    },
    "search": {
        "value": "secret-search-value",
        "kind": "text",
        "description": "short search term",
    },
    "none": {"value": None, "kind": "none", "description": "leave empty"},
}


def test_the_value_request_carries_the_field_contract_and_the_catalogue():
    request = build_value_request(FIELD, CATALOGUE)

    assert request.kind == "choose_value"
    assert request.state["field"] == {
        "name": "contact",
        "type": "email",
        "label": "Contact email",
        "pattern": ".+@.+",
        "min": "3",
        "max": "120",
    }
    assert request.state["catalogue"] == [
        {"key": "email", "kind": "email", "description": "valid email"},
        {"key": "search", "kind": "text", "description": "short search term"},
        {"key": "none", "kind": "none", "description": "leave empty"},
    ]


def test_the_value_answer_space_is_the_catalogue_keys_and_their_descriptions():
    question = build_value_request(FIELD, CATALOGUE).questions["choose_value"]

    assert question.type == "choice"
    assert question.criteria == {
        "email": "valid email",
        "search": "short search term",
        "none": "leave empty",
    }


def test_the_value_instructions_are_the_spec_value_protocol():
    question = build_value_request(FIELD, CATALOGUE).questions["choose_value"]

    assert "Choose one catalogue key for the form field." in question.instructions
    assert "The field contract is in the state." in question.instructions
    assert "Choose none to leave the field empty." in question.instructions
    assert "The value never enters the request" in question.instructions


def test_the_value_never_enters_the_request():
    request = build_value_request(FIELD, CATALOGUE)

    payload = request.model_dump_json()

    assert "qa-crawl+run42@example.test" not in payload
    assert "secret-search-value" not in payload
    assert "should-not-leak" not in payload


def test_a_catalogue_without_none_still_allows_the_decline():
    request = build_value_request(
        {"name": "q", "type": "text"},
        {"search": {"kind": "text", "description": "short search term"}},
    )

    assert request.questions["choose_value"].criteria == {
        "search": "short search term",
        "none": "leave the field empty",
    }
