"""H1-H6 harness-seam contract predicates for the hunter memory system
(docs/design/hunting-164-assertion-catalogue.md).

These are CONTRACT predicates on the harness seam, not e2e walkthroughs: they
drive the real turn-by-turn ReAct host (`build_sync_hunting_agent`) against the
real per-project `HunterMemoryStore` and the real tool surface, with the LIVE
EDGE - the LLM session - substituted by a scripted model emitting REAL tool
calls. Per the to-assertions rule a path that substitutes its live edge is a
simulation, so it lives in the INTEGRATION tier: it pins the harness's
deterministic detection+push+hint wiring (the pass-exit signals, the transition
hints and the grounding rider verbatim, the phase-summary notes, the
fault/note identifier equality) and the request-bound tool schemas (H5). The
live qualitative walkthrough of the same path - the real model through the
co-located gateway - is the e2e tier's `test_hunter_memory_live_walkthrough.py`
(E1). Every terminal quantity here is read back from the real YAML files the
store wrote or from the recorded tool responses.

T5 (#378) re-pointed H1 and H4 from the retired fault lifecycle onto the pass
chain, and added H6 (the tracker is never gated by a tool's acceptance).
"""
from __future__ import annotations

import json

from langchain_core.language_models import BaseChatModel

from polymerhus.attack.hunting.hunter_state import (
    GROUNDING_HINT,
    GROUNDING_KB_HINT,
    TRANSITION_HINTS,
)
from tests.hunting_fixtures import (
    FAULT_KEY,
    PROJECT,
    _answer,
    _fault,
    _hunt_config,
    _spec,
    _tool_call,
    build_hunter_agent,
    build_memory_store,
)


def _produced(tmp_path):
    return tmp_path / PROJECT / "hunting" / "hunter" / "test-specs" / FAULT_KEY / "produced"


def _write(fault_keyword, strategy_keyword, spec):
    """A `hunts_store` write tool call: ONE `spec` payload carrying the
    file-name identity (the single-payload contract, #164)."""
    return _tool_call("hunts_store", {
        "command": "write",
        "spec": {**spec, "fault_keyword": fault_keyword,
                 "strategy_keyword": strategy_keyword},
    })


def _phase_note(phase, *, action="append", body=None):
    """The interposed phase-summary note the model writes as a pass exit
    (S4 14.8): `notes`, kind `phase_summary`, name `phase:<state>`."""
    return _tool_call("notes", {
        "command": "write", "action": action,
        "note_name": f"phase:{phase}", "kind": "phase_summary",
        "body": body or f"the {phase} pass output"})


def _spec_set(*statuses, keywords=("f1", "probe")):
    """The batched `specs` list write (S4 14.4): the whole set in one write.
    The GENERATE draft is all-`hypothesised`; the terminal VERIFY-CLAIMS write
    promotes the survivors and declasses the unfeasible. The store's own
    `specs`-list handling is T6 (#379) - the tracker observes the signal off
    the model's call and is never gated by the tool's acceptance."""
    return _tool_call("hunts_store", {
        "command": "write",
        "specs": [
            {"status": status, "fault_keyword": keywords[0],
             "strategy_keyword": keywords[1]}
            for status in statuses
        ],
    })


# --- H1: the pass chain over the real turn seam --------------------------------


def test_H1_the_pass_chain_reaches_complete_on_the_terminal_write(tmp_path):
    """The tracked state walks the eight-pass chain to `complete` (S4 14.2):
    the interposed phase notes carry the prose passes, the `hunts_store` writes
    carry GENERATE and the terminal VERIFY-CLAIMS commit, and the harness lands
    the terminal state in the feedback."""
    store = build_memory_store(tmp_path)
    steps = [
        _phase_note("grounding"),
        _phase_note("slice"),
        _phase_note("collect"),
        _phase_note("discriminate"),
        _spec_set("hypothesised"),                  # GENERATE exit
        _phase_note("well_formedness"),             # WELL-FORMEDNESS exit
        _spec_set("ratified", "dropped"),           # VERIFY-CLAIMS exit
    ]
    agent = build_hunter_agent(store, steps=steps)
    result = agent(_hunt_config())

    assert result.hypothesis_verdict is None
    # the chain landed terminal: the harness ends the hunt at COMPLETE
    assert "state: complete" in result.feedback


# --- H2: fault and note share the identifier over the real pipeline ------------


