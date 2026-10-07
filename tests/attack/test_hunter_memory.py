"""Unit tier: the per-project hunter-memory store's move-aware spec surface (#205).

Pure filesystem mechanics - no Neo4j, no LLM. Pins the #205 regression at the
store seam, mirroring the #192 ratify-upsert regression for the hunt store
(`tests/attack/test_hunt_store.py`): a produced-target `write_spec` whose
identity ALREADY lives in consumed/ (the mover's at-least-once marker landed)
is a no-op success returning the consumed Path - it never re-creates a
produced/ copy, so produced/ and consumed/ stay mutually exclusive per name
(G4) and the surfer's spec inbox keeps draining (the #205 race: the hunter's
late `specified` harness write can land after the mover consumed the spec;
without the guard the mover re-dispatches the identity every tick and the run
hangs in `running`, F5).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import pytest
import yaml

from polymerhus.attack.hunting import hunter_memory
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore

PROJECT = "proj-1"
FAULT_KEY = "Service:account-registration_CWE-266_Privilege Escalation"


def _spec(**extra) -> dict:
    """A `specified`-shape write payload carrying the lifecycle status."""
    body = {
        "fault_id": "F1", "spec_id": "S1", "status": "specified",
        "strategy": "probe", "fault_key": FAULT_KEY, "test": "t",
    }
    body.update(extra)
    return body


def _spec_file(tmp_path, side: Literal["produced", "consumed"]) -> Path:
    return (
        tmp_path / PROJECT / "hunting" / "hunter" / "test-specs" / FAULT_KEY
        / side / "registration_probe.yaml"
    )


# --- #205: write_spec is move-aware (G4 mutual exclusivity) -------------------

def test_produced_write_after_move_is_a_no_op_and_never_recreates(tmp_path, caplog):
    """#205 regression, `mode="update"`: after the mover consumed the spec, the
    hunter's late `specified` harness write (the lifecycle update) lands AFTER
    the move. It must be a no-op success returning the durable consumed Path -
    produced/ stays absent, so produced/ and consumed/ hold the name once (G4)
    and the surfer's inbox drains."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert store.consume_spec(PROJECT, FAULT_KEY, "registration_probe") is True
    assert not _spec_file(tmp_path, "produced").exists()
    with caplog.at_level(logging.WARNING):
        result = store.write_spec(PROJECT, FAULT_KEY, mode="update", spec=_spec(), **k)
    assert _spec_file(tmp_path, "consumed").exists()
    assert not _spec_file(tmp_path, "produced").exists()
    assert store.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert isinstance(result, Path)
    assert result == _spec_file(tmp_path, "consumed")
    assert any("post-move write, #205" in r.message for r in caplog.records)


def test_produced_create_write_after_move_is_a_no_op(tmp_path, caplog):
    """#205 regression, `mode="create"`: the create-mode novelty gate only
    checks the produced side, so a post-move create write previously fabricated
    a fresh produced/ copy (the move-aware check must short-circuit BEFORE the
    novelty gate). It is now a no-op success returning the consumed Path."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert store.consume_spec(PROJECT, FAULT_KEY, "registration_probe") is True
    with caplog.at_level(logging.WARNING):
        result = store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert _spec_file(tmp_path, "consumed").exists()
    assert not _spec_file(tmp_path, "produced").exists()
    assert store.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert isinstance(result, Path)
    assert result == _spec_file(tmp_path, "consumed")
    assert any("post-move write, #205" in r.message for r in caplog.records)


def test_move_aware_no_op_keeps_consume_a_noop_success(tmp_path, caplog):
    """#205 quiesce proof: after the move-aware no-op, the next mover tick has
    an empty produced inbox - `consume_spec` is a no-op success (never the
    dual-sided clobber refusal), so the run reaches terminal (no re-dispatch
    churn, no hang in `running`)."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert store.consume_spec(PROJECT, FAULT_KEY, "registration_probe") is True
    store.write_spec(PROJECT, FAULT_KEY, mode="update", spec=_spec(), **k)
    with caplog.at_level(logging.WARNING):
        assert store.consume_spec(PROJECT, FAULT_KEY, "registration_probe") is True
    assert store.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert not any("both produced/ and consumed/" in r.message for r in caplog.records)


# --- no regression: the ordinary sides keep their semantics ------------------

