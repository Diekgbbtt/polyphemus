"""Scripted model replies for the lifecycle v2 two-phase triager (test support).

One triage decision is one harness loop on the per-pod `pod_triager` thread: an
ASSESS `submit_assessment` call, then (on a negative assessment) a DECIDE
`submit_decision` call, then a closing prose turn that answers the final gate
call in the thread. The pod builds a fresh model per turn, so `triage_factory`
walks a SHARED triager cursor across the harness's turns while the runner's
script resets per stretch (one ReAct loop rides one model instance).
"""
from __future__ import annotations

import uuid

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from polymerhus.attack.hunting.pod.llm import POD_RUNNER_ROLE, POD_TRIAGER_ROLE


class StampedFakeModel(BaseChatModel):
    """The scripted chat model the pod tiers share.

    `_generate` replays `replies` one per model step (the last repeats) and
    stamps a unique provider-like id on every reply. The deep copy matters:
    `add_messages` mutates a message object it stores, so re-emitting the SAME
    script object on a later turn (e.g. the module-level `CLOSING`) would
    replace the earlier copy in place instead of appending. `bind_tools` is a
    passthrough, so no real tool binding resolves."""

    replies: list = []
    idx: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        i = self.idx.get("i", 0)
        self.idx["i"] = i + 1
        msg = self.replies[min(i, len(self.replies) - 1)]
        msg = msg.model_copy(deep=True,
                             update={"id": f"fake-{i}-{uuid.uuid4().hex}"})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self):
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def fake_model_factory(by_role):
    """A `model_factory(role_id) -> model` walking `by_role[role_id]`; each
    turn builds a fresh instance, so the runner's scripts are role-scoped."""
    def make(role_id):
        replies = by_role.get(role_id) or [AIMessage(content="done")]
        return StampedFakeModel(replies=list(replies), idx={})

    return make


def triage_factory(runner_script, triage_turns):
    """The role-keyed factory for a full production pod run.

    The runner resets its script per stretch (the whole ReAct loop rides ONE
    model instance), while the triager walks a SHARED cursor across the triage
    harness's turns: the pod builds a fresh model per turn, and one decision is
    an ASSESS turn, a DECIDE turn, and the closing turn on the same thread."""
    runner = fake_model_factory({POD_RUNNER_ROLE: runner_script})
    triage = {"i": 0}

    def make(role_id):
        if role_id == POD_TRIAGER_ROLE:
            i = triage["i"]
            triage["i"] = i + 1
            return StampedFakeModel(replies=list(triage_turns), idx={"i": i})
        return runner(role_id)

    return make


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


CLOSING = AIMessage(content="the decision is submitted; the pod may terminate")
"""The closing turn's reply: the machine is done, so the model answers in plain
text and the thread never ends on a dangling gate call (#280)."""


def confirmed_turns(*, clean: bool = True,
                    note: str = "the observation confirms the symptom") -> list:
    """The shortest decision: confirmation at ASSESS, then the closing turn."""
    return [assess(symptom_confirmed=True, clean=clean, note=note), CLOSING]


def space_exhausted_turns(*, note: str = "the probe space is exercised") -> list:
    """A negative (CLEAN) assessment, the space-exhausted terminal, then the
    closing. The assessment must be clean: the decision gate refuses a clean
    absence over unclean observations."""
    return [assess(clean=True,
                   note="the observation does not confirm the symptom"),
            terminate(terminal_reason="space-exhausted", note=note),
            CLOSING]
