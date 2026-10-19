"""Arm L (#385): the structured-channel recovery at the session seam.

The arm K white-jotter shape: a structured turn answered with the payload as
message TEXT (voluntary function calling), the tool-only seam read it as an
empty structured result, and the empty+reasoning signature fired the BLACKLOOP
recovery - an instruction about unbounded thinking loops that does not apply,
whose re-ask drifted to text again and silently dropped the batch. These tests
pin the replacement: ONE corrective re-ask that names the tool, no blackloop
misfire, and the parsed payload accepted fail-open when the correction still
does not land.

Unit tier: the seam's collaborators (`run_session_turn`,
`structured_response_format`) are stubbed; no model, no database.
"""
from __future__ import annotations

import json
import logging

import pytest
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage

from polymerhus.app.llm import session as S
from polymerhus.analysis.analyser_types import L1DeltaBatch

PAYLOAD = {
    "systems": [
        {"kind": "RESTApi", "discriminator": "api",
         "props": {"description": "the JSON tier"}},
    ],
    "system_edges": [
        {"service_slug": "sign-in", "kind": "RESTApi", "discriminator": "api",
         "rel": "EXPOSED_VIA"},
    ],
}
PAYLOAD_JSON = json.dumps(PAYLOAD, indent=2)


def _text_answer(text: str = PAYLOAD_JSON) -> AIMessage:
    return AIMessage(content=text,
                     additional_kwargs={"reasoning_content": "Emit the six Systems now"})


def _turn(content, messages, *, blackloop: bool = False) -> S.SessionTurn:
    return S.SessionTurn(content=content, messages=list(messages), thread_id="t-1",
                         blackloop=blackloop, reasoning="reasoned")


@pytest.fixture()
def seam(monkeypatch):
    """Stub the seam's collaborators and capture the runner's calls."""
    calls: dict = {"turns": [], "scripted": []}

    def fake_run(role_id, thread_id, new_messages, **kwargs):
        calls["turns"].append((role_id, list(new_messages)))
        return calls["scripted"].pop(0)

    monkeypatch.setattr(
        S, "structured_response_format", lambda *a, **k: ToolStrategy(L1DeltaBatch)
    )
    monkeypatch.setattr(S, "run_session_turn", fake_run)
    return calls


def _run_turn(seam, script):
    seam["scripted"] = list(script)
    return S.stateful_turn(
        "mechanism_typist", "t-1", [HumanMessage(content="SYSTEMS now available")],
        checkpointer=None, schema=L1DeltaBatch,
    )


def test_a_text_channel_payload_gets_one_corrective_re_ask(seam, monkeypatch):
    blackloop_called = {"n": 0}
    monkeypatch.setattr(S, "_recover_blackloop",
                        lambda *a, **k: blackloop_called.__setitem__("n", 1))
    expected = L1DeltaBatch.model_validate(PAYLOAD)
    out = _run_turn(seam, [
        _turn(None, [HumanMessage(content="SYSTEMS now available"), _text_answer()]),
        _turn(expected, [AIMessage(content="", tool_calls=[
            {"name": "L1DeltaBatch", "args": PAYLOAD, "id": "call-1"}])]),
    ])
    assert out is expected
    assert blackloop_called["n"] == 0
    assert len(seam["turns"]) == 2
    correction = seam["turns"][1][1][0]
    assert isinstance(correction, HumanMessage)
    assert "L1DeltaBatch" in correction.content
    assert "TOOL CALL" in correction.content


def test_the_parsed_payload_is_accepted_when_the_correction_drifts_again(seam, caplog):
    with caplog.at_level(logging.WARNING):
        out = _run_turn(seam, [
            _turn(None, [HumanMessage(content="SYSTEMS now available"), _text_answer()]),
            _turn(None, [HumanMessage(content="SYSTEMS now available"), _text_answer()]),
        ])
    assert out is not None
    assert out.system_edges[0].service_slug == "sign-in"
    assert any("structured-channel" in record.message for record in caplog.records)


def test_the_parsed_payload_is_also_accepted_when_the_correction_raises(seam, monkeypatch):
    first = _turn(None, [HumanMessage(content="SYSTEMS now available"), _text_answer()])
    calls = {"n": 0}

    def fake_run(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return first
        raise RuntimeError("transport")

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    out = _run_turn(seam, [first])
    assert calls["n"] == 2
    assert out is not None
    assert out.systems[0].kind == "RESTApi"


def test_an_ambiguous_text_falls_back_to_the_blackloop_recovery(seam, monkeypatch):
    sentinel = object()
    calls = {"n": 0}

    def fake_blackloop(*a, **k):
        calls["n"] += 1
        return sentinel

    monkeypatch.setattr(S, "_recover_blackloop", fake_blackloop)
    ambiguous = PAYLOAD_JSON + "\n" + '{"systems": [], "system_edges": []}'
    out = _run_turn(seam, [
        _turn(None, [HumanMessage(content="SYSTEMS now available"),
                     _text_answer(ambiguous)]),
    ])
    assert out is sentinel
    assert calls["n"] == 1


def test_a_cut_turn_still_routes_to_the_blackloop_recovery(seam, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(S, "_recover_blackloop", lambda *a, **k: sentinel)
    out = _run_turn(seam, [
        _turn(None, [AIMessage(content=PAYLOAD_JSON)], blackloop=True),
    ])
    assert out is sentinel


def test_the_outcome_is_recorded_for_the_next_turn(seam):
    _run_turn(seam, [
        _turn(None, [HumanMessage(content="SYSTEMS now available"), _text_answer()]),
        _turn(None, [HumanMessage(content="SYSTEMS now available"), _text_answer()]),
    ])
    config: dict = {}
    S._attach_structured_channel_metadata(config, "t-1")
    assert config["metadata"]["structured_channel_recovery"] == {
        "outcome": "accepted_text_payload"
    }


# --- the pure helpers --------------------------------------------------------

def test_a_proper_tool_round_is_never_read_as_text():
    turn = _turn(None, [AIMessage(content="", tool_calls=[
        {"name": "L1DeltaBatch", "args": PAYLOAD, "id": "call-1"}])])
    assert S._text_channel_payload(turn, L1DeltaBatch) is None


def test_an_honest_empty_answer_is_not_a_payload():
    turn = _turn(None, [AIMessage(content="")])
    assert S._text_channel_payload(turn, L1DeltaBatch) is None


def test_a_pure_json_answer_is_uniquely_parsable():
    payload = S._unique_schema_payload(PAYLOAD_JSON, L1DeltaBatch)
    assert payload is not None and payload.system_edges[0].rel == "EXPOSED_VIA"


def test_a_fenced_json_answer_is_uniquely_parsable():
    text = "Here is the batch:\n```json\n" + PAYLOAD_JSON + "\n```\n"
    assert S._unique_schema_payload(text, L1DeltaBatch) is not None


def test_two_valid_objects_are_ambiguous():
    text = PAYLOAD_JSON + "\n" + '{"systems": [], "system_edges": []}'
    assert S._unique_schema_payload(text, L1DeltaBatch) is None


def test_a_non_validating_object_is_not_a_payload():
    assert S._unique_schema_payload('{"systems": "not-a-list"}', L1DeltaBatch) is None


def test_the_tool_name_comes_from_the_response_format():
    assert S._structured_tool_name(ToolStrategy(L1DeltaBatch)) == "L1DeltaBatch"
