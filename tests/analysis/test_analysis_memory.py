"""Unit tier: the analysis episodic-memory store (`analysis.memory`, T3).

The store is the analysis analogue of the hunter's `notes.yaml`: a per-project,
whole-file YAML record list keyed by Service slug, written through the shared
`BoundedRecordStore` mechanics and bounded by the shared
`retain_bounded_records`. These tests pin the closed L1-modelling note-kind
enum, the keyed append/update/delete/read surface, the bound, and the
within-run/cross-run read-back - no LLM, no graph, no live infrastructure.
"""
from __future__ import annotations

import pytest
import yaml

from polymerhus.analysis import memory
from polymerhus.analysis.memory import (
    MEMORY_NOTES_MAX_BYTES,
    MEMORY_NOTES_MAX_RECORDS,
    NOTE_KINDS,
    AnalysisMemoryStore,
)

PROJECT = "proj-1"


# --- the closed note-kind enum (the L1-modelling fence) -----------------------

def test_note_kinds_are_the_closed_l1_modelling_enum():
    """The five ratified L1-modelling kinds, in order, and NOTHING else."""
    assert NOTE_KINDS == (
        "assignment", "system", "data", "refusal", "open_question"
    )


def test_note_kinds_carry_no_phase3_vocabulary():
    """The analysis CONTEXT fence (ADR D30): the phase-3 hunting vocabulary is
    unratified here, so no note kind may speak it."""
    banned = ("fault", "payload", "technique", "vector", "vulnerability",
              "hypothesis", "probe")
    for kind in NOTE_KINDS:
        assert not any(word in kind.lower() for word in banned), kind


# --- append / update / delete / read ------------------------------------------

def test_append_then_read_by_unit_and_keyword(tmp_path):
    store = AnalysisMemoryStore(root_dir=tmp_path)
    store.write_note(PROJECT, unit="checkout", note_name="owns-cart",
                     kind="data", body="cart line items are checkout-owned")
    store.write_note(PROJECT, unit="search", note_name="index",
                     kind="system", body="a search index system fronts the catalogue")

    # read everything, latest-first
    all_notes = store.read_notes(PROJECT)
    assert [n["note_name"] for n in all_notes] == ["index", "owns-cart"]
    # read by unit
    checkout = store.read_notes(PROJECT, parent_key="checkout")
    assert [n["unit"] for n in checkout] == ["checkout"]
    # read by key keyword
    indexed = store.read_notes(PROJECT, key_keyword="index")
    assert [n["note_name"] for n in indexed] == ["index"]
    # read by body keyword
    cart = store.read_notes(PROJECT, body_keyword="cart line")
    assert [n["note_name"] for n in cart] == ["owns-cart"]


def test_update_and_delete_are_keyed_and_denote_a_miss(tmp_path):
    store = AnalysisMemoryStore(root_dir=tmp_path)
    key = store.write_note(PROJECT, unit="checkout", note_name="n",
                           kind="assignment", body="first")
    assert key == "checkout:n"

    changed = store.write_note(PROJECT, unit="checkout", note_name="n",
                               action="update", kind="refusal", body="second")
    assert changed == key
    note = store.read_notes(PROJECT, parent_key="checkout")[0]
    assert note["kind"] == "refusal" and note["body"] == "second"

    removed = store.write_note(PROJECT, unit="checkout", note_name="n",
                               action="delete", kind="refusal", body="")
    assert removed == key
    assert store.read_notes(PROJECT) == []
    # an update/delete on a missing key is a denoted miss, never a failure
    assert store.write_note(PROJECT, unit="ghost", note_name="n",
                            action="update", kind="refusal", body="x") is None


def test_unknown_kind_or_action_is_rejected(tmp_path):
    store = AnalysisMemoryStore(root_dir=tmp_path)
    with pytest.raises(ValueError):
        store.write_note(PROJECT, unit="checkout", note_name="n",
                         kind="fault_hypothesis", body="x")
    with pytest.raises(ValueError):
        store.write_note(PROJECT, unit="checkout", note_name="n", action="merge",
                         kind="system", body="x")


def test_has_note_is_keyed_exactly_by_unit(tmp_path):
    store = AnalysisMemoryStore(root_dir=tmp_path)
    assert store.has_note(PROJECT, "checkout") is False
    store.write_note(PROJECT, unit="checkout", note_name="n", kind="system", body="x")
    assert store.has_note(PROJECT, "checkout") is True
    # a prefix-sibling unit is NOT the same unit
    assert store.has_note(PROJECT, "check") is False


def test_attributes_project_each_note(tmp_path):
    store = AnalysisMemoryStore(root_dir=tmp_path)
    store.write_note(PROJECT, unit="checkout", note_name="n",
                     kind="system", body="x")
    projected = store.read_notes(PROJECT, attributes=["note_name", "kind"])
    assert projected == [{"note_name": "n", "kind": "system"}]


# --- the write bound (the shared retain_bounded_records) ----------------------

def test_notes_file_is_bounded_by_record_count(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_NOTES_MAX_RECORDS", 3)
    store = AnalysisMemoryStore(root_dir=tmp_path)
    for i in range(6):
        store.write_note(PROJECT, unit=f"unit-{i}", note_name="n",
                         kind="open_question", body=str(i))
    notes = store.read_notes(PROJECT)
    assert len(notes) == 3
    # the NEWEST records are kept (oldest evicted)
    assert [n["body"] for n in notes] == ["5", "4", "3"]


def test_notes_file_is_bounded_by_serialized_size(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_NOTES_MAX_BYTES", 600)
    store = AnalysisMemoryStore(root_dir=tmp_path)
    for i in range(10):
        store.write_note(PROJECT, unit=f"unit-{i}", note_name="n",
                         kind="open_question", body="x" * 200)
    raw = (tmp_path / PROJECT / "analysis" / "memory.yaml").read_text(encoding="utf-8")
    assert len(raw.encode("utf-8")) <= 600 + 400  # the newest record is always kept whole


def test_the_retained_step_is_read_back_through_one_shared_bound(tmp_path):
    """A store write lands the shared bound; the file is a bare YAML list."""
    store = AnalysisMemoryStore(root_dir=tmp_path)
    store.write_note(PROJECT, unit="checkout", note_name="n", kind="data", body="x")
    path = tmp_path / PROJECT / "analysis" / "memory.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, list) and loaded[0]["unit"] == "checkout"


def test_a_corrupt_notes_file_raises_and_never_returns_empty(tmp_path):
    """A rewrite-on-write store must fail LOUD on a corrupt file or it would
    silently destroy history (the hunting-memory canon)."""
    store = AnalysisMemoryStore(root_dir=tmp_path)
    path = tmp_path / PROJECT / "analysis" / "memory.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("key: [unclosed\n", encoding="utf-8")
    with pytest.raises(OSError):
        store.read_notes(PROJECT)
    assert MEMORY_NOTES_MAX_RECORDS >= 1 and MEMORY_NOTES_MAX_BYTES >= 1


def test_read_back_is_within_run_and_cross_run(tmp_path):
    """Two store instances over the same root: a note written by an earlier unit
    (or an earlier run) is read by a later one."""
    first = AnalysisMemoryStore(root_dir=tmp_path)
    first.write_note(PROJECT, unit="checkout", note_name="cart",
                     kind="data", body="cart is checkout-owned")
    second = AnalysisMemoryStore(root_dir=tmp_path)
    assert [n["note_name"] for n in second.read_notes(PROJECT, key_keyword="checkout")] == ["cart"]
