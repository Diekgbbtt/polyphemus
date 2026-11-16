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
from polymerhus.attack.hunting.pod.llm import PodHarnessContext
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.attack.hunting.pod.prompts import load_pod_triager_contract
from polymerhus.attack.hunting.pod.triage_state import TriageFacts
from polymerhus.attack.hunting.pod.types import NO_SYMPTOM_EVIDENCE
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


def _ctx(checkpointer=None):
    address = SimpleNamespace(role_id="pod_triager", thread_id=MEM_KEY)
    return SimpleNamespace(address=address, checkpointer=checkpointer)


def _hc(store):
    return PodHarnessContext(
        exec_fn=lambda command, timeout_s: ExecResult(stdout="", stderr="",
                                                      returncode=0),
        memory_store=store, spec_id=SPEC_ID, log=ExperimentLog(),
        variant_ref="v0", model_factory=None)


def _run_harness(script, store, *, lap=1, checkpointer=None):
    from polymerhus.attack.hunting.pod.triage import run_triage_harness

    facts = TriageFacts(**{**_FACTS, "lap": lap})
    return asyncio.run(run_triage_harness(
        ExperimentLog(), {}, None, facts, store=store, spec_id=SPEC_ID,
        order=0, session_ctx=_ctx(checkpointer=checkpointer),
        harness_ctx=_hc(store),
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


def test_the_multi_gate_call_turn_composes_one_packet(tmp_path, monkeypatch):
    # Two gate calls in ONE AI message: the first accepted, the second is a
    # wrong-phase submission after the advance. One packet, one advance.
    import polymerhus.attack.hunting.pod.context as context_mod

    compose_calls = {"n": 0}
    real_compose = context_mod.compose_decide_packet

    async def scripted(role, thread, messages, **kw):
        if "phase:close" in (kw.get("extra_tags") or []):
            return _turn([], content="done closing")
        return _turn([
            {"name": "submit_assessment", "id": "g1",
             "args": {"symptom_confirmed": False, "runner_diverged": False,
                      "clean": True, "note": "first"}},
            {"name": "submit_assessment", "id": "g2",
             "args": {"symptom_confirmed": True, "runner_diverged": False,
                      "clean": True, "note": "second"}},
        ])

    def counting_compose(*a, **k):
        compose_calls["n"] += 1
        return real_compose(*a, **k)

    monkeypatch.setattr(context_mod, "compose_decide_packet", counting_compose)
    result = _run_harness(scripted, PodMemoryStore(tmp_path))
    assert compose_calls["n"] <= 1, (
        "the DECIDE material is composed only when the route continues")
    # The second call is a wrong-phase rejection, never a second packet.
    decisions = [r for r in result["rejections"]
                 if "submit_assessment" in r]
    assert decisions, "the late submission is a coded rejection"
    # The machine saw exactly one assessment.
    assert result["assessment"]["note"] == "first"


def test_the_phase_path_uses_the_ratified_vocabulary(tmp_path):
    # pod-triager-lifecycle-v2.md: the path is one of assess, assess>decide,
    # assess>variant, assess>decide>variant, assess>decide>terminal.
    confirmed = {"name": "submit_assessment", "id": "a1",
                 "args": {"symptom_confirmed": True, "runner_diverged": False,
                          "clean": True, "note": "n"}}
    diverged = {"name": "submit_assessment", "id": "a1",
                "args": {"symptom_confirmed": False, "runner_diverged": True,
                         "clean": True, "note": "n"}}
    variant_after_decide = [
        _turn([_ASSESS_CALL]),
        _turn([{"name": "submit_decision", "id": "d1",
                "args": {"action": "variant", "declined_attribute": "recon-action",
                         "variant_spec": {"rationale": "v"}, "note": "n"}}]),
    ]
    cases = [
        ([_turn([confirmed])], "assess"),
        ([_turn([diverged])], "assess>variant"),
        ([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])],
         "assess>decide>terminal"),
        (variant_after_decide, "assess>decide>variant"),
        # A budget exhaust after the advance: no gate call ever lands.
        ([_turn([_ASSESS_CALL])] + [_turn([], content="prose")] * 9, "assess>decide"),
    ]
    for turns, expected in cases:
        script = _TurnScript(list(turns) + [_turn([], content="close")])
        result = _run_harness(script, PodMemoryStore(tmp_path))
        assert result["phase_path"] == expected, (expected, result["phase_path"])


