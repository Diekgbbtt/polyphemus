"""Unit tier: T7 (#157) - the pod-owned experiment-memory store (D84-20/28).

The persistent hunting test-executor memory: notes keyed by the spec's canonical
id, each with a monotonic `_seq`/`_ref`, append-only, grep-match read
(parent_key / key_keyword / body_keyword), read-latest. The note VALUE fields
are the D84-32 CANONICAL set - no `differential_shape`, no `resume_point`.
The prompt-memory pattern (D84-27) ships the persistent `MEMORY_READ_GUIDANCE`
and the per-turn indexable key-list `compose_memory_guidance`. Pure file store -
no LLM, no DB.
"""
from __future__ import annotations

import pytest

from polymerhus.attack.hunting.pod.context import canonical_spec_hash
from polymerhus.attack.hunting.pod.pod_memory import (
    POD_MEMORY_ROOT,
    POD_NOTE_KINDS,
    PodMemoryStore,
    canonical_spec_id,
    compose_memory_guidance,
    notation_key,
)

SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability",
}


@pytest.fixture
def store(tmp_path):
    return PodMemoryStore(tmp_path)


# --- canonical_spec_id (D84-2, relocated into the pod) ------------------------

def test_canonical_spec_id_is_byte_identical_to_the_shared_canonical_hash():
    assert canonical_spec_id(SPEC) == canonical_spec_hash(SPEC) == canonical_spec_id(
        dict(reversed(list(SPEC.items()))))


def test_store_root_lives_at_the_hunting_module_seam():
    # D84-28: the store is a sibling of the hunt store under attack/hunting/data/.
    assert str(POD_MEMORY_ROOT).endswith("attack/hunting/data/pod-memory")


def test_canonical_spec_id_is_deterministic_and_key_order_insensitive():
    a = canonical_spec_id(SPEC)
    b = canonical_spec_id(dict(reversed(list(SPEC.items()))))
    assert a == canonical_spec_id(SPEC)   # stable
    assert b == a                          # key order never changes it


# --- the store layout and notation keys ---------------------------------------

def test_notation_key_chains_spec_variant_and_note_name():
    assert notation_key("h1", "v3", "exhaustion") == "h1:v3:exhaustion"


def test_append_lands_under_specs_spec_id_notes_yaml(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="exhaustion", kind="experiment_summary",
                 body="space genuinely exhausted")
    path = store._root / "specs" / spec_id / "notes.yaml"
    assert path.exists()
    assert path.read_text(encoding="utf-8").count("experiment_summary") >= 1


# --- closed kinds enum (D84-28) -----------------------------------------------

def test_note_kinds_are_closed_and_the_consolidation_kind_is_first():
    assert POD_NOTE_KINDS == ("experiment_summary", "kb_insight", "freeform")


def test_append_rejects_a_kind_outside_the_enum(store):
    with pytest.raises(ValueError):
        store.append(canonical_spec_id(SPEC), variant_ref="v0", note_name="x",
                     kind="hypothesis_refusal", body="b")


# --- the D84-32 note value fields ---------------------------------------------

def test_note_value_fields_match_the_canonical_d84_32_set(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v4", note_name="experiment", kind="experiment_summary",
                 body="summary", classification="symptom-absent",
                 symptom_status="clean", kb_primitives_used=["status-diff"],
                 exhaustion_evidence="no new primitive from the terminal KB query",
                 evidence="raw obs 1", provenance={"parent_ref": "v3"})
    (note,) = store.read_notes(spec_id)
    assert set(note) == {
        "_seq", "_ref", "key", "spec_id", "variant_ref", "note_name", "kind", "body",
        "classification", "symptom_status", "kb_primitives_used", "exhaustion_evidence",
        "evidence", "provenance",
    }
    # D84-30/31: no differential_shape, no resume_point residue.
    assert "differential_shape" not in note
    assert "resume_point" not in note


def test_note_value_round_trip(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="insight", kind="kb_insight",
                 body="payload family X defeats the WAF", classification="",
                 symptom_status="", kb_primitives_used=["WAF-bypass"],
                 exhaustion_evidence="", evidence="KB: ...", provenance={"src": "kb"})
    note = store.read_notes(spec_id)[0]
    assert note["variant_ref"] == "v0"
    assert note["note_name"] == "insight"
    assert note["kind"] == "kb_insight"
    assert note["body"] == "payload family X defeats the WAF"
    assert note["kb_primitives_used"] == ["WAF-bypass"]
    assert note["spec_id"] == spec_id
    assert note["key"] == f"{spec_id}:v0:insight"


def test_seq_is_monotonic_per_spec_and_ref_is_zero_padded(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="a", kind="freeform", body="1")
    store.append(spec_id, variant_ref="v1", note_name="b", kind="freeform", body="2")
    a, b = store.read_notes(spec_id)
    assert (a["_seq"], b["_seq"]) == (2, 1)       # latest-first on read
    assert b["_ref"] == "note-0001"
    assert a["_ref"] == "note-0002"