def test_H2_fault_and_note_share_the_identifier_over_the_real_pipeline(tmp_path):
    store = build_memory_store(tmp_path)
    steps = [
        _write("f1", "probe", _fault("F1", status="hypothesised")),
        _tool_call("notes", {
            "command": "write", "action": "append",
            "note_name": "decision", "kind": "freeform",
            "body": "the trailing support hint", "evidence": "evidence-1",
            "provenance": {"source": "pod-export", "run_id": "r1",
                           "verdict_stub": True,
                           "probe_refs": ["exec:probe-1"]}}),
        _answer("concluded"),
    ]
    agent = build_hunter_agent(store, steps=steps)
    result = agent(_hunt_config())

    assert result.hypothesis_verdict is None
    # the produced spec file and the notes body both exist under the project
    assert (_produced(tmp_path) / "f1_probe.yaml").is_file()
    notes = store.read_notes(PROJECT, parent_key=FAULT_KEY)
    assert len(notes) == 1
    assert notes[0]["fault_key"] == FAULT_KEY
    assert notes[0]["key"] == f"{FAULT_KEY}:decision"
    assert notes[0]["body"] == "the trailing support hint"
    assert notes[0]["evidence"] == "evidence-1"
    # #209: provenance is the TYPED NoteProvenance (extra="forbid") - the ratified
    # shape round-trips verbatim, never a free-form dict.
    assert notes[0]["provenance"] == {"source": "pod-export", "run_id": "r1",
                                      "verdict_stub": True,
                                      "probe_refs": ["exec:probe-1"]}
    # ONE identifier walks both bodies: the spec under test-specs/<fault_key>/,
    # the note key embedding <fault_key>
    assert store.read_specs(PROJECT, FAULT_KEY)[0]["fault_id"] == "F1"


# --- E3: all memory integration capabilities through the tool surface ----------


def test_H3_all_memory_capabilities_through_the_tool_surface(tmp_path):
    store = build_memory_store(tmp_path)
    seen: list = []
    steps = [
        # hunts_store write create -> update -> update (the lifecycle)
        _write("f1", "probe", _fault("F1", status="hypothesised")),
        _write("f1", "probe", _fault("F1", status="verified", supports=["evidence-1"])),
        _write("f1", "probe", _spec("F1", "S1", status="specified")),
        # hunts_store read by fault_key with statuses + attributes
        _tool_call("hunts_store", {
            "command": "read",
            "statuses": ["specified"], "attributes": ["status", "spec_id"]}),
        # notes write append -> append -> read -> update -> delete
        _tool_call("notes", {
            "command": "write", "action": "append",
            "note_name": "n1", "kind": "freeform", "body": "first note"}),
        _tool_call("notes", {
            "command": "write", "action": "append",
            "note_name": "n2", "kind": "freeform", "body": "second note"}),
        _tool_call("notes", {
            "command": "read"}),
        _tool_call("notes", {
            "command": "write", "action": "update",
            "note_name": "n1", "kind": "hypothesis_refusal", "body": "amended"}),
        _tool_call("notes", {
            "command": "write", "action": "delete",
            "note_name": "n1"}),
        _answer("done"),
    ]
    agent = build_hunter_agent(store, steps=steps, seen=seen)
    result = agent(_hunt_config())

    assert result.hypothesis_verdict is None
    # the produced side holds exactly one surviving spec file (the lifecycle
    # rode one file) carrying the specified terminal
    assert [f.name for f in sorted(_produced(tmp_path).glob("*.yaml"))] == ["f1_probe.yaml"]
    assert store.read_spec(PROJECT, FAULT_KEY, fault_keyword="f1",
                           strategy_keyword="probe")["status"] == "specified"
    # notes.yaml holds exactly the surviving note in append order (n1 deleted)
    notes = store.read_notes(PROJECT)
    assert [n["key"] for n in notes] == [f"{FAULT_KEY}:n2"]
    assert notes[0]["body"] == "second note"
    # the tool responses the model saw carried the memory JSON contracts (the
    # response to step N arrives as step N+1's input, so read seen[N+1])
    read_resp = json.loads(seen[4][-1].split("\n\n<phase-transition-hint>")[0])
    assert read_resp["specs"] == [{"status": "specified", "spec_id": "S1"}]
    notes_read = json.loads(seen[7][-1].split("\n\n<phase-transition-hint>")[0])
    assert [n["key"] for n in notes_read["notes"]] == [f"{FAULT_KEY}:n2", f"{FAULT_KEY}:n1"]
    delete_resp = json.loads(seen[9][-1].split("\n\n<phase-transition-hint>")[0])
    assert delete_resp == {"ok": True, "key": f"{FAULT_KEY}:n1"}


# --- H4: the pass hints ride the tool responses -------------------------------


