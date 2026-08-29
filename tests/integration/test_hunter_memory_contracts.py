"""Integration tier: the hunter memory assertion catalogue C1-C22
(docs/design/hunting-164-assertion-catalogue.md).

The contract predicates exercise the memory system at its two seams - the
per-project `HunterMemoryStore` (the store seam, spec 6 / G1-G9) and the
`hunts_store` / `notes` tool seams over it (`hunter_tools.py`, spec 5) - never
the ReAct host's internals. The real store on a tmp root and the real tools
bound to it; no model is involved in this tier. Every observable is the exact
file, count, or JSON shape the contract promises.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from polymerhus.attack.hunting.hunt_store import (
    HuntStore,
    config_file_name,
    semantic_key,
)
from polymerhus.attack.hunting.hunter_memory import (
    DuplicateSpecError,
    HunterMemoryStore,
)
from polymerhus.attack.hunting.hunter_tools import HuntsStoreTool, NotesTool
from tests.hunting_fixtures import (
    FAULT_KEY,
    PROJECT,
    _fault,
    _spec,
    build_memory_store,
)


# --- the store seam (C1-C15) ---------------------------------------------------


def test_C1_produced_topology_and_lazy_project_dir(tmp_path):
    store = build_memory_store(tmp_path)
    path = store.write_spec(
        PROJECT, FAULT_KEY, fault_keyword="csrf", strategy_keyword="probe",
        spec=_fault("F1", status="hypothesised"),
    )
    expected = (
        tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced" / "csrf_probe.yaml"
    )
    assert path == expected
    assert expected.is_file()
    # the project dir is created only at the first write - no eager tree
    empty = build_memory_store(tmp_path / "empty")
    assert empty.read_specs(PROJECT, FAULT_KEY) == []
    assert not (tmp_path / "empty" / PROJECT).exists()


def test_C2_read_round_trips_by_identity(tmp_path):
    store = build_memory_store(tmp_path)
    spec = _fault("F1", status="hypothesised")
    store.write_spec(PROJECT, FAULT_KEY, fault_keyword="csrf",
                     strategy_keyword="probe", spec=spec)
    back = store.read_spec(PROJECT, FAULT_KEY, fault_keyword="csrf",
                           strategy_keyword="probe")
    assert back == spec
    # the read is a function of the identity - the consumed side is a miss
    assert store.read_spec(PROJECT, FAULT_KEY, fault_keyword="csrf",
                           strategy_keyword="probe", side="consumed") is None


def test_C3_keyword_sanitisation_poisons_separator_chars(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_spec(
        PROJECT, FAULT_KEY, fault_keyword="fault/x:csrf", strategy_keyword="probe_1",
        spec=_fault("F1", status="hypothesised"),
    )
    f = (
        tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced"
        / "fault-x-csrf_probe-1.yaml"
    )
    assert f.is_file()
    back = store.read_spec(PROJECT, FAULT_KEY, fault_keyword="fault/x:csrf",
                           strategy_keyword="probe_1")
    assert back["fault_id"] == "F1"
    # a keyword that sanitises to a dot component is pathological -> rejected
    with pytest.raises(ValueError):
        store.write_spec(PROJECT, FAULT_KEY, fault_keyword="..",
                         strategy_keyword="probe",
                         spec=_fault("F2", status="hypothesised"))


def test_C4_status_lifecycle_rides_one_produced_file(tmp_path):
    store = build_memory_store(tmp_path)
    k = dict(fault_keyword="csrf", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create",
                     spec=_fault("F1", status="hypothesised"), **k)
    store.write_spec(PROJECT, FAULT_KEY, mode="update",
                     spec=_fault("F1", status="verified", supports=["e1"]), **k)
    store.write_spec(PROJECT, FAULT_KEY, mode="update",
                     spec=_spec("F1", "S1", status="specified"), **k)
    produced = tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced"
    files = sorted(produced.glob("*.yaml"))
    assert len(files) == 1
    assert files[0].name == "csrf_probe.yaml"
    body = store.read_spec(PROJECT, FAULT_KEY, **k)
    assert body["status"] == "specified"
    assert body["spec_id"] == "S1"


def test_C5_duplicate_create_fails_and_preserves_original(tmp_path):
    store = build_memory_store(tmp_path)
    k = dict(fault_keyword="csrf", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create",
                     spec=_fault("F1", status="hypothesised"), **k)
    with pytest.raises(DuplicateSpecError):
        store.write_spec(PROJECT, FAULT_KEY, mode="create",
                         spec=_fault("F1", status="hypothesised"), **k)
    # the original is not clobbered
    assert store.read_spec(PROJECT, FAULT_KEY, **k)["fault_id"] == "F1"
    # a different strategy or side is a fresh file, never a collision
    store.write_spec(PROJECT, FAULT_KEY, mode="create",
                     fault_keyword="csrf", strategy_keyword="other",
                     spec=_fault("F1", status="hypothesised"))
    store.write_spec(PROJECT, FAULT_KEY, mode="create", side="consumed",
                     fault_keyword="csrf", strategy_keyword="probe",
                     spec=_fault("F1", status="hypothesised"))
    produced = tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced"
    assert len(list(produced.glob("*.yaml"))) == 2


def test_C6_reauthor_update_overwrites_in_place(tmp_path):
    store = build_memory_store(tmp_path)
    k = dict(fault_keyword="csrf", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create",
                     spec=_fault("F1", status="hypothesised"), **k)
    store.write_spec(PROJECT, FAULT_KEY, mode="update",
                     spec=_fault("F1", status="verified", supports=["e1"]), **k)
    produced = tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced"
    files = sorted(produced.glob("*.yaml"))
    assert len(files) == 1
    body = store.read_spec(PROJECT, FAULT_KEY, **k)
    assert body["status"] == "verified"
    assert body["supports"] == ["e1"]
    # no _seq/_ref bookkeeping on the spec records (G11)
    assert "_seq" not in body and "_ref" not in body


def test_C7_read_spec_missing_returns_none_and_projection(tmp_path):
    store = build_memory_store(tmp_path)
    assert store.read_spec(PROJECT, FAULT_KEY, fault_keyword="csrf",
                           strategy_keyword="probe") is None
    store.write_spec(PROJECT, FAULT_KEY, fault_keyword="csrf",
                     strategy_keyword="probe",
                     spec=_spec("F1", "S1", status="specified"))
    proj = store.read_spec(PROJECT, FAULT_KEY, fault_keyword="csrf",
                           strategy_keyword="probe",
                           attributes=["status", "spec_id"])
    assert set(proj) == {"status", "spec_id"}
    assert proj == {"status": "specified", "spec_id": "S1"}


def test_C8_read_specs_listing_sides_and_statuses(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_spec(PROJECT, FAULT_KEY, fault_keyword="f1", strategy_keyword="probe",
                     spec=_spec("F1", "S1", status="specified"))
    store.write_spec(PROJECT, FAULT_KEY, fault_keyword="f2", strategy_keyword="probe",
                     spec=_fault("F2", status="dropped"))
    store.write_spec(PROJECT, FAULT_KEY, fault_keyword="f3", strategy_keyword="probe",
                     side="consumed", spec=_fault("F3", status="specified"))
    all_specs = store.read_specs(PROJECT, FAULT_KEY)
    assert [s["fault_id"] for s in all_specs] == ["F1", "F2", "F3"]
    consumed = store.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))
    assert [s["fault_id"] for s in consumed] == ["F3"]
    specified = store.read_specs(PROJECT, FAULT_KEY, statuses=["specified"])
    assert sorted(s["fault_id"] for s in specified) == ["F1", "F3"]
    # a missing fault_key (a valid 3-part key with no files) is a valid empty
    # result, never a failure
    assert store.read_specs(PROJECT, semantic_key("Service:slug:b", "fault-y",
                                                  "csrf")) == []


def test_C9_sides_addressable_and_no_movement(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_spec(PROJECT, FAULT_KEY, fault_keyword="f1", strategy_keyword="probe",
                     side="consumed", spec=_fault("F1", status="specified"))
    consumed = tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "consumed"
    assert (consumed / "f1_probe.yaml").is_file()
    # nothing eagerly creates or moves the produced side
    assert not (tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced").exists()
    with pytest.raises(ValueError):
        store.write_spec(PROJECT, FAULT_KEY, fault_keyword="f2", strategy_keyword="probe",
                         side="sideways", spec=_fault("F2", status="hypothesised"))


def test_C10_validation_rejects_unsafe_components(tmp_path):
    store = build_memory_store(tmp_path)
    for bad in ("../escape", "a/b", "a\\b", "a\x00b", ".", ".."):
        with pytest.raises(ValueError):
            store.write_spec(PROJECT, bad, fault_keyword="f", strategy_keyword="p",
                             spec=_fault("F1", status="hypothesised"))
    with pytest.raises(ValueError):
        store.write_spec(PROJECT, FAULT_KEY, fault_keyword="f", strategy_keyword="p",
                         spec=_fault("F1", status="open"))
    with pytest.raises(ValueError):
        store.write_spec(PROJECT, FAULT_KEY, mode="upsert", fault_keyword="f",
                         strategy_keyword="p", spec=_fault("F1", status="hypothesised"))
    with pytest.raises(ValueError):
        store.write_note(PROJECT, action="append", fault_key=FAULT_KEY,
                         note_name="n", kind="bogus", body="x")


def test_C11_corrupt_file_fails_loud(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_spec(PROJECT, FAULT_KEY, fault_keyword="f1", strategy_keyword="probe",
                     spec=_fault("F1", status="hypothesised"))
    f = tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced" / "f1_probe.yaml"
    f.write_text("{{{{{{{{")
    with pytest.raises(OSError):
        store.read_spec(PROJECT, FAULT_KEY, fault_keyword="f1", strategy_keyword="probe")
    with pytest.raises(OSError):
        store.read_specs(PROJECT, FAULT_KEY)
    # a corrupt notes file fails loud the same way
    notes = tmp_path / PROJECT / "hunter" / "notes.yaml"
    notes.write_text("{{{{{{{{")
    with pytest.raises(OSError):
        store.read_notes(PROJECT)


def test_C12_notes_append_and_append_order(tmp_path):
    store = build_memory_store(tmp_path)
    k1 = store.write_note(PROJECT, action="append", fault_key=FAULT_KEY,
                          note_name="n1", kind="freeform", body="first")
    k2 = store.write_note(PROJECT, action="append", fault_key=FAULT_KEY,
                          note_name="n2", kind="freeform", body="second")
    assert k1 == f"{FAULT_KEY}:n1"
    assert k2 == f"{FAULT_KEY}:n2"
    notes = store.read_notes(PROJECT)
    assert [n["key"] for n in notes] == [k2, k1]  # read-latest
    assert notes[1]["fault_key"] == FAULT_KEY
    assert notes[1]["note_name"] == "n1"
    assert notes[1]["body"] == "first"


def test_C13_notes_update_delete_and_denoted_miss(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_note(PROJECT, action="append", fault_key=FAULT_KEY,
                     note_name="n1", kind="freeform", body="first")
    store.write_note(PROJECT, action="update", fault_key=FAULT_KEY,
                     note_name="n1", kind="hypothesis_refusal",
                     body="amended", evidence="e")
    notes = store.read_notes(PROJECT)
    assert len(notes) == 1
    assert notes[0]["body"] == "amended"
    assert notes[0]["kind"] == "hypothesis_refusal"
    assert notes[0]["evidence"] == "e"
    store.write_note(PROJECT, action="delete", fault_key=FAULT_KEY, note_name="n1",
                     kind="freeform", body="")
    assert store.read_notes(PROJECT) == []
    # update/delete on a missing key is a denoted miss, never a failure
    assert store.write_note(PROJECT, action="update", fault_key=FAULT_KEY,
                            note_name="missing", kind="freeform", body="x") is None
    assert store.write_note(PROJECT, action="delete", fault_key=FAULT_KEY,
                            note_name="missing", kind="freeform", body="") is None


def test_C14_notes_read_grep_match_and_read_latest(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_note(PROJECT, action="append", fault_key=FAULT_KEY,
                     note_name="lead", kind="freeform", body="WAF soft-blocked the probe")
    store.write_note(PROJECT, action="append", fault_key=FAULT_KEY,
                     note_name="refusal", kind="hypothesis_refusal",
                     body="no observable symptom")
    store.write_note(PROJECT, action="append",
                     fault_key=semantic_key("Service:slug:b", "fault-y", "csrf"),
                     note_name="lead", kind="freeform", body="other project note")
    parent = store.read_notes(PROJECT, parent_key=FAULT_KEY)
    assert sorted(n["note_name"] for n in parent) == ["lead", "refusal"]
    by_body = store.read_notes(PROJECT, body_keyword="WAF")
    assert len(by_body) == 1 and by_body[0]["note_name"] == "lead"
    by_key = store.read_notes(PROJECT, key_keyword="refus")
    assert len(by_key) == 1 and by_key[0]["note_name"] == "refusal"
    combined = store.read_notes(PROJECT, parent_key=FAULT_KEY, key_keyword="lead")
    assert len(combined) == 1
    # zero matches is a valid empty result
    assert store.read_notes(PROJECT, body_keyword="zzz-nothing") == []


def test_C15_fault_and_note_share_the_config_identifier(tmp_path):
    store = build_memory_store(tmp_path)
    store.write_spec(PROJECT, FAULT_KEY, fault_keyword="f1", strategy_keyword="probe",
                     spec=_fault("F1", status="hypothesised"))
    store.write_note(PROJECT, action="append", fault_key=FAULT_KEY,
                     note_name="decision", kind="freeform", body="hint")
    specs = store.read_specs(PROJECT, FAULT_KEY)
    notes = store.read_notes(PROJECT, parent_key=FAULT_KEY)
    assert len(specs) == 1 and len(notes) == 1
    assert specs[0]["fault_id"] == "F1"
    assert notes[0]["fault_key"] == FAULT_KEY
    assert notes[0]["key"] == f"{FAULT_KEY}:decision"
    # the produced spec file lives under test-specs/<fault_key>/ - the SAME key
    # the note keys embed: the pipeline is walked by one identifier
    produced = tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced"
    assert (produced / "f1_probe.yaml").is_file()


# --- the tool seams (C16-C22) ---------------------------------------------------


def _tool_store(tmp_path):
    store = HunterMemoryStore(root_dir=tmp_path)
    return (
        store,
        HuntsStoreTool(store=store, project_id=PROJECT),
        NotesTool(store=store, project_id=PROJECT),
    )


def test_C16_hunts_store_write_create(tmp_path):
    _, tool, _ = _tool_store(tmp_path)
    out = json.loads(tool.invoke({
        "command": "write", "fault_key": FAULT_KEY, "mode": "create",
        "fault_keyword": "f1", "strategy_keyword": "probe",
        "spec": _fault("F1", status="hypothesised"),
    }))
    assert out["ok"] is True
    assert out["status"] == "hypothesised"
    assert out["path"].endswith(f"{PROJECT}/hunter/test-specs/{FAULT_KEY}/produced/f1_probe.yaml")
    assert Path(out["path"]).is_file()


def test_C17_duplicate_create_denoted_signal(tmp_path):
    _, tool, _ = _tool_store(tmp_path)
    write = {
        "command": "write", "fault_key": FAULT_KEY, "mode": "create",
        "fault_keyword": "f1", "strategy_keyword": "probe",
        "spec": _fault("F1", status="hypothesised"),
    }
    assert json.loads(tool.invoke(write))["ok"] is True
    out = json.loads(tool.invoke(write))
    assert out["ok"] is False
    assert out["error"] == "duplicate_spec"
    assert out["fault_key"] == FAULT_KEY


def test_C18_hunts_store_invalid_args(tmp_path):
    _, tool, _ = _tool_store(tmp_path)
    out = json.loads(tool.invoke({
        "command": "write", "fault_key": FAULT_KEY, "mode": "create",
        "fault_keyword": "", "strategy_keyword": "",
        "spec": _fault("F1", status="hypothesised"),
    }))
    assert out["ok"] is False and out["error"] == "invalid_args"
    out = json.loads(tool.invoke({
        "command": "write", "fault_key": FAULT_KEY, "mode": "create",
        "fault_keyword": "f1", "strategy_keyword": "probe",
        "spec": {"fault_id": "F1", "status": "open"},
    }))
    assert out["ok"] is False and out["error"] == "invalid_args"
    out = json.loads(tool.invoke({"command": "read"}))
    assert out["specs"] == [] and out["error"] == "invalid_args"


def test_C19_tool_read_filters_produce_projection(tmp_path):
    _, tool, _ = _tool_store(tmp_path)
    tool.invoke({
        "command": "write", "fault_key": FAULT_KEY, "mode": "create",
        "fault_keyword": "f1", "strategy_keyword": "probe",
        "spec": _spec("F1", "S1", status="specified"),
    })
    out = json.loads(tool.invoke({
        "command": "read", "fault_key": FAULT_KEY,
        "statuses": ["specified"], "attributes": ["status", "spec_id"],
    }))
    assert len(out["specs"]) == 1
    assert set(out["specs"][0]) == {"status", "spec_id"}
    assert out["specs"][0]["spec_id"] == "S1"


def test_C20_notes_tool_denoted_missing(tmp_path):
    _, _, tool = _tool_store(tmp_path)
    out = json.loads(tool.invoke({
        "command": "write", "action": "update", "fault_key": FAULT_KEY,
        "note_name": "nope", "kind": "freeform", "body": "x",
    }))
    assert out["ok"] is False
    assert out["error"] == "note_missing"
    assert out["fault_key"] == FAULT_KEY
    assert out["note_name"] == "nope"


def test_C21_absent_store_degrades_fail_open(tmp_path):
    store_tool = HuntsStoreTool(store=None, project_id=PROJECT)
    notes_tool = NotesTool(store=None, project_id=PROJECT)
    out = json.loads(store_tool.invoke({
        "command": "write", "fault_key": FAULT_KEY, "mode": "create",
        "fault_keyword": "f1", "strategy_keyword": "probe",
        "spec": _fault("F1", status="hypothesised"),
    }))
    assert out["error"] == "store_unavailable" and out["degraded"] is True
    out = json.loads(notes_tool.invoke({
        "command": "write", "action": "append", "fault_key": FAULT_KEY,
        "note_name": "n", "kind": "freeform", "body": "x",
    }))
    assert out["error"] == "store_unavailable" and out["degraded"] is True


def test_C22_read_failure_degrades_to_empty_set(tmp_path):
    _, tool, _ = _tool_store(tmp_path)
    tool.invoke({
        "command": "write", "fault_key": FAULT_KEY, "mode": "create",
        "fault_keyword": "f1", "strategy_keyword": "probe",
        "spec": _fault("F1", status="hypothesised"),
    })
    f = tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY / "produced" / "f1_probe.yaml"
    f.write_text("{{{{{{{{")
    out = json.loads(tool.invoke({"command": "read", "fault_key": FAULT_KEY}))
    assert out["specs"] == []
    assert out["error"] == "read_failed"


# --- the fault_key validation gate (C23-C24, #199) -----------------------------

# The canonical dispatched config the gate validates against: the production
# `_`-joined fault_key form and its `::`-semantic twin (G4/ADR Q13).
_CANON_UNIT = "Service:account-registration"
_CANON_FAULT = "CWE-1220"
_CANON_CLASS = "Privilege Escalation"
_CANON_KEY = f"{_CANON_UNIT}_{_CANON_FAULT}_{_CANON_CLASS}"
_CANON_TWIN = semantic_key(_CANON_UNIT, _CANON_FAULT, _CANON_CLASS)


def _gate_store(tmp_path):
    """A hunter store + a hunt store whose produced config is the canonical
    (Service:account-registration, CWE-1220, Privilege Escalation) identity -
    the persisted config the tool's harness-owned gate validates against."""
    store = HunterMemoryStore(root_dir=tmp_path)
    hunt = HuntStore(root_dir=tmp_path)
    hunt.write_config(PROJECT, {
        "unit_id": _CANON_UNIT, "fault_class": _CANON_FAULT,
        "vulnerability_class": _CANON_CLASS, "status": "ratified",
    })
    return store, hunt


