"""Unit tier: the triage phase graph (lifecycle v2, slice 7).

The compiled `StateGraph` mirror of `hunter_graph.py`: one passive supervisor,
one deterministic detect, one advance. The graph selects a DECISION, never a
pod terminal - the pod graph's terminal node renders the `PodExport` from it
and the finalizer applies the monotonicity rule.
"""
from __future__ import annotations

from langgraph.constants import END

from polymerhus.attack.hunting.pod.triage_graph import (
    build_triage_graph,
    route_supervise,
)
from polymerhus.attack.hunting.pod.triage_state import TriageFacts
from polymerhus.attack.hunting.pod.types import SPACE_EXHAUSTED, SYMPTOM_CONFIRMED

_FACTS = TriageFacts(runner_failed=False, runner_exhausted=False,
                     runner_terminated=None, variant_allowed=True,
                     lap=1, thread_id="pod:s:s0")
_ASSESSMENT = {"symptom_confirmed": False, "runner_diverged": False,
               "clean": True, "note": "no confirmation"}


def _state(**over):
    base = {"phase": "assess", "observed_signal": None, "observed_args": None,
            "facts": dict(_FACTS), "assessment": None, "decide_packet": "DECIDE MATERIAL",
            "injected_constant": None, "trail": [], "decision": None}
    base.update(over)
    return base


# --- the supervisor's route ----------------------------------------------------

def test_route_supervise_ends_on_done():
    assert route_supervise(_state(phase="done")) == END


def test_route_supervise_detects_a_pending_signal():
    assert route_supervise(_state(observed_signal="assessment")) == "detect"


def test_route_supervise_stays_put_without_a_signal():
    assert route_supervise(_state()) is None


# --- the compiled drive --------------------------------------------------------

def test_a_negative_assessment_advances_to_decide_with_the_packet():
    graph = build_triage_graph().compile()
    out = graph.invoke(_state(observed_signal="assessment",
                              observed_args=dict(_ASSESSMENT)))
    assert out["phase"] == "decide"
    assert out["injected_constant"] == "DECIDE MATERIAL"
    assert out["assessment"] == _ASSESSMENT
    assert out["observed_signal"] is None and out["observed_args"] is None
    assert len(out["trail"]) == 1


def test_a_confirmed_assessment_lands_done_with_the_domain_decision():
    graph = build_triage_graph().compile()
    args = {**_ASSESSMENT, "symptom_confirmed": True}
    out = graph.invoke(_state(observed_signal="assessment", observed_args=args))
    assert out["phase"] == "done"
    decision = out["decision"]
    assert decision["action"] == "terminate"
    assert decision["verdict"] == "successful"
    assert decision["terminal_reason"] == SYMPTOM_CONFIRMED
    assert decision["clean"] is True
    assert out["injected_constant"] is None


def test_a_terminate_decision_lands_done_with_the_assessment_clean():
    graph = build_triage_graph().compile()
    args = {"action": "terminate", "verdict": "unsuccessful",
            "terminal_reason": SPACE_EXHAUSTED, "note": "covered"}
    out = graph.invoke(_state(phase="decide", observed_signal="decision",
                              observed_args=args, assessment=dict(_ASSESSMENT)))
    assert out["phase"] == "done"
    decision = out["decision"]
    assert decision["terminal_reason"] == SPACE_EXHAUSTED
    assert decision["clean"] is True     # the assessment's clean rides through


def test_a_rejected_signal_never_reaches_the_graph():
    # The harness only invokes the graph on an accepted gate result, so the
    # state channels stay untouched when the gate rejects.
    graph = build_triage_graph().compile()
    out = graph.invoke(_state())
    assert out["phase"] == "assess"
    assert out["decision"] is None and out["injected_constant"] is None
