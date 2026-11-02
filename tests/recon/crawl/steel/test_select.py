"""Seam under test: the choice and value protocol, through a fake policy.

Spec: `docs/design/steel-crawl-spec.md` sections 6.4, 6.6, 8.1, 8.2, and 12;
seam 5 of `docs/design/steel-crawl-implementation-plan.md` section 3.

The impact order and the change-semantics ranking live in the prompt (spec 6.6):
Jev sees the order and the control facts, and its answer is authoritative. These
tests assert the contract around that answer - which traversal move the outcome
names, and which catalogue key fills a field - never a second symbolic ranker.
Expected values come from the spec, never from re-reading the implementation.
"""
from __future__ import annotations

import json

import pytest

from polymerhus.recon.crawl.steel.command import CaptureChannel, ImpactClass
from polymerhus.recon.crawl.steel.enumerate import (
    ChangeSemantics,
    Element,
    ElementMap,
    ElementType,
    SnapshotNode,
)
from polymerhus.recon.crawl.steel.policy.jev import JevPolicy
from polymerhus.recon.crawl.steel.policy.port import PolicyInvalidChoice
from polymerhus.recon.crawl.steel.policy.select import (
    DEFAULT_VALUE_CATALOGUE,
    ValueCatalogue,
    ValueEntry,
    ValueValidation,
    choose_field_value,
    decide_choice,
    field_kind_for,
    matching_keys,
    validate_value,
)
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance
from tests.recon.crawl.steel.support import FakeDecisionClient
from tests.recon.crawl.steel.support.jev import FakeAskClient

URL = "https://example.test/products"


def open_page() -> tuple[BrowserState, PageInstance]:
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_1",
        url=URL,
        final_url=URL,
        title="Products",
        snapshot=(),
    )
    return state, page


def element(
    element_id: str,
    label: str,
    *,
    impact: ImpactClass = "local_state",
    capture: CaptureChannel = "dom",
) -> Element:
    """One candidate carrying the identity and change semantics the choice reads."""
    return Element(
        element_id=element_id,
        fingerprint=f"fingerprint_{element_id}",
        element_type=ElementType.BUTTON,
        name=label,
        impact=impact,
        capture=capture,
        change=ChangeSemantics(impact=impact, capture=capture),
    )


def test_the_choice_question_carries_the_impact_order_as_the_soft_prior():
    _, page = open_page()
    add = element("e23", "Add to cart")
    home = element("e20", "Home", impact="navigate")
    client = FakeAskClient(chosen=["e20"])

    decide_choice(JevPolicy(client), page, [add, home])

    assert client.calls[0].state["impact_order"] == [
        "observe",
        "local_state",
        "read",
        "write",
        "navigate",
    ]


def test_a_chosen_navigation_pushes_the_current_page():
    # Jev answers a navigation although a lower-impact local-state candidate is
    # available: the order is a soft prior, so the answer is authoritative.
    _, page = open_page()
    add = element("e23", "Add to cart")
    home = element("e20", "Home", impact="navigate")
    client = FakeAskClient(chosen=["e20"])

    outcome = decide_choice(JevPolicy(client), page, [add, home])

    assert outcome.chosen is home
    assert outcome.navigates is True
    assert outcome.restores is False


def test_a_chosen_local_state_action_is_recorded_and_the_page_restored():
    _, page = open_page()
    add = element("e23", "Add to cart")
    home = element("e20", "Home", impact="navigate")
    client = FakeAskClient(chosen=["e23"])

    outcome = decide_choice(JevPolicy(client), page, [add, home])

    assert outcome.chosen is add
    assert outcome.navigates is False
    assert outcome.restores is True


def test_a_none_choice_asks_for_neither_a_push_nor_a_restore():
    _, page = open_page()
    add = element("e23", "Add to cart")
    client = FakeAskClient(chosen=[None])

    outcome = decide_choice(JevPolicy(client), page, [add])

    assert outcome.chosen is None
    assert outcome.navigates is False
    assert outcome.restores is False