def test_C23_fault_key_gate_rejects_a_non_canonical_identity(tmp_path):
    """The harness-owned gate (write AND read, #199): a model-emitted fault_key
    that follows the naming convention but does not `:`-split-match a persisted
    hunt-config identity is rejected with the denoted `fault_key_mismatch`
    error - never a raise, never a fabricated folder."""
    store, hunt = _gate_store(tmp_path)
    tool = HuntsStoreTool(store=store, hunt_store=hunt, project_id=PROJECT)
    for bad in (
        # space STRIPPED out of the class name
        "Service:account-registration_CWE-1220_PrivilegeEscalation",
        # space replaced with `_` in the class name
        "Service:account-registration_CWE-1220_Privilege_Escalation",
        # the `Service:` kind prefix dropped
        "account-registration_CWE-1220_Privilege Escalation",
    ):
        out = json.loads(tool.invoke({
            "command": "write", "fault_key": bad, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised"),
        }))
        assert out["ok"] is False
        assert out["error"] == "fault_key_mismatch"
        assert out["fault_key"] == bad
        # reads reject the same way
        out = json.loads(tool.invoke({"command": "read", "fault_key": bad}))
        assert out["specs"] == []
        assert out["error"] == "fault_key_mismatch"
    # NO folder was fabricated for any rejected identity
    assert not (tmp_path / PROJECT / "hunter" / "test-specs").exists()


