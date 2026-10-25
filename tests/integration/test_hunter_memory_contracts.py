"""Integration tier: the hunter memory spec-set contract (S3 8.6-8.9, T6 #379).

The contract predicates exercise the threat-driven memory system at its two
seams - the per-project `HunterMemoryStore` (the spec-set store) and the
`hunts_store` / `notes` tool seams over it (`hunter_tools.py`) - never the
ReAct host's internals. The real store on a tmp root and the real tools bound
to it; no model is involved in this tier. Every observable is the exact file,
count, or JSON shape the contract promises.

T6 re-pointed the old C1-C26 catalogue from the retired fault/config key and
the four-value lifecycle onto the threat dispatch key, the batched `specs` set
write and the `{hypothesised, ratified, dropped}` vocabulary.
"""
from __future__ import annotations

import json

import pytest

from polymerhus.attack.hunting.hunter_memory import (
    DuplicateSpecError,
    HunterMemoryStore,
)
from polymerhus.attack.hunting.hunter_tools import HuntsStoreTool, NotesTool
from tests.hunting_fixtures import HUNT_KEY, PROJECT, build_memory_store


def _spec(*, class_name: str = "csrf", fault_keyword: str = "probe",
          strategy_keyword: str = "form", **extra) -> dict:
    """A reduced-D4 spec entry: the status + the ordered discriminators plus
    the typed body the store persists unchanged."""
    body = {
        "status": "hypothesised",
        "discriminators": [
            {"axis": "fault", "value": fault_keyword},
            {"axis": "technique", "value": strategy_keyword},
        ],
        "target_identity": {"url": "http://t/", "unit_id": "Service:a"},
        "verification_symptoms": ["a foreign state change is accepted"],
        "assumptions": ["the token is not bound to the session"],
        "rationale": "r",
        "provenance": {"threat_id": "threat-1",
                       "web_vulnerability_class": class_name},
    }
    body.update(extra)
    return body


def _produced(tmp_path, spec_id="csrf__probe__form"):
    return (tmp_path / PROJECT / "hunting" / "hunter" / "test-specs" / HUNT_KEY
            / "produced" / f"{spec_id}.yaml")


# --- the store seam -----------------------------------------------------------


def test_C1_produced_topology_and_lazy_project_dir(tmp_path):
    store = build_memory_store(tmp_path)
    written = store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    assert written[0] == ("csrf__probe__form", _produced(tmp_path))
    assert _produced(tmp_path).is_file()
    # the project dir is created only at the first write - no eager tree
    empty = build_memory_store(tmp_path / "empty")
    assert empty.read_specs(PROJECT, HUNT_KEY) == []
    assert not (tmp_path / "empty" / PROJECT).exists()


def test_C2_read_round_trips_by_derived_identity(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    assert store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form") == _spec()
    # the read is a function of the identity - the consumed side is a miss
    assert store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form",
                           side="consumed") is None


def test_C3_keyword_sanitisation_poisons_separator_chars(tmp_path):
    store = build_memory_store(tmp_path)
    (spec_id, path) = store.write_specs(PROJECT, HUNT_KEY, [
        _spec(class_name="fault/x:csrf", fault_keyword="probe",
              strategy_keyword="one")])[0]
    assert spec_id == "fault-x-csrf__probe__one"
    assert path.is_file()
    # a keyword that sanitises to a dot component is pathological -> rejected
    with pytest.raises(ValueError):
        store.write_specs(PROJECT, HUNT_KEY, [
            _spec(fault_keyword="..", strategy_keyword="probe")])