def test_append_only_history_is_preserved(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="n", kind="freeform", body="old")
    store.append(spec_id, variant_ref="v1", note_name="n", kind="freeform", body="new")
    bodies = [n["body"] for n in store.read_notes(spec_id)]
    assert bodies == ["new", "old"]


def test_per_spec_isolation(store):
    sid_a = canonical_spec_id(SPEC)
    sid_b = canonical_spec_id({**SPEC, "testing_pattern": "reflected"})
    store.append(sid_a, variant_ref="v0", note_name="n", kind="freeform", body="a")
    store.append(sid_b, variant_ref="v0", note_name="n", kind="freeform", body="b")
    assert [n["body"] for n in store.read_notes(sid_a)] == ["a"]
    assert [n["body"] for n in store.read_notes(sid_b)] == ["b"]


# --- the grep-match read (parent_key / key_keyword / body_keyword) ------------

def test_read_parent_key_ranges_the_variant_prefix(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="a", kind="freeform", body="one")
    store.append(spec_id, variant_ref="v1", note_name="b", kind="freeform", body="two")
    hits = store.read_notes(spec_id, parent_key=f"{spec_id}:v1")
    assert [n["variant_ref"] for n in hits] == ["v1"]


def test_read_key_keyword_filters_on_the_note_key(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="capability", kind="freeform", body="x")
    store.append(spec_id, variant_ref="v1", note_name="defence", kind="freeform", body="y")
    hits = store.read_notes(spec_id, key_keyword="capab")
    assert [n["note_name"] for n in hits] == ["capability"]


def test_read_body_keyword_filters_on_the_note_body(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="a", kind="freeform", body="WAF blocked")
    store.append(spec_id, variant_ref="v1", note_name="b", kind="freeform", body="reflected")
    hits = store.read_notes(spec_id, body_keyword="waf")
    assert [n["note_name"] for n in hits] == ["a"]


def test_zero_matches_is_a_valid_empty_result(store):
    assert store.read_notes(canonical_spec_id(SPEC)) == []
    assert store.read_notes(canonical_spec_id(SPEC), body_keyword="nope") == []


# --- note_keys: the prompt-embedded index (D84-27) ----------------------------

def test_note_keys_lists_the_indexable_keys_newest_first(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="capability", kind="freeform", body="x")
    store.append(spec_id, variant_ref="v1", note_name="exhaustion", kind="experiment_summary",
                 body="y")
    assert store.note_keys(spec_id) == [f"{spec_id}:v1:exhaustion", f"{spec_id}:v0:capability"]
    assert store.note_keys(canonical_spec_id({"target_identity": "other"})) == []


# --- fail-open durability semantics -------------------------------------------

def test_corrupt_notes_file_raises_not_silently_returns_empty(tmp_path):
    """A corrupt file raises (O4) rather than returning [] - the rewrite-on-append
    would otherwise silently destroy every earlier record."""
    store = PodMemoryStore(tmp_path)
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="a", kind="freeform", body="1")
    path = store._root / "specs" / spec_id / "notes.yaml"
    path.write_text("_ref: [unclosed flow mapping\n", encoding="utf-8")
    with pytest.raises(OSError):
        store.read_notes(spec_id)


def test_append_failure_raises_for_the_caller_to_degrade(tmp_path):
    store = PodMemoryStore(tmp_path / "readonly")
    store._root.mkdir()
    (store._root / "specs").write_text("", encoding="utf-8")   # make specs a FILE
    with pytest.raises(OSError):
        store.append(canonical_spec_id(SPEC), variant_ref="v0", note_name="a",
                     kind="freeform", body="1")


# --- the prompt-memory pattern (D84-27) ---------------------------------------

def test_memory_read_guidance_is_a_persistent_system_block():
    from polymerhus.attack.hunting.pod.pod_memory import MEMORY_READ_GUIDANCE

    assert "note" in MEMORY_READ_GUIDANCE.lower()
    assert "experiment_summary" in MEMORY_READ_GUIDANCE
    assert "parent_key" in MEMORY_READ_GUIDANCE


def test_compose_memory_guidance_embeds_an_indexable_key_list(store):
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="exhaustion", kind="experiment_summary",
                 body="done")
    guidance = compose_memory_guidance(store, spec_id)
    assert f"{spec_id}:v0:exhaustion" in guidance
    # The reading contract ships with the keys (system block re-presented per turn).
    assert "parent_key" in guidance
    assert "experiment_summary" in guidance


def test_compose_memory_guidance_marks_an_empty_index(store):
    guidance = compose_memory_guidance(store, canonical_spec_id(SPEC))
    assert "no notes" in guidance.lower()


def test_compose_memory_guidance_is_fail_open_without_a_store():
    assert compose_memory_guidance(None, "h1") != ""