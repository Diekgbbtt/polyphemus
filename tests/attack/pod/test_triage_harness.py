"""Unit tier: the triage harness loop (lifecycle v2, slice 7).

One `arun_session_turn` per step, the same immutable system prompt and the same
request-only tool list on every step, the harness as the sole tool executor,
and the phase packet appended once to the accepted gate response. The turn
function is injected so the tier never touches a live LLM; the gate tools are
the real ones, so the acceptance rule is exercised end to end.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.gates import build_triage_gate_tools
from polymerhus.attack.hunting.pod.llm import PodHarnessContext
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.attack.hunting.pod.prompts import load_pod_triager_contract
from polymerhus.attack.hunting.pod.triage_state import TriageFacts
from polymerhus.app.llm.provider_failure import ProviderUnavailableError
from polymerhus.recon.domain.types import ExecResult

SPEC_ID = spec_identifier("sqli", [{"axis": "technique", "value": "blind"},
                                   {"axis": "payload-vector", "value": "boolean"}])
MEM_KEY = "pod:triager:" + SPEC_ID

_FACTS = TriageFacts(runner_failed=False, runner_exhausted=False,
                     runner_terminated=None, variant_allowed=True,
                     lap=1, thread_id=MEM_KEY)

_ASSESS_CALL = {"name": "submit_assessment", "id": "c1",
                "args": {"symptom_confirmed": False, "runner_diverged": False,
                         "clean": True, "note": "no confirmation"}}
_DECIDE_CALL = {"name": "submit_decision", "id": "c2",
                "args": {"action": "terminate", "verdict": "unsuccessful",
                         "terminal_reason": "space-exhausted",
                         "note": "space covered"}}
_MALFORMED_CALL = {"name": "submit_assessment", "id": "c3",
                   "args": {"symptom_confirmed": "yes", "note": "sloppy"}}


class _TurnScript:
    """A scripted `arun_session_turn`: each call consumes the next scripted
    turn and records the request the loop made. A script exhausted by the
    CLOSING turn answers with an empty turn - the harness discards that
    reply."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls: list[dict] = []

    async def __call__(self, role_id, thread_id, new_messages, **kwargs):
        self.calls.append({
            "role_id": role_id, "thread_id": thread_id,
            "messages": list(new_messages), **kwargs})
        if not self.turns:
            return _turn([])
        return self.turns.pop(0)


def _turn(tool_calls=None, content=""):
    return SimpleNamespace(messages=[AIMessage(
        content=content, tool_calls=list(tool_calls or []))])


async def _invoke_real(tools_by_name, name, args):
    tool = tools_by_name.get(name)
    if tool is None:
        return json.dumps({"error": "unknown_tool", "tool": name})
    return tool.invoke(args)


def _ctx():
    address = SimpleNamespace(role_id="pod_triager", thread_id=MEM_KEY)
    return SimpleNamespace(address=address, checkpointer=None)


def _hc(store):
    return PodHarnessContext(
        exec_fn=lambda command, timeout_s: ExecResult(stdout="", stderr="",
                                                      returncode=0),
        memory_store=store, spec_id=SPEC_ID, log=ExperimentLog(),
        variant_ref="v0", model_factory=None)


def _run_harness(script, store, *, lap=1):
    from polymerhus.attack.hunting.pod.triage import run_triage_harness

    facts = TriageFacts(**{**_FACTS, "lap": lap})
    return asyncio.run(run_triage_harness(
        ExperimentLog(), {}, None, facts, store=store, spec_id=SPEC_ID,
        order=0, session_ctx=_ctx(), harness_ctx=_hc(store),
        turn_fn=script, invoke_fn=_invoke_real))


def _text(message) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    return str(content)


# --- the loop's shape ----------------------------------------------------------

def test_one_turn_per_step_and_a_terminal_decision(tmp_path):
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    result = _run_harness(script, PodMemoryStore(tmp_path))
    # Two decision turns plus the closing turn that answers the final gate
    # call in the thread (the #280 adjacency contract).
    assert len(script.calls) == 3
    assert result["decision"]["action"] == "terminate"
    assert result["decision"]["terminal_reason"] == "space-exhausted"
    assert result["assessment"]["symptom_confirmed"] is False
    assert result["steps"] == 2