def test_the_thread_count_serves_every_saver_shape():
    # The prior-turn read must work for a sync saver, a coroutine-shaped
    # get_tuple, and a REAL async-only BaseCheckpointSaver (whose inherited
    # get_tuple raises NotImplementedError); a broken read degrades to 0.
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from polymerhus.attack.hunting.pod.triage import _thread_message_count

    class _T:
        checkpoint = {"channel_values": {"messages": []}}

    class _SyncSaver:
        def get_tuple(self, config):
            t = _T()
            t.checkpoint = {"channel_values": {"messages": [HumanMessage(content="x")] * 4}}
            return t

    class _CoroutineSaver:
        def get_tuple(self, config):
            async def _read():
                t = _T()
                t.checkpoint = {"channel_values": {"messages": [HumanMessage(content="x")] * 3}}
                return t

            return _read()

    class _AsyncOnlySaver(BaseCheckpointSaver):
        async def aget_tuple(self, config):
            t = _T()
            t.checkpoint = {"channel_values": {"messages": [HumanMessage(content="x")] * 2}}
            return t

    async def drive():
        return (await _thread_message_count(_SyncSaver(), "t"),
                await _thread_message_count(_CoroutineSaver(), "t"),
                await _thread_message_count(_AsyncOnlySaver(), "t"),
                await _thread_message_count(object(), "t"))

    sync_count, coroutine_count, async_count, broken = asyncio.run(drive())
    assert sync_count == 4
    assert coroutine_count == 3
    assert async_count == 2
    assert broken == 0


def test_a_closing_turn_failure_keeps_a_reached_decision(tmp_path):
    # A cosmetic closing failure must never cost a decision the machine
    # reached; the decision is returned with its phase path intact.
    async def scripted(role, thread, messages, **kw):
        if "phase:close" in (kw.get("extra_tags") or []):
            raise RuntimeError("closing transport blew up")
        return _turn([_ASSESS_CALL])

    from polymerhus.attack.hunting.pod.triage import run_triage_harness

    facts = TriageFacts(**{**_FACTS, "lap": 1})
    result = asyncio.run(run_triage_harness(
        ExperimentLog(), {}, None, facts, store=PodMemoryStore(tmp_path),
        spec_id=SPEC_ID, order=0, session_ctx=_ctx(), harness_ctx=_hc(
            PodMemoryStore(tmp_path)),
        turn_fn=scripted, invoke_fn=_invoke_real))
    assert result["decision"]["terminal_reason"] == NO_SYMPTOM_EVIDENCE
    assert result["phase_path"] == "assess>decide"


def test_a_closing_turn_provider_failure_without_a_decision_propagates(tmp_path):
    # #329: a provider failure with NO reached decision still propagates; the
    # surfer owns the retry. The gate is rejected on every step (a prose turn
    # would clear the pending results), so the step budget ends with
    # unanswered results and no decision - the closing turn then fails.
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    async def scripted(role, thread, messages, **kw):
        if "phase:close" in (kw.get("extra_tags") or []):
            raise ProviderUnavailableError("throttled", status_code=429)
        return _turn([_MALFORMED_CALL])

    from polymerhus.attack.hunting.pod.triage import run_triage_harness

    facts = TriageFacts(**{**_FACTS, "lap": 1})
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(run_triage_harness(
            ExperimentLog(), {}, None, facts, store=PodMemoryStore(tmp_path),
            spec_id=SPEC_ID, order=0, session_ctx=_ctx(), harness_ctx=_hc(
                PodMemoryStore(tmp_path)),
            turn_fn=scripted, invoke_fn=_invoke_real))


def test_the_closing_turn_rejects_truthfully_and_keeps_the_full_surface(tmp_path):
    # A post-decision submission on a closing turn is a PHASE-NEUTRAL coded
    # rejection ("the decision is closed"), and the closing executor still
    # carries the skill binding's tools (the same constant surface, closed).
    closing_seen = []

    async def scripted(role, thread, messages, **kw):
        if "phase:close" in (kw.get("extra_tags") or []):
            closing_seen.append(kw)
            return _turn([{"name": "submit_decision", "id": "c9",
                           "args": {"action": "terminate",
                                    "verdict": "successful",
                                    "terminal_reason": "symptom-confirmed",
                                    "note": "late"}}], content="")
        return _turn([_ASSESS_CALL])

    from polymerhus.attack.hunting.pod.triage import run_triage_harness

    facts = TriageFacts(**{**_FACTS, "lap": 1})
    result = asyncio.run(run_triage_harness(
        ExperimentLog(), {}, None, facts, store=PodMemoryStore(tmp_path),
        spec_id=SPEC_ID, order=0, session_ctx=_ctx(), harness_ctx=_hc(
            PodMemoryStore(tmp_path)),
        turn_fn=scripted, invoke_fn=_invoke_real))
    assert result["decision"]["terminal_reason"] != "symptom-confirmed"
    rejections = [r for r in result["rejections"] if "decision is closed" in r]
    assert rejections, "the closing rejection is phase-neutral, not misdirecting"
    assert closing_seen, "the closing turn ran"
    # The closing REQUEST carries the constant tool list (the same schemas the
    # decision turns saw); only the gates are closed in the executor.
    assert closing_seen[0]["tools"], "the closing request binds the surface"


