"""Unit tier: the triage phase state machine (lifecycle v2, slice 4).

The machine is PURE: signal detection and state advance over the observed gate
call verbatim. No LLM, no tool execution, no side effects. It mirrors
`hunter_state.py`'s `detect_phase_signal` / `advance_state` split: a malformed
gate call maps to no signal, so the phase stays put, and the phase machine
never gates on the tool's acceptance (the harness owns that check).
"""
from __future__ import annotations

from polymerhus.attack.hunting.pod.triage_state import (
    TriageFacts,
    advance_triage_state,
    detect_triage_signal,
    detect_triage_outcome,
)
from polymerhus.attack.hunting.pod.types import (
    NO_SYMPTOM_EVIDENCE,
    SPACE_EXHAUSTED,
    SYMPTOM_CONFIRMED,
)

_FACTS = TriageFacts(runner_failed=False, runner_exhausted=False,
                     runner_terminated=None, variant_allowed=True,
                     lap=1, thread_id="pod:s:s0")
_ASSESSMENT = {"symptom_confirmed": False, "runner_diverged": False,
               "clean": True, "note": "no confirmation"}
_DECISION_TERMINATE = {"action": "terminate", "verdict": "unsuccessful",
                       "terminal_reason": SPACE_EXHAUSTED,
                       "note": "space covered"}


# --- signal detection ---------------------------------------------------------

def test_detect_maps_a_valid_assessment():
    assert detect_triage_signal("submit_assessment", _ASSESSMENT) == "assessment"


def test_detect_maps_a_valid_decision():
    assert detect_triage_signal("submit_decision", _DECISION_TERMINATE) == "decision"


def test_detect_rejects_a_malformed_submission():
    bad_assessments = [
        {}, None, "x", 42,
        {"symptom_confirmed": "yes", "runner_diverged": False,
         "clean": True, "note": "n"},
        {"symptom_confirmed": True, "runner_diverged": False, "note": "n"},
    ]
    for bad in bad_assessments:
        assert detect_triage_signal("submit_assessment", bad) is None, bad


def test_detect_maps_every_other_tool_to_none_and_never_raises():
    for tool in ("notes", "browser", "load_skill", "", None):
        for args in ({"anything": []}, None, "garbage"):
            assert detect_triage_signal(tool, args) is None


def test_a_malformed_decision_maps_to_no_signal_and_never_raises():
    for bad in ({"action": "terminate"}, {"action": "variant"},
                {"action": "variant", "declined_attribute": "nope",
                 "variant_spec": {}, "note": "n"},
                None, "x"):
        assert detect_triage_signal("submit_decision", bad) is None


# --- the assessment outcome ---------------------------------------------------

def test_a_confirmed_assessment_selects_the_confirmed_terminal():
    args = {**_ASSESSMENT, "symptom_confirmed": True}
    outcome = detect_triage_outcome(_FACTS, _ASSESSMENT, "assessment", args)
    assert outcome["kind"] == "decision"
    decision = outcome["decision"]
    assert decision["action"] == "terminate"
    assert decision["verdict"] == "successful"
    assert decision["terminal_reason"] == SYMPTOM_CONFIRMED
    assert decision["clean"] is True


def test_a_runner_failure_fact_outranks_a_confirmed_symptom():
    args = {**_ASSESSMENT, "symptom_confirmed": True}
    facts = TriageFacts(**{**_FACTS, "runner_failed": True})
    outcome = detect_triage_outcome(facts, _ASSESSMENT, "assessment", args)
    assert outcome["kind"] == "decision"
    assert outcome["decision"]["action"] == "variant"
    assert outcome["decision"]["declined_attribute"] == "runner-failure"


def test_a_diverged_assessment_mints_the_divergence_variant():
    args = {**_ASSESSMENT, "runner_diverged": True}
    outcome = detect_triage_outcome(_FACTS, _ASSESSMENT, "assessment", args)
    assert outcome["kind"] == "decision"
    assert outcome["decision"]["action"] == "variant"
    assert outcome["decision"]["declined_attribute"] == "runner-divergence"


def test_a_negative_assessment_advances_to_decide():
    outcome = detect_triage_outcome(_FACTS, _ASSESSMENT, "assessment", _ASSESSMENT)
    assert outcome["kind"] == "advance"


# --- the decision outcome -----------------------------------------------------

def test_a_terminate_decision_is_the_final_decision():
    outcome = detect_triage_outcome(_FACTS, _ASSESSMENT, "decision",
                                    _DECISION_TERMINATE)
    assert outcome["kind"] == "decision"
    decision = outcome["decision"]
    assert decision["action"] == "terminate"
    assert decision["terminal_reason"] == SPACE_EXHAUSTED
    assert decision["clean"] is True   # the assessment's clean rides through


def test_a_variant_decision_when_allowed_mints_the_variant():
    args = {"action": "variant", "declined_attribute": "payload-vector",
            "variant_spec": {"rationale": "untested vector"},
            "feedback": "try the vector", "note": "vector untried"}
    outcome = detect_triage_outcome(_FACTS, _ASSESSMENT, "decision", args)
    assert outcome["kind"] == "decision"
    assert outcome["decision"]["action"] == "variant"
    assert outcome["decision"]["declined_attribute"] == "payload-vector"


def test_a_variant_decision_when_not_allowed_degrades_to_no_symptom_evidence():
    args = {"action": "variant", "declined_attribute": "payload-vector",
            "variant_spec": {"rationale": "untested vector"},
            "feedback": "try the vector", "note": "vector untried"}
    facts = TriageFacts(**{**_FACTS, "variant_allowed": False})
    outcome = detect_triage_outcome(facts, _ASSESSMENT, "decision", args)
    assert outcome["kind"] == "decision"
    decision = outcome["decision"]
    assert decision["action"] == "terminate"
    assert decision["verdict"] == "unsuccessful"
    assert decision["terminal_reason"] == NO_SYMPTOM_EVIDENCE
    assert decision["clean"] is False


# --- the phase advance --------------------------------------------------------

def test_an_advance_outcome_moves_assess_to_decide():
    assert advance_triage_state("assess", {"kind": "advance"}) == "decide"


def test_a_decision_outcome_moves_every_phase_to_done():
    assert advance_triage_state("assess", {"kind": "decision"}) == "done"
    assert advance_triage_state("decide", {"kind": "decision"}) == "done"