# A disclosure button and the hidden panel it controls, whose own candidate is
# still unconsumed. Jev ranks this above a control with no new surface (spec 6.5,
# 6.6), so the facts that ranking reads must cross the request.
CONTROL_NODES = (
    SnapshotNode(
        tag="button",
        ref="e23",
        role="button",
        name="Filters",
        attributes={"type": "button", "aria-controls": "filters"},
    ),
    SnapshotNode(
        tag="div",
        ref="e24",
        attributes={"id": "filters", "hidden": ""},
        children=(
            SnapshotNode(
                tag="button",
                ref="e25",
                role="button",
                name="Apply",
                attributes={"type": "button"},
            ),
        ),
    ),
)


def test_the_choice_question_carries_a_hidden_target_and_its_unconsumed_candidates():
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_1",
        url=URL,
        final_url=URL,
        title="Products",
        snapshot=CONTROL_NODES,
    )
    candidates = ElementMap().project(
        CONTROL_NODES, page=page, state=state, page_url=URL
    )
    client = FakeAskClient(chosen=["e23"])

    decide_choice(JevPolicy(client), page, candidates)

    criteria = client.calls[0].state["candidates"]
    filters = next(item for item in criteria if item["element_id"] == "e23")
    fact = filters["change"]["control_facts"][0]
    assert fact["target_id"] == "filters"
    assert fact["hidden"] is True
    assert fact["consumed_count"] == 0
    assert "Apply" in fact["target_projection"][0]


def test_the_default_catalogue_is_the_spec_value_catalogue():
    # Spec 8.2 verbatim: the keys, their values, kinds, and descriptions. The
    # `first` value is the sentinel the field resolver owns, never a typed value.
    assert dict(DEFAULT_VALUE_CATALOGUE.entries) == {
        "email": ValueEntry(
            value="qa-crawl+<run>@example.test",
            kind="email",
            description="valid email",
        ),
        "search": ValueEntry(
            value="test", kind="text", description="short search term"
        ),
        "name": ValueEntry(value="QA Crawler", kind="text", description="person name"),
        "number": ValueEntry(value="42", kind="number", description="small integer"),
        "date": ValueEntry(value="2026-01-01", kind="date", description="ISO date"),
        "url": ValueEntry(
            value="https://example.test/", kind="url", description="valid URL"
        ),
        "file": ValueEntry(
            value="crawl-upload.txt", kind="file", description="small text file"
        ),
        "first": ValueEntry(
            value="__first_option__", kind="option", description="first non-empty option"
        ),
        "none": ValueEntry(value=None, kind="none", description="leave empty"),
    }


def test_a_catalogue_with_a_run_id_resolves_the_email_placeholder():
    catalogue = ValueCatalogue(
        entries=DEFAULT_VALUE_CATALOGUE.entries, run_id="run-123"
    )

    assert catalogue.value_for("email") == "qa-crawl+run-123@example.test"
    choice = choose_field_value(
        {"name": "contact", "type": "email"}, catalogue, FakeDecisionClient()
    )
    assert choice.value == "qa-crawl+run-123@example.test"


def test_an_empty_run_id_only_removes_the_placeholder():
    # The documented empty-run behaviour: the placeholder is removed and no
    # other entry value is touched. The executor's pattern check decides whether
    # the resulting address is usable for the field.
    catalogue = ValueCatalogue(entries=DEFAULT_VALUE_CATALOGUE.entries)

    assert catalogue.run_id == ""
    assert catalogue.value_for("email") == "qa-crawl+@example.test"
    assert catalogue.value_for("search") == "test"
    assert catalogue.value_for("url") == "https://example.test/"


def test_value_for_a_none_or_unknown_key_is_none():
    assert DEFAULT_VALUE_CATALOGUE.value_for("none") is None
    assert DEFAULT_VALUE_CATALOGUE.value_for("missing") is None


@pytest.mark.parametrize(
    ("field_type", "kind"),
    [
        ("text", "text"),
        ("search", "text"),
        ("textarea", "text"),
        ("email", "email"),
        ("number", "number"),
        ("range", "number"),
        ("date", "date"),
        ("url", "url"),
        ("file", "file"),
        ("select", "option"),
        ("select-one", "option"),
        ("select-multiple", "option"),
        ("radio", "option"),
        ("checkbox", "option"),
        ("password", "none"),
        ("hidden", "none"),
        ("submit", "none"),
        ("button", "none"),
        ("reset", "none"),
        ("image", "none"),
    ],
)
def test_the_field_type_maps_to_its_catalogue_kind(field_type, kind):
    assert field_kind_for({"name": "field", "type": field_type}) == kind


