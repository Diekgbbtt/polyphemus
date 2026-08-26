"""H1-H5 harness-seam contract predicates for the hunter memory system
(docs/design/hunting-164-assertion-catalogue.md).

These are CONTRACT predicates on the harness seam, not e2e walkthroughs: they
drive the real turn-by-turn ReAct host (`build_sync_hunting_agent`) against the
real per-project `HunterMemoryStore` and the real five-tool surface, with the
LIVE EDGE - the LLM session - substituted by a scripted model emitting REAL
tool calls. Per the to-assertions rule a path that substitutes its live edge is
a simulation, so it lives in the INTEGRATION tier: it pins the harness's
deterministic detection+push+hint wiring (status verbatim, phase hints verbatim,
lifecycle-on-one-file, fault/note identifier equality) and the request-bound
tool schemas (H5). The live qualitative walkthrough of the same path - the real
model through the co-located gateway - is the e2e tier's
`test_hunter_memory_live_walkthrough.py` (E1). Every terminal quantity here is
read back from the real YAML files the store wrote or from the recorded tool
responses.
"""
from __future__ import annotations

import json

from langchain_core.language_models import BaseChatModel

from polymerhus.attack.hunting.hunter_state import (
    COMMIT_SPECIFICATION_HINT,
    D2_HINT,
    D3_HINT,
    NEXT_FAULT_HINT,
    NEXT_ITERATION_HINT,
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
    return tmp_path / PROJECT / "test-specs" / FAULT_KEY / "produced"


# --- E1: the full lifecycle over the real store --------------------------------


def test_H1_full_lifecycle_over_the_real_store(tmp_path):
    store = build_memory_store(tmp_path)
    steps = [
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised", mechanism="m1")}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="verified", mechanism="m1",
                           supports=["evidence-1"])}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _spec("F1", "S1", status="specified")}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f2", "strategy_keyword": "probe",
            "spec": _fault("F2", status="hypothesised", mechanism="m2")}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f2", "strategy_keyword": "probe",
            "spec": _fault("F2", status="dropped", mechanism="m2")}),
        _answer("candidate set exhausted"),
    ]
    agent = build_hunter_agent(store, steps=steps)
    result = agent(_hunt_config())

    assert result.hypothesis_verdict is None
    # EXACTLY TWO produced spec files, each carrying its lifecycle terminal
    files = sorted(_produced(tmp_path).glob("*.yaml"))
    assert [f.name for f in files] == ["f1_probe.yaml", "f2_probe.yaml"]
    f1 = store.read_spec(PROJECT, FAULT_KEY, fault_keyword="f1", strategy_keyword="probe")
    f2 = store.read_spec(PROJECT, FAULT_KEY, fault_keyword="f2", strategy_keyword="probe")
    assert f1["status"] == "specified" and f1["spec_id"] == "S1"
    assert f2["status"] == "dropped"
    # the terminal graph state rides the feedback: ratified S1, dropped F2,
    # and F1 is NOT left stale in hypothesised
    assert "phase: concluded" in result.feedback
    assert "- ratified: S1" in result.feedback
    assert "- dropped: F2" in result.feedback
    assert "- hypothesised: F1" not in result.feedback


# --- E2: fault and note share the identifier over the real pipeline ------------


