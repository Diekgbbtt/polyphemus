"""Scripted replies for the lifecycle v2 two-phase triager (test support).

One triage decision is one harness loop on the per-pod `pod_triager` thread: an
ASSESS `submit_assessment` call, then (on a negative assessment) a DECIDE
`submit_decision` call, then a closing prose turn that answers the final gate
call in the thread. The pod builds a fresh model per turn, so the role-keyed
factories walk a SHARED per-role cursor; these helpers supply the gate calls and
the common turn sequences.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage


def gate_call(name: str, args: dict, call_id: str) -> AIMessage:
    """One gate submission as an AI tool call (the harness executes it)."""
    return AIMessage(content="", tool_calls=[
        {"name": name, "id": call_id, "args": args}])


def assess(*, symptom_confirmed: bool = False, runner_diverged: bool = False,
           clean: bool = True, note: str = "",
           call_id: str = "a1") -> AIMessage:
    """The ASSESS gate payload (`submit_assessment`)."""
    return gate_call("submit_assessment", {
        "symptom_confirmed": symptom_confirmed,
        "runner_diverged": runner_diverged,
        "clean": clean, "note": note}, call_id)


def terminate(*, verdict: str = "unsuccessful",
              terminal_reason: str = "no-symptom-evidence",
              note: str = "", call_id: str = "d1") -> AIMessage:
    """The DECIDE gate payload for a terminal (`submit_decision`)."""
    return gate_call("submit_decision", {
        "action": "terminate", "verdict": verdict,
        "terminal_reason": terminal_reason, "note": note}, call_id)


def decide_variant(*, declined_attribute: str, variant_spec: dict,
                   feedback: str = "", covered_gap_classes: list | None = None,
                   note: str = "", call_id: str = "d1") -> AIMessage:
    """The DECIDE gate payload for one falsifiable variant (`submit_decision`)."""
    args = {"action": "variant", "declined_attribute": declined_attribute,
            "variant_spec": variant_spec, "feedback": feedback, "note": note}
    if covered_gap_classes is not None:
        args["covered_gap_classes"] = covered_gap_classes
    return gate_call("submit_decision", args, call_id)


CLOSING = AIMessage(content="the decision is submitted; the pod may terminate")
"""The closing turn's reply: the machine is done, so the model answers in plain
text and the thread never ends on a dangling gate call (#280)."""


def confirmed_turns(*, clean: bool = True,
                    note: str = "the observation confirms the symptom") -> list:
    """The shortest decision: confirmation at ASSESS, then the closing turn."""
    return [assess(symptom_confirmed=True, clean=clean, note=note), CLOSING]


def space_exhausted_turns(*, clean: bool = True,
                          note: str = "the probe space is exercised") -> list:
    """A negative assessment, the space-exhausted terminal, then the closing."""
    return [assess(clean=clean,
                   note="the observation does not confirm the symptom"),
            terminate(terminal_reason="space-exhausted", note=note),
            CLOSING]