def test_the_closing_turn_answers_the_final_gate_call(tmp_path):
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    result = _run_harness(script, PodMemoryStore(tmp_path))
    closing = script.calls[-1]
    assert any(t == "phase:close" for t in closing["extra_tags"])
    tool_results = [m for m in closing["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_results) == 1
    assert tool_results[0].tool_call_id == "c2"   # the submit_decision call id
    assert "<phase-packet>" not in _text(tool_results[0])


def test_the_same_prompt_and_the_same_tools_on_every_step(tmp_path):
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    _run_harness(script, PodMemoryStore(tmp_path))
    assert all(call["system_prompt"] == load_pod_triager_contract()
               for call in script.calls)
    tool_names = [t["function"]["name"] for t in script.calls[0]["tools"]]
    # The read-only triager surface plus the two gates, in a fixed order.
    assert tool_names[-2:] == ["submit_assessment", "submit_decision"]
    assert "notes" in tool_names and "graph_view" in tool_names
    assert "exec" not in tool_names            # never the Kali terminal
    assert script.calls[0]["tools"] == script.calls[1]["tools"]


def test_the_gate_response_carries_the_phase_packet_once(tmp_path):
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    result = _run_harness(script, PodMemoryStore(tmp_path))
    # The submit_assessment result the NEXT turn sees carries the DECIDE
    # packet appended to the gate acknowledgement, exactly once.
    second_input = script.calls[1]["messages"]
    tool_results = [m for m in second_input if isinstance(m, ToolMessage)]
    assert len(tool_results) == 1
    assert "<phase-packet>" in _text(tool_results[0])
    assert "phase-packet" not in _text(script.calls[0]["messages"][0])
    assert result["decision"] is not None


def test_a_malformed_gate_call_is_a_rejection_and_never_a_phase_move(tmp_path):
    script = _TurnScript([_turn([_MALFORMED_CALL]), _turn([_ASSESS_CALL]),
                          _turn([_DECIDE_CALL])])
    result = _run_harness(script, PodMemoryStore(tmp_path))
    assert len(script.calls) == 4
    assert result["rejections"], "the coded rejection is surfaced"
    rejection = json.loads(result["rejections"][0])
    assert rejection["error"] == "rejected"
    assert result["decision"]["terminal_reason"] == "space-exhausted"


def test_a_no_tool_call_turn_gets_a_bounded_correction(tmp_path):
    script = _TurnScript([_turn(tool_calls=[], content="I think it is fine"),
                          _turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    result = _run_harness(script, PodMemoryStore(tmp_path))
    assert len(script.calls) == 4
    assert "submit_" in _text(script.calls[1]["messages"][0])
    assert result["decision"]["terminal_reason"] == "space-exhausted"


def test_the_step_budget_degrades_to_an_honest_terminal(tmp_path):
    script = _TurnScript([_turn([])] * 12)   # never a gate call
    result = _run_harness(script, PodMemoryStore(tmp_path))
    decision = result["decision"]
    assert decision["action"] == "terminate"
    assert decision["verdict"] == "unsuccessful"
    assert decision["terminal_reason"] == "no-symptom-evidence"
    assert decision["clean"] is False
    assert "budget" in decision["note"]
    assert len(script.calls) <= 8


def test_a_provider_failure_propagates_untouched(tmp_path):
    # #329: a provider failure is infrastructure, never a domain verdict. The
    # loop catches nothing, so the typed error propagates to the seam's
    # classification layer.
    async def boom(*a, **k):
        raise ProviderUnavailableError("throttled", status_code=429)

    with pytest.raises(ProviderUnavailableError):
        _run_harness(boom, PodMemoryStore(tmp_path))


def test_the_turn_tags_carry_run_thread_lap_and_phase(tmp_path):
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    _run_harness(script, PodMemoryStore(tmp_path))
    tags = script.calls[0]["extra_tags"]
    assert "lap:1" in tags and any(t.startswith("phase:") for t in tags)
    assert script.calls[0]["thread_id"] == MEM_KEY


def test_the_verbatim_rides_only_the_first_lap(tmp_path):
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    _run_harness(script, PodMemoryStore(tmp_path), lap=2)
    assert "# ASSESS phase" not in _text(script.calls[0]["messages"][0])
    assert "## Harness facts" in _text(script.calls[0]["messages"][0])