def test_H2_fault_and_note_share_the_identifier_over_the_real_pipeline(tmp_path):
    store = build_memory_store(tmp_path)
    steps = [
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised")}),
        _tool_call("notes", {
            "command": "write", "action": "append", "fault_key": FAULT_KEY,
            "note_name": "decision", "kind": "freeform",
            "body": "the trailing support hint", "evidence": "evidence-1",
            "provenance": {"step": 2}}),
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
    assert notes[0]["provenance"] == {"step": 2}
    # ONE identifier walks both bodies: the spec under test-specs/<fault_key>/,
    # the note key embedding <fault_key>
    assert store.read_specs(PROJECT, FAULT_KEY)[0]["fault_id"] == "F1"


# --- E3: all memory integration capabilities through the tool surface ----------


def test_H3_all_memory_capabilities_through_the_tool_surface(tmp_path):
    store = build_memory_store(tmp_path)
    seen: list = []
    steps = [
        # hunts_store write create -> update -> update (the lifecycle)
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised")}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="verified", supports=["evidence-1"])}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _spec("F1", "S1", status="specified")}),
        # hunts_store read by fault_key with statuses + attributes
        _tool_call("hunts_store", {
            "command": "read", "fault_key": FAULT_KEY,
            "statuses": ["specified"], "attributes": ["status", "spec_id"]}),
        # notes write append -> append -> read -> update -> delete
        _tool_call("notes", {
            "command": "write", "action": "append", "fault_key": FAULT_KEY,
            "note_name": "n1", "kind": "freeform", "body": "first note"}),
        _tool_call("notes", {
            "command": "write", "action": "append", "fault_key": FAULT_KEY,
            "note_name": "n2", "kind": "freeform", "body": "second note"}),
        _tool_call("notes", {
            "command": "read", "parent_key": FAULT_KEY}),
        _tool_call("notes", {
            "command": "write", "action": "update", "fault_key": FAULT_KEY,
            "note_name": "n1", "kind": "hypothesis_refusal", "body": "amended"}),
        _tool_call("notes", {
            "command": "write", "action": "delete", "fault_key": FAULT_KEY,
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


# --- E4: the phase hints ride the tool responses and the graph tracks ----------


def test_H4_phase_hints_ride_tool_responses_and_graph_tracks_the_loop(tmp_path):
    store = build_memory_store(tmp_path)
    seen: list = []
    steps = [
        # a grounding-phase kb_query rides the D3 retrieval-gap check
        _tool_call("kb_query", {
            "scenario_id": "s1", "attack_goal": "g", "concern": "c"}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised", mechanism="m1")}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="verified", mechanism="m1",
                           supports=["evidence-1"])}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _spec("F1", "S1", status="specified")}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f2", "strategy_keyword": "probe",
            "spec": _fault("F2", status="hypothesised", mechanism="m2")}),
        _tool_call("hunts_store", {
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f2", "strategy_keyword": "probe",
            "spec": _fault("F2", status="dropped", mechanism="m2")}),
        _answer("concluded"),
    ]
    agent = build_hunter_agent(store, steps=steps, seen=seen)
    result = agent(_hunt_config())

    assert result.hypothesis_verdict is None

    def hint_content(i):
        # the tool response the model received on turn i (step N's response
        # arrives as step N+1's input, so seen[N+1][-1] carries step N's hint)
        return seen[i][-1] or ""

    # each phase hint rode its status-write response verbatim, inside the
    # phase-transition-hint wrapper
    assert "<phase-transition-hint>" in hint_content(1)
    assert D3_HINT in hint_content(1)
    assert D2_HINT in hint_content(2)
    assert COMMIT_SPECIFICATION_HINT in hint_content(3)
    assert NEXT_ITERATION_HINT in hint_content(4)
    assert D2_HINT in hint_content(5)
    assert NEXT_FAULT_HINT in hint_content(6)
    # hints are consumed per response - no stale hint leaks onto a later one
    assert D2_HINT not in hint_content(3)
    assert NEXT_ITERATION_HINT not in hint_content(5)
    # the graph tracked the loop, never left stale: both faults reached their
    # terminal lists - F1 ratified (not hypothesised/verified), F2 dropped
    # (not hypothesised)
    assert "- ratified: S1" in result.feedback
    assert "- dropped: F2" in result.feedback
    assert "- hypothesised: F1" not in result.feedback
    assert "- verified: F1" not in result.feedback
    assert "- hypothesised: F2" not in result.feedback
    # the persisted lifecycle files agree
    assert store.read_spec(PROJECT, FAULT_KEY, fault_keyword="f1",
                           strategy_keyword="probe")["status"] == "specified"
    assert store.read_spec(PROJECT, FAULT_KEY, fault_keyword="f2",
                           strategy_keyword="probe")["status"] == "dropped"

# --- H5: the five tool schemas ride the session turn (option B) ---------------


def test_H5_tool_schemas_ride_the_session_turn(tmp_path, monkeypatch):
    """The five tool schemas are bound REQUEST-ONLY to the session turn: each
    `convert_to_openai_tool` dict carries the tool's JSON schema in the
    generation request's `tools` body (the standard tool interface), so the
    model can emit valid args - and no ToolNode is created, so the harness stays
    the sole executor."""
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
    assert names == ["hunts_store", "notes", "graph_view", "kb_query", "exec"]
    for t in tools:
        assert t["type"] == "function"
        assert t["function"]["name"] and t["function"]["description"]
        # the args JSON schema rides the request body - the model sees it
        assert "parameters" in t["function"]
        assert "properties" in t["function"]["parameters"]