def test_a_field_without_a_type_is_a_text_field():
    # An input without a type attribute is a text input in HTML.
    assert field_kind_for({"name": "q"}) == "text"


def test_an_unknown_field_type_has_no_safe_value_shape():
    # No catalogue entry matches an unrecognised shape, so the field is left
    # empty rather than typed with a value the browser would reject.
    assert field_kind_for({"name": "colour", "type": "color"}) == "none"


def test_the_matching_keys_are_the_entries_of_the_field_kind_excluding_none():
    # A text field matches both text entries, and never the email, option, or
    # `none` entry; a select matches only `first`; a password matches nothing.
    assert matching_keys({"name": "q", "type": "text"}, DEFAULT_VALUE_CATALOGUE) == (
        "search",
        "name",
    )
    assert matching_keys(
        {"name": "size", "type": "select-one"}, DEFAULT_VALUE_CATALOGUE
    ) == ("first",)
    assert matching_keys(
        {"name": "secret", "type": "password"}, DEFAULT_VALUE_CATALOGUE
    ) == ()


def test_one_matching_entry_is_used_without_asking_the_policy():
    field = {"name": "contact", "type": "email"}
    catalogue = ValueCatalogue(
        entries=DEFAULT_VALUE_CATALOGUE.entries, run_id="run-123"
    )
    policy = FakeDecisionClient()

    choice = choose_field_value(field, catalogue, policy)

    assert choice.key == "email"
    assert choice.value == "qa-crawl+run-123@example.test"
    assert choice.source == "single"
    assert choice.skip_field is False
    assert choice.skip_form is False
    assert policy.questions == []


def test_more_than_one_match_asks_the_policy_over_the_catalogue_keys():
    field = {
        "name": "q",
        "type": "text",
        "label": "Search",
        "value": "should-not-leak",
    }
    policy = FakeDecisionClient(values=["name"])

    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, policy)

    assert choice.key == "name"
    assert choice.value == "QA Crawler"
    assert choice.source == "jev"
    assert choice.skip_field is False
    assert policy.asked == ["choose_value"]
    asked = policy.questions[0]
    # The field crosses the port as its contract only: the carried value never
    # reaches the model.
    assert asked.field == {"name": "q", "type": "text", "label": "Search"}
    assert asked.catalogue == DEFAULT_VALUE_CATALOGUE.entries


def test_a_none_answer_declines_the_field():
    field = {"name": "q", "type": "text"}
    policy = FakeDecisionClient(values=[None])

    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, policy)

    assert choice.key == "none"
    assert choice.value is None
    assert choice.source == "none"
    assert choice.skip_field is True
    assert choice.skip_form is False


def test_no_matching_entry_declines_without_asking_the_policy():
    field = {"name": "secret", "type": "password"}
    policy = FakeDecisionClient()

    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, policy)

    assert choice.key == "none"
    assert choice.value is None
    assert choice.source == "none"
    assert choice.skip_field is True
    assert policy.questions == []


def test_a_skipped_required_field_skips_the_form():
    field = {"name": "secret", "type": "password", "required": True}
    policy = FakeDecisionClient()

    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, policy)

    assert choice.skip_field is True
    assert choice.skip_form is True


def test_a_policy_key_outside_the_catalogue_is_a_protocol_error():
    field = {"name": "q", "type": "text"}
    policy = FakeDecisionClient(values=["password"])

    with pytest.raises(PolicyInvalidChoice) as excinfo:
        choose_field_value(field, DEFAULT_VALUE_CATALOGUE, policy)

    assert excinfo.value.code == "policy_invalid_choice"
    assert excinfo.value.kind == "choose_value"
    assert excinfo.value.choice == "password"
    assert "email" in excinfo.value.valid
    assert "none" in excinfo.value.valid