def test_the_closing_turns_gates_are_closed(tmp_path):
    # A post-decision submission on a closing turn is a coded rejection, never
    # an accepted signal: the machine is done.
    closing_calls = []

    async def scripted(role, thread, messages, **kw):
        if "phase:close" in (kw.get("extra_tags") or []):
            closing_calls.append(kw)
            # The model misbehaves: it submits a decision AFTER the machine
            # ended. The gate must reject it.
            return _turn([{"name": "submit_decision", "id": "c9",
                           "args": {"action": "terminate",
                                    "verdict": "successful",
                                    "terminal_reason": "symptom-confirmed",
                                    "note": "late"}}], content="")
        return _turn([_ASSESS_CALL])

    from polymerhus.attack.hunting.pod.triage import run_triage_harness

    facts = TriageFacts(**{**_FACTS, "lap": 1})
    result = asyncio.run(run_triage_harness(
        ExperimentLog(), {}, None, facts, store=PodMemoryStore(tmp_path),
        spec_id=SPEC_ID, order=0, session_ctx=_ctx(), harness_ctx=_hc(
            PodMemoryStore(tmp_path)),
        turn_fn=scripted, invoke_fn=_invoke_real))
    assert result["decision"]["terminal_reason"] != "symptom-confirmed", (
        "a post-decision submission must never become the machine's decision")
    assert result["rejections"], "the late submission is a coded rejection"


def test_a_prose_budget_end_never_closes_with_stale_results(tmp_path):
    # The budget ends on a PROSE turn after an earlier tool call: the results
    # were already delivered (the prose turn's input), so the harness sends NO
    # closing turn - a duplicate ToolMessage for the same tool_call_id would
    # sit after the correction message, off-position for #280.
    script = _TurnScript([_turn([_ASSESS_CALL])] + [_turn([], content="prose")] * 9)
    result = _run_harness(script, PodMemoryStore(tmp_path))
    close_calls = [c for c in script.calls
                   if "phase:close" in (c.get("extra_tags") or [])]
    assert not close_calls, "no stale results to close: they were delivered"
    assert result["decision"]["clean"] is False


def test_the_closing_loop_never_leaves_a_dangling_call(tmp_path):
    # Two consecutive closing turns both emitting calls: every emitted call is
    # answered; the harness never ends on an unanswered call.
    closing_rounds = {"n": 0}

    async def scripted(role, thread, messages, **kw):
        if "phase:close" in (kw.get("extra_tags") or []):
            closing_rounds["n"] += 1
            if closing_rounds["n"] <= 2:
                return _turn([{"name": "notes", "id": f"n{closing_rounds['n']}",
                               "args": {"command": "read"}}], content="")
            return _turn([], content="done closing")
        return _turn([_ASSESS_CALL])

    from polymerhus.attack.hunting.pod.triage import run_triage_harness

    facts = TriageFacts(**{**_FACTS, "lap": 1})
    result = asyncio.run(run_triage_harness(
        ExperimentLog(), {}, None, facts, store=PodMemoryStore(tmp_path),
        spec_id=SPEC_ID, order=0, session_ctx=_ctx(), harness_ctx=_hc(
            PodMemoryStore(tmp_path)),
        turn_fn=scripted, invoke_fn=_invoke_real))
    # 2 closing tool rounds, each answered: the last scripted turn is prose.
    assert closing_rounds["n"] == 3
    assert result["decision"]["terminal_reason"] == NO_SYMPTOM_EVIDENCE
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    _run_harness(script, PodMemoryStore(tmp_path))
    tags = script.calls[0]["extra_tags"]
    assert "lap:1" in tags and any(t.startswith("phase:") for t in tags)
    assert script.calls[0]["thread_id"] == MEM_KEY


def test_the_verbatim_rides_only_the_first_decision_of_the_thread(tmp_path, monkeypatch):
    # A later LAP on an existing thread appends material only: the thread
    # already carries the verbatim. The thread's prior-turn count is what
    # decides; a polluted count is the observable stand-in for the persisted
    # thread (the count's own read is pinned in the re-dispatch tests).
    import polymerhus.attack.hunting.pod.triage as triage_mod

    async def async_count(*a, **k):
        return 5

    monkeypatch.setattr(triage_mod, "_thread_message_count", async_count)
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    _run_harness(script, PodMemoryStore(tmp_path), lap=2)
    assert "# ASSESS phase" not in _text(script.calls[0]["messages"][0])
    assert "## Harness facts" in _text(script.calls[0]["messages"][0])


def test_the_verbatim_rides_a_resumed_pods_fresh_thread(tmp_path):
    script = _TurnScript([_turn([_ASSESS_CALL]), _turn([_DECIDE_CALL])])
    _run_harness(script, PodMemoryStore(tmp_path), lap=3)
    assert "# ASSESS phase" in _text(script.calls[0]["messages"][0])
