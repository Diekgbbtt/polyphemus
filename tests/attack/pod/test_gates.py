"""Unit tier: the triage gate tools (lifecycle v2, slice 6).

A gate tool is a pure validator-acknowledgement: it validates the observed
submission and returns a coded acceptance or rejection. It never mutates the
trial state, and it never advances the phase - the harness accepts the signal
only when the gate result says it accepted the call (`gate_accepted`), which
mirrors the hunter's authoritative exits. A malformed submission is therefore a
coded rejection, never a raise and never a phase move.
"""
from __future__ import annotations

import json

from polymerhus.attack.hunting.pod.gates import (
    build_triage_gate_tools,
    gate_accepted,
    triage_request_tools,
)
from polymerhus.attack.hunting.pod.triage_state import TriageFacts
from polymerhus.attack.hunting.pod.types import SPACE_EXHAUSTED

_FACTS = TriageFacts(runner_failed=False, runner_exhausted=False,
                     runner_terminated=None, variant_allowed=True,
                     lap=1, thread_id="pod:s:s0")
_CLEAN_ASSESSMENT = {"symptom_confirmed": False, "runner_diverged": False,
                     "clean": True, "note": "no confirmation"}
_UNCLEAN_ASSESSMENT = {**_CLEAN_ASSESSMENT, "clean": False}

_ASSESSMENT = {"symptom_confirmed": True, "runner_diverged": False,
               "clean": True, "note": "the marker is reflected"}


def _tools(facts=None, assessment=None):
    return build_triage_gate_tools(facts or _FACTS,
                                   _CLEAN_ASSESSMENT if assessment is None
                                   else assessment)


# --- the assessment gate -------------------------------------------------------

def test_the_assessment_gate_accepts_a_valid_submission():
    result = _tools()["submit_assessment"].invoke(_ASSESSMENT)
    assert gate_accepted(result)
    body = json.loads(result)
    assert body["signal"] == "assessment"


def test_the_assessment_gate_rejects_a_malformed_submission_with_a_coded_message():
    for bad in ({"symptom_confirmed": "yes", "runner_diverged": False,
                 "clean": True, "note": "n"},
                {"symptom_confirmed": True, "note": "n"},
                None, "x"):
        result = _tools()["submit_assessment"].invoke(bad)
        assert not gate_accepted(result), bad
        assert "error" in json.loads(result), bad
        assert json.loads(result)["tool"] == "submit_assessment"


# --- the decision gate ---------------------------------------------------------

def test_the_decision_gate_accepts_a_honest_terminal():
    result = _tools()["submit_decision"].invoke({
        "action": "terminate", "verdict": "unsuccessful",
        "terminal_reason": "no-symptom-evidence", "note": "impaired observations"})
    assert gate_accepted(result)
    assert json.loads(result)["signal"] == "decision"


def test_the_decision_gate_has_no_clean_field():
    request = {t["function"]["name"]: t["function"]["parameters"]
               for t in triage_request_tools()}
    assert "clean" not in request["submit_decision"]["properties"]
    assert "clean" in request["submit_assessment"]["properties"]


def test_the_decision_gate_never_reads_clean_from_the_submission():
    # A space-exhausted claim over an UNCLEAN assessment is rejected even when
    # the submission asserts clean=true: the assessment owns clean, never the
    # decision.
    result = _tools(assessment=_UNCLEAN_ASSESSMENT)["submit_decision"].invoke({
        "action": "terminate", "verdict": "unsuccessful",
        "terminal_reason": SPACE_EXHAUSTED, "clean": True, "note": "done"})
    assert not gate_accepted(result)
    body = json.loads(result)
    assert body["error"] == "rejected"
    # The rejection names the canonical corrections: a partial-coverage
    # assessment and a variant for the unobserved execution modes.
    assert "partial" in body["detail"].lower()
    assert "variant" in body["detail"].lower()


def test_the_decision_gate_accepts_space_exhausted_over_a_clean_assessment():
    result = _tools(assessment=_CLEAN_ASSESSMENT)["submit_decision"].invoke({
        "action": "terminate", "verdict": "unsuccessful",
        "terminal_reason": SPACE_EXHAUSTED, "note": "space covered"})
    assert gate_accepted(result)


def test_the_decision_gate_rejects_a_variant_when_the_runner_is_terminated():
    facts = TriageFacts(**{**_FACTS, "runner_terminated": "node-timeout",
                           "variant_allowed": False})
    result = _tools(facts)["submit_decision"].invoke({
        "action": "variant", "declined_attribute": "payload-vector",
        "variant_spec": {"rationale": "untested vector"}, "note": "try it"})
    assert not gate_accepted(result)
    body = json.loads(result)
    assert body["error"] == "rejected"
    assert "node-timeout" in body["detail"]


def test_the_decision_gate_accepts_a_variant_when_allowed():
    result = _tools()["submit_decision"].invoke({
        "action": "variant", "declined_attribute": "payload-vector",
        "variant_spec": {"rationale": "untested vector"}, "note": "try it"})
    assert gate_accepted(result)


def test_the_decision_gate_rejects_an_unknown_basis_or_reason():
    for bad in ({"action": "variant", "declined_attribute": "nope",
                 "variant_spec": {}, "note": "n"},
                {"action": "terminate", "verdict": "unsuccessful",
                 "terminal_reason": "node-timeout", "note": "harness reason"}):
        result = _tools()["submit_decision"].invoke(bad)
        assert not gate_accepted(result), bad
        assert "error" in json.loads(result), bad


# --- the request-side schema ---------------------------------------------------

def test_the_request_tools_are_the_two_gate_schemas_in_order():
    tools = triage_request_tools()
    assert [t["type"] for t in tools] == ["function", "function"]
    assert [t["function"]["name"] for t in tools] == \
        ["submit_assessment", "submit_decision"]


def test_the_request_tool_schemas_match_the_gate_models():
    from polymerhus.attack.hunting.pod.triage_state import (
        AssessmentSubmission,
        DecisionSubmission,
    )

    tools = {t["function"]["name"]: t["function"]
             for t in triage_request_tools()}
    assert tools["submit_assessment"]["parameters"] == \
        AssessmentSubmission.model_json_schema()
    assert tools["submit_decision"]["parameters"] == \
        DecisionSubmission.model_json_schema()


def test_gate_accepted_never_raises():
    assert gate_accepted(json.dumps({"accepted": True})) is True
    assert gate_accepted(json.dumps({"accepted": False})) is False
    assert gate_accepted("not json") is False
    assert gate_accepted(None) is False
    assert gate_accepted({"accepted": True}) is True