def test_first_resolves_to_the_first_non_empty_option():
    field = {
        "name": "size",
        "type": "select-one",
        "options": ["", "  ", "Medium", "Large"],
    }

    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, FakeDecisionClient())

    assert choice.key == "first"
    assert choice.value == "Medium"
    assert choice.source == "single"
    assert choice.skip_field is False


def test_first_reads_the_value_of_an_option_object():
    field = {
        "name": "size",
        "type": "select-one",
        "options": [
            {"value": "s", "label": "Small"},
            {"value": "m", "label": "Medium"},
        ],
    }

    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, FakeDecisionClient())

    assert choice.value == "s"


def test_first_without_a_non_empty_option_skips_the_field():
    field = {
        "name": "size",
        "type": "select-one",
        "options": ["", "  "],
        "required": True,
    }

    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, FakeDecisionClient())

    assert choice.value is None
    assert choice.skip_field is True
    assert choice.skip_form is True


def test_the_manifest_records_the_chosen_key_and_never_the_value():
    field = {"name": "contact", "type": "email"}
    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, FakeDecisionClient())

    record = choice.manifest_record()

    assert record == {"value_key": "email"}
    assert "qa-crawl+<run>@example.test" not in str(record)


def test_the_value_never_enters_the_request_through_the_real_policy():
    field = {"name": "q", "type": "text", "value": "should-not-leak"}
    client = FakeAskClient(values=["name"])

    choice = choose_field_value(field, DEFAULT_VALUE_CATALOGUE, JevPolicy(client))

    payload = json.dumps(
        {"state": client.calls[0].state, "questions": client.calls[0].questions}
    )
    assert choice.value == "QA Crawler"
    for value in (
        "should-not-leak",
        "QA Crawler",
        "qa-crawl+<run>@example.test",
        "https://example.test/",
        "2026-01-01",
        "crawl-upload.txt",
    ):
        assert value not in payload


def test_the_pattern_must_match_the_whole_value():
    # `re.fullmatch`, not `re.search`: a value that merely contains a match is
    # not a valid field value (spec 8.2).
    field = {"name": "code", "type": "text", "pattern": "[a-z]+"}

    assert validate_value("abc", field).ok is True
    assert validate_value("abc1", field).ok is False


def test_a_numeric_value_outside_the_min_and_max_is_invalid():
    field = {"name": "qty", "type": "number", "min": "3", "max": "120"}

    assert validate_value("42", field).ok is True
    assert validate_value("2", field).ok is False
    assert validate_value("121", field).ok is False


def test_a_date_outside_the_iso_min_and_max_is_invalid():
    field = {"name": "when", "type": "date", "min": "2026-01-01", "max": "2026-12-31"}

    assert validate_value("2026-06-15", field).ok is True
    assert validate_value("2025-12-31", field).ok is False
    assert validate_value("2027-01-01", field).ok is False
    # A date field's value must itself be an ISO date when bounds are present.
    assert validate_value("15/06/2026", field).ok is False


def test_a_value_outside_the_options_is_invalid():
    field = {"name": "size", "type": "select-one", "options": ["S", "M", "L"]}

    assert validate_value("M", field).ok is True
    assert validate_value("XL", field).ok is False


def test_the_options_membership_reads_an_option_object_value():
    field = {
        "name": "size",
        "type": "select-one",
        "options": [{"value": "s", "label": "Small"}, {"value": "m", "label": "Medium"}],
    }

    assert validate_value("m", field).ok is True
    assert validate_value("Medium", field).ok is False


def test_a_value_with_no_constraints_is_valid():
    assert validate_value("anything", {"name": "q", "type": "text"}) == (
        ValueValidation(ok=True)
    )


def test_a_failed_validation_names_the_reason():
    result = validate_value("2", {"name": "qty", "type": "number", "min": "3"})

    assert result.ok is False
    assert "minimum" in result.reason


def test_a_malformed_pattern_fails_closed():
    # A pattern that does not parse cannot be shown to match, so the value is
    # rejected rather than typed unvalidated.
    result = validate_value("abc", {"name": "q", "type": "text", "pattern": "["})

    assert result.ok is False
    assert "regular expression" in result.reason