def test_H4_exit_hints_and_the_grounding_rider_ride_the_tool_responses(tmp_path):
    """The harness injects the exited pass's constant in the signal's tool
    response (S4 14.7) and the grounding `kb_query` rider on a grounding KB
    call (S4 14.9); a hint is consumed by its own response - never leaked onto
    a later one. A [D2] re-iteration rewrites an earlier pass's note: that is
    trail material, and it rides no hint."""
    store = build_memory_store(tmp_path)
    seen: list = []
    steps = [
        # grounding: a KB call rides the retrieval-gap rider, never a transition
        _tool_call("kb_query", {
            "scenario_id": "s1", "attack_goal": "g", "concern": "c"}),
        _phase_note("grounding"),
        _phase_note("slice"),
        _phase_note("collect"),
        _phase_note("discriminate"),
        _spec_set("hypothesised"),
        _phase_note("collect", action="update",        # the [D2] re-entry
                    body="the collect pass output (re-iterated)"),
        _phase_note("well_formedness"),
    ]
    agent = build_hunter_agent(store, steps=steps, seen=seen)
    result = agent(_hunt_config())

    assert result.hypothesis_verdict is None

    def hint_content(i):
        # the tool response the model received on turn i (step N's response
        # arrives as step N+1's input, so seen[i][-1] carries step i-1's hint)
        return seen[i][-1] or ""

    assert "<phase-transition-hint>" in hint_content(1)
    # the roster: grounding's rider, then each exited pass's own constant
    assert GROUNDING_KB_HINT in hint_content(1)
    assert TRANSITION_HINTS["grounding"] in hint_content(2)
    assert TRANSITION_HINTS["slice"] in hint_content(3)
    assert TRANSITION_HINTS["collect"] in hint_content(4)
    assert TRANSITION_HINTS["discriminate"] in hint_content(5)
    assert TRANSITION_HINTS["generate"] in hint_content(6)
    # the [D2] re-entry rewrite is trail material: it never moves the state
    # back and rides no hint
    assert TRANSITION_HINTS["collect"] not in hint_content(7)
    assert TRANSITION_HINTS["well_formedness"] in hint_content(8)
    # hints are consumed per response - no stale hint leaks onto a later one
    assert GROUNDING_KB_HINT not in hint_content(2)
    assert TRANSITION_HINTS["slice"] not in hint_content(4)
    # the interposed notes persisted as the hunter-only kind, and the
    # re-iteration REWROTE the same note (latest wins, one record)
    notes = store.read_notes(PROJECT)
    assert {n["note_name"] for n in notes} >= {
        "phase:grounding", "phase:slice", "phase:collect", "phase:discriminate",
        "phase:well_formedness"}
    assert {n["kind"] for n in notes} == {"phase_summary"}
    collect_notes = [n for n in notes if n["note_name"] == "phase:collect"]
    assert [n["body"] for n in collect_notes] == [
        "the collect pass output (re-iterated)"]

# --- H5: the nine tool schemas ride the session turn (option B) ---------------


def test_H5_tool_schemas_ride_the_session_turn(tmp_path, monkeypatch):
    """The nine tool schemas are bound REQUEST-ONLY to the session turn: each
    `convert_to_openai_tool` dict carries the tool's JSON schema in the
    generation request's `tools` body (the standard tool interface), so the
    model can emit valid args - and no ToolNode is created, so the harness stays
    the sole executor. After the five memory/exec tools come the two HTTP-history
    verbs `search_http_history` / `get_http_artifact` (#196), then `load_skill`
    (ADR A4: the hunter declares it request-only alongside its memory/exec
    tools), and finally `auth_store` (#223: the auth-capable binding arms the
    hunter's skill surface with the shared auth store, last in the surface)."""
    import polymerhus.app.llm.session as S
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    captured: dict = {}

    class _Conclude(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content="done", tool_calls=[]))])

        @property
        def _llm_type(self) -> str:
            return "fake"

    async def fake_turn(role_id, thread_id, new_messages, *, checkpointer,
                        tools=(), **kw):
        captured["tools"] = tuple(tools)
        return S.SessionTurn(content="done",
                             messages=[AIMessage(content="done", tool_calls=[])],
                             thread_id=thread_id)

    monkeypatch.setattr(S, "arun_session_turn", fake_turn)
    store = build_memory_store(tmp_path)
    agent = build_hunter_agent(store, steps=[_answer("done")])
    result = agent(_hunt_config())

    assert result.hypothesis_verdict is None
    tools = captured.get("tools", ())
    names = [t["function"]["name"] for t in tools]
    assert names == [
        "hunts_store", "notes", "graph_view", "kb_query", "exec",
        "search_http_history", "get_http_artifact", "load_skill", "auth_store",
    ]
    for t in tools:
        assert t["type"] == "function"
        assert t["function"]["name"] and t["function"]["description"]
        # the args JSON schema rides the request body - the model sees it
        assert "parameters" in t["function"]
        assert "properties" in t["function"]["parameters"]


# --- H6: the tracker is never gated by the tool's acceptance -------------------


class _ExplodingNoteStore:
    """A store whose note WRITE raises (O3): the seam degrades, and the
    tracker must still observe the model's own call."""

    def write_note(self, *args, **kwargs):
        raise RuntimeError("notes store exploded")

    def read_notes(self, *args, **kwargs):
        return []


def test_H6_the_tracker_advances_even_when_the_tool_call_fails():
    """S4 14.2: the machine NEVER gates a tool call. The signal is read off the
    model's own call, never off the tool's response, so a tool that raises
    still advances the tracker and still rides the exited pass's hint."""
    seen: list = []
    agent = build_hunter_agent(
        _ExplodingNoteStore(), steps=[_phase_note("grounding"), _answer("done")],
        seen=seen)
    result = agent(_hunt_config())

    assert "state: slice" in result.feedback
    assert GROUNDING_HINT in (seen[1][-1] or "")
