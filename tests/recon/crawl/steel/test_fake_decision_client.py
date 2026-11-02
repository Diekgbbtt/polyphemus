"""Seam under test: the fake decision client the policy tests will inject.

The fake answers the three question kinds from per-kind queues and records
every question it was asked, so a policy test can assert what the model saw.
"""
from __future__ import annotations

import pytest

from tests.recon.crawl.steel.support import DecisionQueueExhausted, FakeDecisionClient

PAGE = {"url": "https://example.test/products"}
CANDIDATES = [{"id": "e9", "label": "Load more"}, {"id": "e13", "label": "Delete account"}]
CATALOGUE = {
    "email": {"kind": "email", "description": "valid email"},
    "none": {"kind": "none", "description": "leave empty"},
}


def test_choose_removed_returns_the_queued_answer_and_records_the_question():
    client = FakeDecisionClient(removed=["e13"])

    answer = client.choose_removed(PAGE, CANDIDATES)

    assert answer == "e13"
    question = client.questions[0]
    assert question.kind == "choose_removed"
    assert question.state is PAGE
    assert question.candidates == tuple(CANDIDATES)


def test_choose_chosen_returns_answers_in_order_including_none():
    client = FakeDecisionClient(chosen=["e9", None])

    assert client.choose_chosen(PAGE, CANDIDATES) == "e9"
    assert client.choose_chosen(PAGE, []) is None
    assert client.asked == ["choose_chosen", "choose_chosen"]


def test_choose_value_returns_the_queued_catalogue_keys():
    client = FakeDecisionClient(values=["email", "none"])
    field = {"name": "contact", "type": "email"}

    assert client.choose_value(field, CATALOGUE) == "email"
    assert client.choose_value(field, CATALOGUE) == "none"
    question = client.questions[0]
    assert question.kind == "choose_value"
    assert question.field is field
    assert question.catalogue == CATALOGUE


def test_all_three_question_kinds_are_recorded_in_ask_order():
    client = FakeDecisionClient(removed=[None], chosen=[None], values=["none"])

    client.choose_removed(PAGE, CANDIDATES)
    client.choose_chosen(PAGE, CANDIDATES)
    client.choose_value({"name": "contact"}, CATALOGUE)

    assert client.asked == ["choose_removed", "choose_chosen", "choose_value"]


def test_queue_exhaustion_fails_loudly_and_still_records_the_question():
    client = FakeDecisionClient()

    with pytest.raises(DecisionQueueExhausted, match="choose_removed") as excinfo:
        client.choose_removed(PAGE, CANDIDATES)

    assert "no queued choose_removed answer" in str(excinfo.value)
    assert client.asked == ["choose_removed"]