def test_C4_status_lifecycle_rides_one_produced_file(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    store.write_specs(PROJECT, HUNT_KEY, [_spec(status="ratified")])
    files = sorted(_produced(tmp_path).parent.glob("*.yaml"))
    assert len(files) == 1
    assert files[0].name == "csrf__probe__form.yaml"
    assert store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form")["status"] == "ratified"
    # the terminal declass rewrites the same file statused `dropped`
    store.write_specs(PROJECT, HUNT_KEY, [_spec(status="dropped")])
    assert store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form")["status"] == "dropped"
    assert len(sorted(_produced(tmp_path).parent.glob("*.yaml"))) == 1


def test_C5_duplicate_identity_inside_the_set_fails(tmp_path):
    store = build_memory_store(tmp_path)
    with pytest.raises(DuplicateSpecError):
        store.write_specs(PROJECT, HUNT_KEY, [_spec(), _spec()])
    # the rejected batch left nothing on disk
    assert not _produced(tmp_path).exists()
    # a different strategy is a fresh file, never a collision
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(strategy_keyword="other")])
    assert sorted(p.name for p in _produced(tmp_path).parent.glob("*.yaml")) == [
        "csrf__probe__other.yaml"]


def test_C6_reauthor_upserts_in_place(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(rationale="amended", verification_symptoms=["changed"])])
    body = store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form")
    assert body["rationale"] == "amended"
    assert body["verification_symptoms"] == ["changed"]


def test_C7_read_spec_missing_returns_none_and_projection(tmp_path):
    store = build_memory_store(tmp_path)
    assert store.read_spec(PROJECT, HUNT_KEY, "nope") is None
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    projected = store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form",
                                attributes=["status", "discriminators"])
    assert projected["status"] == "hypothesised"
    assert projected["discriminators"][0] == {
        "axis": "fault", "value": "probe"}


def test_C8_read_specs_listing_sides_and_statuses(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="f1"), _spec(fault_keyword="f2")])
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(status="ratified", fault_keyword="f1"),
        _spec(status="dropped", fault_keyword="f2")])
    assert len(store.read_specs(PROJECT, HUNT_KEY)) == 2
    assert store.read_specs(PROJECT, HUNT_KEY, statuses=["dropped"]) == [
        store.read_spec(PROJECT, HUNT_KEY, "csrf__f2__form")]
    assert store.read_specs(PROJECT, HUNT_KEY, sides=("consumed",)) == []


def test_C9_sides_addressable_and_no_movement(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()], side="consumed")
    assert not _produced(tmp_path).exists()
    assert store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form",
                           side="consumed")["status"] == "hypothesised"
    assert store.produced_spec_files(PROJECT, HUNT_KEY) == []


def test_C10_validation_rejects_unsafe_hunt_keys(tmp_path):
    store = build_memory_store(tmp_path)
    for bad in ("../escape", "a/b", "", ".", ".."):
        with pytest.raises(ValueError):
            store.write_specs(PROJECT, bad, [_spec()])


