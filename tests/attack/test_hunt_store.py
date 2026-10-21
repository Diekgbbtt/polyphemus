"""Unit tier: the residual project notes vocabulary and notes surface.

Pure filesystem mechanics - no Neo4j, no LLM. T10 (#383) removed the hunt
store's config I/O, key helpers, and bounded `memory.yaml` notes surface (no
live consumer). This file pins what remains: the phase-1 note-kind vocabulary
(the base `HunterMemoryStore` / `ThreatModelStore` extend) and the small
append/read contract of `ProjectMemoryStore`.
"""
from __future__ import annotations

import pytest

from polymerhus.attack.hunting.hunt_store import ProjectMemoryStore

PROJECT = "proj-1"
UNIT = "Service:catalogue-and-discovery"
FAULT = "CWE-639"


def _notes_file(tmp_path):
    return tmp_path / "projects" / PROJECT / "notes.yaml"


def test_the_note_kind_vocabulary_is_the_phase_1_closed_set():
    assert ProjectMemoryStore.NOTE_KINDS == (
        "hypothesis_refusal", "implicit_test_primitive", "freeform",
    )


def test_notes_append_in_natural_order_and_read_latest_first(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    store.append_note(PROJECT, UNIT, FAULT, "missing-capability", "freeform", "first")
    store.append_note(PROJECT, UNIT, FAULT, "refusal", "hypothesis_refusal", "second")
    store.append_note(PROJECT, UNIT, FAULT, "primitive", "implicit_test_primitive",
                      "third")
    notes = store.read_notes(PROJECT)
    assert [n["body"] for n in notes] == ["third", "second", "first"]
    # The stored record keeps the documented shape and monotonic sequence.
    assert notes[-1]["key"] == f"{UNIT}:{FAULT}:missing-capability"
    assert [n["_seq"] for n in notes] == [3, 2, 1]
    assert all(n["_ref"].startswith("note-") for n in notes)


def test_an_unknown_note_kind_is_refused(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    with pytest.raises(ValueError, match="unknown note kind"):
        store.append_note(PROJECT, UNIT, FAULT, "x", "not-a-kind", "body")
    assert not _notes_file(tmp_path).exists()


def test_a_later_store_reads_the_prior_pass_notes(tmp_path):
    """A later pass on the same project reads the prior pass's notes through a
    FRESH store at the same root - the notes file is per-project durable."""
    ProjectMemoryStore(tmp_path).append_note(
        PROJECT, UNIT, FAULT, "surface", "freeform", "track the IDOR surface")
    notes = ProjectMemoryStore(tmp_path).read_notes(PROJECT, parent_key=f"{UNIT}:{FAULT}")
    assert [n["body"] for n in notes] == ["track the IDOR surface"]


def test_the_grep_filters_match_key_and_body(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    store.append_note(PROJECT, UNIT, FAULT, "surface", "freeform", "the WAF is on")
    store.append_note(PROJECT, UNIT, FAULT, "refusal", "hypothesis_refusal", "absent")
    assert [n["body"] for n in store.read_notes(PROJECT, body_keyword="waf")] == [
        "the WAF is on"]
    assert [n["body"] for n in store.read_notes(PROJECT, key_keyword="refusal")] == [
        "absent"]
    assert store.read_notes(PROJECT, body_keyword="nope") == []


def test_a_corrupt_notes_file_raises_rather_than_returning_empty(tmp_path):
    """O4: a corrupt file must not read as "no notes" - the append path rewrites
    the whole file and would silently destroy the prior history."""
    path = _notes_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("notes: [unterminated", encoding="utf-8")
    with pytest.raises(OSError, match="unreadable notes file"):
        ProjectMemoryStore(tmp_path).read_notes(PROJECT)