def test_C24_fault_key_gate_accepts_the_canonical_identity(tmp_path):
    """The gate accepts the canonical `_`-joined form and its `::`-semantic
    twin (both split `:`-wise to the persisted config identity, #199), writes
    the spec under the emitted key, and a read by the canonical returns it."""
    store, hunt = _gate_store(tmp_path)
    tool = HuntsStoreTool(store=store, hunt_store=hunt, project_id=PROJECT)
    for good, folder in ((_CANON_KEY, _CANON_KEY), (_CANON_TWIN, _CANON_TWIN)):
        out = json.loads(tool.invoke({
            "command": "write", "fault_key": good, "mode": "create",
            "fault_keyword": "f1", "strategy_keyword": "probe",
            "spec": _fault("F1", status="hypothesised"),
        }))
        assert out["ok"] is True, out
        assert out["path"].endswith(
            f"{PROJECT}/hunter/test-specs/{folder}/produced/f1_probe.yaml")
        assert Path(out["path"]).is_file()
    out = json.loads(tool.invoke({"command": "read", "fault_key": _CANON_KEY}))
    assert len(out["specs"]) == 1
    assert out["specs"][0]["fault_id"] == "F1"


def test_C24b_notes_tool_gate_rejects_a_non_canonical_identity(tmp_path):
    """The same harness-owned gate rides the `notes` write (the fault_key the
    note is scoped to must match a persisted config identity, #199)."""
    store, hunt = _gate_store(tmp_path)
    tool = NotesTool(store=store, hunt_store=hunt, project_id=PROJECT)
    out = json.loads(tool.invoke({
        "command": "write", "action": "append",
        "fault_key": "Service:account-registration_CWE-1220_PrivilegeEscalation",
        "note_name": "decision", "kind": "freeform", "body": "x",
    }))
    assert out["ok"] is False
    assert out["error"] == "fault_key_mismatch"
    assert store.read_notes(PROJECT) == []