def test_C11_corrupt_file_fails_loud(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    _produced(tmp_path).write_text(": : broken [", encoding="utf-8")
    with pytest.raises(OSError):
        store.read_specs(PROJECT, HUNT_KEY)


def test_C12_notes_append_and_append_order(tmp_path):
    store = build_memory_store(tmp_path)
    assert store.write_note(PROJECT, action="append", hunt_key=HUNT_KEY,
                            note_name="n1", kind="freeform", body="a") \
        == f"{HUNT_KEY}:n1"
    store.write_note(PROJECT, action="append", hunt_key=HUNT_KEY,
                     note_name="n2", kind="freeform", body="b")
    assert [n["body"] for n in store.read_notes(PROJECT)] == ["b", "a"]


def test_C13_notes_update_delete_and_denoted_miss(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_note(PROJECT, action="append", hunt_key=HUNT_KEY,
                     note_name="n1", kind="freeform", body="a")
    assert store.write_note(PROJECT, action="update", hunt_key=HUNT_KEY,
                            note_name="n1", kind="freeform", body="amended") \
        == f"{HUNT_KEY}:n1"
    assert [n["body"] for n in store.read_notes(PROJECT)] == ["amended"]
    assert store.write_note(PROJECT, action="delete", hunt_key=HUNT_KEY,
                            note_name="n1", kind="freeform", body="") \
        == f"{HUNT_KEY}:n1"
    assert store.read_notes(PROJECT) == []
    assert store.write_note(PROJECT, action="update", hunt_key=HUNT_KEY,
                            note_name="ghost", kind="freeform", body="") is None


def test_C14_notes_read_grep_match_and_read_latest(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_note(PROJECT, action="append", hunt_key=HUNT_KEY,
                     note_name="alpha", kind="freeform", body="the token check")
    store.write_note(PROJECT, action="append", hunt_key=HUNT_KEY,
                     note_name="beta", kind="freeform", body="unrelated")
    assert [n["note_name"] for n in
            store.read_notes(PROJECT, key_keyword="alph")] == ["alpha"]
    assert [n["note_name"] for n in
            store.read_notes(PROJECT, body_keyword="token")] == ["alpha"]
    assert store.read_notes(PROJECT, parent_key="Service-other__threat-9") == []


def test_C15_hunt_and_note_share_the_identifier(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    store.write_note(PROJECT, action="append", hunt_key=HUNT_KEY,
                     note_name="decision", kind="freeform", body="b")
    (note,) = store.read_notes(PROJECT)
    assert note["key"] == f"{HUNT_KEY}:decision"
    assert note["hunt_key"] == HUNT_KEY
    assert store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form")["status"] == "hypothesised"


# --- the tool seam ------------------------------------------------------------


def _hunts(store, **kwargs):
    return HuntsStoreTool(store=store, project_id=PROJECT,
                          hunt_key=HUNT_KEY).invoke(kwargs)


def _notes(store, **kwargs):
    return NotesTool(store=store, project_id=PROJECT,
                     hunt_key=HUNT_KEY).invoke(kwargs)


def test_C16_hunts_store_one_spec_writes(tmp_path):
    store = build_memory_store(tmp_path)
    first = json.loads(_hunts(store, command="write", spec=_spec()))
    second = json.loads(_hunts(store, command="write",
                               spec=_spec(fault_keyword="f2")))
    assert first["ok"] is True and second["ok"] is True
    assert first["specs"][0]["spec_id"] == "csrf__probe__form"
    assert second["specs"][0]["spec_id"] == "csrf__f2__form"
    assert len(store.read_specs(PROJECT, HUNT_KEY)) == 2


def test_C17_repeated_one_spec_write_upserts_the_identity(tmp_path):
    """F-025: a repeated identity is an upsert, never a duplicate-set error."""
    store = build_memory_store(tmp_path)
    assert json.loads(_hunts(store, command="write", spec=_spec()))["ok"] is True
    out = json.loads(_hunts(store, command="write",
                            spec=_spec(status="ratified")))
    assert out["ok"] is True
    assert [spec["status"] for spec in store.read_specs(PROJECT, HUNT_KEY)] == [
        "ratified"]


def test_C18_hunts_store_invalid_args(tmp_path):
    store = build_memory_store(tmp_path)
    empty = json.loads(_hunts(store, command="write"))
    assert empty["error"] == "hunts_store_write_rejected"
    assert "spec" in empty["fields"]
    missing = json.loads(_hunts(store, command="write", spec={
        "status": "hypothesised"}))
    assert missing["error"] == "hunts_store_args_rejected"
    assert "discriminators" in " ".join(missing["fields"])
    bad_status = json.loads(_hunts(store, command="write",
                                   spec=_spec(status="specified")))
    assert bad_status["error"] == "hunts_store_write_rejected"
    authored_id = json.loads(_hunts(store, command="write",
                                    spec=_spec(spec_id="S1")))
    assert authored_id["error"] == "hunts_store_args_rejected"
    assert "spec_id" in " ".join(authored_id["fields"])
    assert store.read_specs(PROJECT, HUNT_KEY) == []


def test_C19_tool_read_filters_produce_projection(tmp_path):
    store = build_memory_store(tmp_path)
    _hunts(store, command="write",
           spec=_spec(fault_keyword="f1", strategy_keyword="probe"))
    _hunts(store, command="write",
           spec=_spec(fault_keyword="f2", strategy_keyword="probe"))
    _hunts(store, command="write",
           spec=_spec(status="ratified", fault_keyword="f1", strategy_keyword="probe"))
    _hunts(store, command="write",
           spec=_spec(status="dropped", fault_keyword="f2", strategy_keyword="probe"))
    out = json.loads(_hunts(store, command="read", statuses=["ratified"],
                            attributes=["status"]))
    assert out["specs"] == [{"status": "ratified"}]


def test_C20_notes_tool_denoted_missing(tmp_path):
    store = build_memory_store(tmp_path)
    out = json.loads(_notes(store, command="write", action="update",
                            note_name="ghost", kind="freeform", body="b"))
    assert out["ok"] is False and out["error"] == "note_missing"


def test_C21_absent_store_degrades_fail_open(tmp_path):
    assert json.loads(HuntsStoreTool(store=None, project_id=PROJECT,
                                     hunt_key=HUNT_KEY).invoke(
        {"command": "read"}))["degraded"] is True
    out = json.loads(HuntsStoreTool(store=None, project_id=PROJECT,
                                    hunt_key=HUNT_KEY).invoke(
        {"command": "write", "spec": _spec()}))
    assert out["degraded"] is True and out["error"] == "store_unavailable"


def test_C22_read_failure_degrades_to_empty_set(tmp_path, monkeypatch):
    store = build_memory_store(tmp_path)
    _hunts(store, command="write", spec=_spec())

    def boom(*args, **kwargs):
        raise OSError("read exploded (fixture)")

    monkeypatch.setattr(store, "read_specs", boom)
    out = json.loads(_hunts(store, command="read"))
    assert out == {"specs": [], "error": "read_failed",
                   "detail": "read exploded (fixture)"}


def test_C23_the_hunt_key_is_bound_not_a_request_field(tmp_path):
    store = build_memory_store(tmp_path)
    fields = HuntsStoreTool(store=None, project_id=PROJECT,
                            hunt_key=HUNT_KEY).args_schema.model_fields
    assert "hunt_key" not in fields and "fault_key" not in fields
    assert "spec" in fields
    # a tool with NO bound key degrades to a denoted invalid_args
    out = json.loads(HuntsStoreTool(store=store, project_id=PROJECT).invoke(
        {"command": "write", "spec": _spec()}))
    assert out["error"] == "invalid_args"
    assert store.read_specs(PROJECT, HUNT_KEY) == []


# --- the move-aware write and the single-owner move (the #205 rule) -----------


def test_C27_move_aware_write_and_single_owner_move(tmp_path, caplog):
    store = build_memory_store(tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    assert store.consume_spec(PROJECT, HUNT_KEY, "csrf__probe__form") is True
    assert store.produced_spec_files(PROJECT, HUNT_KEY) == []
    assert store.consume_spec(PROJECT, HUNT_KEY, "csrf__probe__form") is True   # at-least-once
    assert store.consume_spec(PROJECT, HUNT_KEY, "missing") is False
    # the late terminal write after the move is a no-op success, never a
    # produced/ re-creation (the #205 rule; the inbox keeps draining)
    written = store.write_specs(PROJECT, HUNT_KEY, [_spec(status="ratified")])
    assert written[0][1].parent.name == "consumed"
    assert store.produced_spec_files(PROJECT, HUNT_KEY) == []


def test_C28_the_typed_skill_concretisation_round_trips_through_the_tool(tmp_path):
    from polymerhus.attack.hunting.spec_contract import (
        SkillConcretisedProcedure,
    )

    store = build_memory_store(tmp_path)
    procedure = SkillConcretisedProcedure(recon_action="mine the item id",
                                         bypass_technique="swap the id")
    out = json.loads(_hunts(store, command="write", spec=_spec(
        skill_concretised_procedure=procedure.model_dump())))
    assert out["ok"] is True
    body = store.read_spec(PROJECT, HUNT_KEY, "csrf__probe__form")
    assert body["skill_concretised_procedure"]["bypass_technique"] == "swap the id"