def test_produced_write_still_creates_when_consumed_absent(tmp_path):
    """A normal produced-target write with no consumed/ twin still creates the
    produced file (create) and re-authors it in place (update) - the guard only
    fires on a post-move write."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    result = store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert isinstance(result, Path)
    assert result == _spec_file(tmp_path, "produced")
    assert _spec_file(tmp_path, "produced").exists()
    assert not _spec_file(tmp_path, "consumed").exists()
    store.write_spec(PROJECT, FAULT_KEY, mode="update",
                     spec=_spec(test="t2"), **k)
    assert store.read_spec(PROJECT, FAULT_KEY, **k)["test"] == "t2"
    assert store.produced_spec_files(PROJECT, FAULT_KEY) == ["registration_probe"]


def test_consumed_side_write_is_unaffected(tmp_path):
    """A `side="consumed"` write is untouched by the guard: replay still
    overwrites the consumed record in place (the mover's at-least-once marker
    is re-dumped, never blocked, never clobbered)."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create", side="consumed",
                     spec=_spec(), **k)
    assert _spec_file(tmp_path, "consumed").exists()
    assert not _spec_file(tmp_path, "produced").exists()
    store.write_spec(PROJECT, FAULT_KEY, mode="update", side="consumed",
                     spec=_spec(test="t2"), **k)
    assert store.read_spec(PROJECT, FAULT_KEY, side="consumed",
                           **k)["test"] == "t2"
    assert not _spec_file(tmp_path, "produced").exists()


def test_config_key_from_fault_key_accepts_a_system_unit_with_double_colon():
    # G4 regression (live e2e eval): the `::` semantic-key form of a System
    # unit id (which itself contains `::`) must normalise to the same key, and
    # the `_` folder form must round-trip to it too.
    from polymerhus.attack.hunting.hunter_memory import config_key_from_fault_key

    unit = "System:AuthorizationSystem::__singleton__"
    key = f"{unit}::CWE-1220::Broken Function Level Authorization (BFLA)"
    assert config_key_from_fault_key(key) == key
    folder = (
        "System:AuthorizationSystem::__singleton__"
        "_CWE-1220_Broken Function Level Authorization (BFLA)"
    )
    assert config_key_from_fault_key(folder) == key
    HunterMemoryStore._validate_fault_key(key)


# --- #340: notes.yaml is written atomically ----------------------------------

def _notes_file(tmp_path: Path) -> Path:
    return tmp_path / PROJECT / "hunting" / "hunter" / "notes.yaml"


def _tmp_leftovers(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [p for p in directory.iterdir() if p.name.endswith(".tmp")]


def _append(store: HunterMemoryStore, body: str) -> None:
    store.write_note(
        PROJECT, action="append", fault_key=FAULT_KEY, note_name="n1",
        kind="freeform", body=body,
    )


def test_failed_notes_dump_leaves_prior_content_intact(tmp_path, monkeypatch, caplog):
    """#340: a raising dump must never truncate notes.yaml. The old plain
    `path.open("w")` truncated the file before dumping, so a mid-dump abort
    left it empty/malformed and every later read raised. The atomic write
    renders the body first, so the previous file survives untouched."""
    store = HunterMemoryStore(root_dir=tmp_path)
    _append(store, "first")
    notes = _notes_file(tmp_path)
    before = notes.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("dump crashed (fixture)")

    monkeypatch.setattr(
        "polymerhus.attack.hunting.hunter_memory.yaml.safe_dump", boom)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError):
            _append(store, "second")
    monkeypatch.undo()

    assert notes.read_text(encoding="utf-8") == before
    assert [n["body"] for n in store.read_notes(PROJECT)] == ["first"]
    assert _tmp_leftovers(notes.parent) == []


def test_aborted_replace_leaves_prior_notes_intact(tmp_path, monkeypatch):
    """#340: an abort AFTER the temp file is fully written but BEFORE the
    `os.replace` lands leaves the previous notes.yaml intact and cleans up the
    temp. Only the atomic rename mutates the live file."""
    store = HunterMemoryStore(root_dir=tmp_path)
    _append(store, "first")
    notes = _notes_file(tmp_path)
    before = notes.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated kill before the atomic rename")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        _append(store, "second")
    monkeypatch.undo()

    assert notes.read_text(encoding="utf-8") == before
    assert [n["body"] for n in store.read_notes(PROJECT)] == ["first"]
    assert _tmp_leftovers(notes.parent) == []


def test_reader_never_sees_a_partial_notes_file(tmp_path, monkeypatch):
    """#340: a concurrent reader observes the OLD complete file for the whole
    write, because the new content only becomes visible at the atomic rename.
    The hook fires exactly at that boundary and records what a reader sees."""
    store = HunterMemoryStore(root_dir=tmp_path)
    _append(store, "first")
    notes = _notes_file(tmp_path)
    before = notes.read_text(encoding="utf-8")
    observed: list[str] = []
    real_replace = os.replace

    def observe(src, dst):
        observed.append(notes.read_text(encoding="utf-8"))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", observe)
    _append(store, "second")
    monkeypatch.undo()

    assert observed == [before]
    assert [n["body"] for n in store.read_notes(PROJECT)] == ["second", "first"]
    assert _tmp_leftovers(notes.parent) == []


