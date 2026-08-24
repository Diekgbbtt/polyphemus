"""E1-E4 e2e walkthrough predicates for the hunter memory system
(docs/design/hunting-164-assertion-catalogue.md).

The walkthroughs drive the REAL turn-by-turn ReAct host
(`build_sync_hunting_agent`) against the REAL per-project `HunterMemoryStore`
on the filesystem and the REAL five-tool surface; the compiled state graph
rides per status write. The only substitution is the LIVE EDGE - the LLM
session, declared `model service, mode=scripted`: a scripted model emits
`HunterStep` tool calls (the real-LLM whole-hunter walkthroughs E5-E8 land
when the REST-capability workstream lands). Every terminal quantity is read
back from the real YAML files the store wrote or from the recorded tool
responses.
"""
from __future__ import annotations

import json

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
    _fault,
    _hunter_step,
    _hunt_config,
    _spec,
    build_hunter_agent,
    build_memory_store,
)


def _produced(tmp_path):
    return tmp_path / PROJECT / "test-specs" / FAULT_KEY / "produced"


# --- E1: the full lifecycle over the real store --------------------------------


def test_E1_full_lifecycle_over_the_real_store(tmp_path):
    store = build_memory_store(tmp_path)
    steps = [
        _hunter_step("tool", reasoning="ground and hypothesise F1", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised", mechanism="m1")}),
        _hunter_step("tool", reasoning="verify F1", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="verified", mechanism="m1",
                           supports=["evidence-1"])}),
        _hunter_step("tool", reasoning="specify F1", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _spec("F1", "S1", status="specified")}),
        _hunter_step("tool", reasoning="hypothesise F2", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f2", "strategy_keyword": "probe",
            "spec": _fault("F2", status="hypothesised", mechanism="m2")}),
        _hunter_step("tool", reasoning="drop F2", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f2", "strategy_keyword": "probe",
            "spec": _fault("F2", status="dropped", mechanism="m2")}),
        _hunter_step("answer", answer="candidate set exhausted"),
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


def test_E2_fault_and_note_share_the_identifier_over_the_real_pipeline(tmp_path):
    store = build_memory_store(tmp_path)
    steps = [
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised")}),
        _hunter_step("tool", tool="notes", args={
            "command": "write", "action": "append", "fault_key": FAULT_KEY,
            "note_name": "decision", "kind": "freeform",
            "body": "the trailing support hint", "evidence": "evidence-1",
            "provenance": {"step": 2}}),
        _hunter_step("answer", answer="concluded"),
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


def test_E3_all_memory_capabilities_through_the_tool_surface(tmp_path):
    store = build_memory_store(tmp_path)
    seen: list = []
    steps = [
        # hunts_store write create -> update -> update (the lifecycle)
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised")}),
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="verified", supports=["evidence-1"])}),
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _spec("F1", "S1", status="specified")}),
        # hunts_store read by fault_key with statuses + attributes
        _hunter_step("tool", tool="hunts_store", args={
            "command": "read", "fault_key": FAULT_KEY,
            "statuses": ["specified"], "attributes": ["status", "spec_id"]}),
        # notes write append -> append -> read -> update -> delete
        _hunter_step("tool", tool="notes", args={
            "command": "write", "action": "append", "fault_key": FAULT_KEY,
            "note_name": "n1", "kind": "freeform", "body": "first note"}),
        _hunter_step("tool", tool="notes", args={
            "command": "write", "action": "append", "fault_key": FAULT_KEY,
            "note_name": "n2", "kind": "freeform", "body": "second note"}),
        _hunter_step("tool", tool="notes", args={
            "command": "read", "parent_key": FAULT_KEY}),
        _hunter_step("tool", tool="notes", args={
            "command": "write", "action": "update", "fault_key": FAULT_KEY,
            "note_name": "n1", "kind": "hypothesis_refusal", "body": "amended"}),
        _hunter_step("tool", tool="notes", args={
            "command": "write", "action": "delete", "fault_key": FAULT_KEY,
            "note_name": "n1"}),
        _hunter_step("answer", answer="done"),
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


def test_E4_phase_hints_ride_tool_responses_and_graph_tracks_the_loop(tmp_path):
    store = build_memory_store(tmp_path)
    seen: list = []
    steps = [
        # a grounding-phase kb_query rides the D3 retrieval-gap check
        _hunter_step("tool", tool="kb_query", args={
            "scenario_id": "s1", "attack_goal": "g", "concern": "c"}),
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised", mechanism="m1")}),
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="verified", mechanism="m1",
                           supports=["evidence-1"])}),
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _spec("F1", "S1", status="specified")}),
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "create",
            "fault_keyword": "f2", "strategy_keyword": "probe",
            "spec": _fault("F2", status="hypothesised", mechanism="m2")}),
        _hunter_step("tool", tool="hunts_store", args={
            "command": "write", "fault_key": FAULT_KEY, "mode": "update",
            "fault_keyword": "f2", "strategy_keyword": "probe",
            "spec": _fault("F2", status="dropped", mechanism="m2")}),
        _hunter_step("answer", answer="concluded"),
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