def test_failed_spec_dump_leaves_no_partial_file(tmp_path, monkeypatch):
    """#340: `write_spec` writes the produced spec file the same way, so the
    same hazard applies. A raising dump must leave no partial spec file on
    disk (the old truncate-then-dump left an empty file the reader refused)."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    spec_file = _spec_file(tmp_path, "produced")

    def boom(*args, **kwargs):
        raise RuntimeError("dump crashed (fixture)")

    monkeypatch.setattr(
        "polymerhus.attack.hunting.hunter_memory.yaml.safe_dump", boom)
    with pytest.raises(RuntimeError):
        store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    monkeypatch.undo()

    assert not spec_file.exists()
    assert _tmp_leftovers(spec_file.parent) == []


# --- #341: notes.yaml growth is bounded (count + size, value-aware eviction) --

def _append_named(store: HunterMemoryStore, name: str, body: str = "x",
                  provenance: dict | None = None) -> None:
    store.write_note(
        PROJECT, action="append", fault_key=FAULT_KEY, note_name=name,
        kind="freeform", body=body, provenance=provenance,
    )


def _unbounded_size(monkeypatch) -> None:
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_BYTES", 10**9)


def test_notes_file_is_bounded_by_record_count(tmp_path, monkeypatch):
    """#341: a long run appends records forever; the store keeps only the
    newest HUNTER_NOTES_MAX_RECORDS, so the whole-file rewrite stays O(bound)
    and the file cannot grow without limit. The reader still sees one complete
    parseable file."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 3)
    _unbounded_size(monkeypatch)
    store = HunterMemoryStore(root_dir=tmp_path)
    for i in range(6):
        _append_named(store, f"n{i}")
    notes = store.read_notes(PROJECT)
    assert [n["note_name"] for n in notes] == ["n5", "n4", "n3"]
    raw = yaml.safe_load(_notes_file(tmp_path).read_text(encoding="utf-8"))
    assert len(raw) == 3


def test_notes_eviction_preserves_durable_pod_export_records(tmp_path, monkeypatch):
    """#341: the durable prior-insight record - the Q16 pod-export stub
    (`provenance.verdict_stub`, consumed by `HuntStore.read_hunter_notes` into
    a config's `prior_hunt_insights`) - survives ordinary eviction. The oldest
    REASONING notes are dropped first; the stub is kept."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 3)
    _unbounded_size(monkeypatch)
    store = HunterMemoryStore(root_dir=tmp_path)
    _append_named(store, "pod-export:s1", body="stub",
                  provenance={"verdict_stub": True, "run_id": "r", "source": "s"})
    for i in range(5):
        _append_named(store, f"n{i}")
    names = {n["note_name"] for n in store.read_notes(PROJECT)}
    assert names == {"pod-export:s1", "n3", "n4"}


def test_notes_bound_is_absolute_when_durable_records_alone_exceed_it(tmp_path, monkeypatch):
    """#341: the bound is absolute - when the protected durable records alone
    exceed it, the hard ceiling still trims the oldest, so the file can never
    grow without limit. The newest survive."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 2)
    _unbounded_size(monkeypatch)
    store = HunterMemoryStore(root_dir=tmp_path)
    for i in range(3):
        _append_named(store, f"pod-export:s{i}",
                      provenance={"verdict_stub": True})
    names = {n["note_name"] for n in store.read_notes(PROJECT)}
    assert names == {"pod-export:s1", "pod-export:s2"}


def test_notes_file_is_bounded_by_serialized_size(tmp_path, monkeypatch):
    """#341: the count bound alone is not enough when one record body is huge
    (the observed pod-export stubs carry a full export log). A serialized-size
    ceiling evicts oldest-first until the file fits, so the rewrite cost is
    bounded by bytes, not by record count."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 10**6)
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_BYTES", 4000)
    store = HunterMemoryStore(root_dir=tmp_path)
    for i in range(20):
        _append_named(store, f"n{i}", body="z" * 500)
    raw = _notes_file(tmp_path).read_text(encoding="utf-8")
    assert len(raw.encode("utf-8")) <= 4000
    kept = yaml.safe_load(raw)
    assert 1 <= len(kept) < 20
    assert kept[-1]["note_name"] == "n19"


def test_a_single_oversized_record_is_kept_whole(tmp_path, monkeypatch):
    """#341: a record larger than the whole-file ceiling is never truncated
    (the write must land); the ceiling bounds the file EXCEPT for that one
    in-flight record."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 10**6)
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_BYTES", 100)
    store = HunterMemoryStore(root_dir=tmp_path)
    _append_named(store, "oversized", body="z" * 5000)
    notes = store.read_notes(PROJECT)
    assert len(notes) == 1
    assert notes[0]["note_name"] == "oversized"

