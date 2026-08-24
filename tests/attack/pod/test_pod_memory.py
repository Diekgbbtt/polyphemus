"""Unit tier: T2 (#178) - the pod-owned experiment-memory store (D84-33..38).

The per-project deterministic-key store, coherent per-spec layout (operator,
2026-08-24): `experiment-log/<order>.yaml` (one file per variant, the D6 slice +
the `experiment_summary` terminal record, overwritten idempotently) +
`variants/<ref>.yaml` (the minted TestImplementationSpec variants) + the
per-project `notes.yaml` keyed `<spec_id>:<order>:<note_name>`, append +
read-latest. The spec identifier is the #164 hunter's `<fault>_<strategy>`
(D84-34), the order is the variant ordinal, and the variant ref `vN` maps 1:1 to
the order N. The reading surface gains the typed attribute filters (`order`,
`kind`, `classification`, `symptom_status`) beside the retained `parent_key` /
`key_keyword` / `body_keyword` substring match. There is NO `_seq`/`_ref`
anywhere (D84-36). The prompt-memory pattern (D84-27) ships the persistent
`MEMORY_READ_GUIDANCE` and the per-turn indexable `compose_memory_guidance`.
Pure file store - no LLM, no DB.
"""
from __future__ import annotations

import pytest

from polymerhus.attack.hunting.pod.pod_memory import (
    POD_NOTE_KINDS,
    PodMemoryStore,
    compose_memory_guidance,
    note_key,
    spec_identifier,
)

# The #164 `<fault>_<strategy>` spec id (D84-34), used as the memory key.
SPEC_ID = spec_identifier("sqli", "blind")
OTHER_ID = spec_identifier("xss", "reflected")


@pytest.fixture
def store(tmp_path):
    return PodMemoryStore(tmp_path)


# --- the spec identifier: <fault>_<strategy> (D84-34) -------------------------

def test_spec_identifier_joins_sanitised_fault_and_strategy():
    assert spec_identifier("sqli", "blind") == "sqli_blind"
    # `_` is the separator, so a keyword may not carry it; `:` is poisoned.
    assert spec_identifier("sqli", "blind_boolean") == "sqli_blind-boolean"
    assert spec_identifier("open:redirect", "sql") == "open-redirect_sql"


def test_spec_identifier_rejects_a_pathological_keyword():
    with pytest.raises(ValueError):
        spec_identifier("", "x")
    with pytest.raises(ValueError):
        spec_identifier(".", "x")


def test_spec_id_is_the_semantic_key_never_a_content_hash():
    # Q13 (ADR #169): the canonical-hash spec identity is REMOVED - the memory
    # key AND the session-address spec discriminator are the semantic
    # `<fault>_<strategy>` id, which differs from any content hash BY
    # CONSTRUCTION: the id is the short sanitised keyword pair (the old
    # sha256 spec digest was 64 hex chars), so SPEC_ID != hash holds without
    # a hash ever being computed (the function is gone from the identity
    # path).
    assert SPEC_ID == "sqli_blind"
    assert len(SPEC_ID) != 64                       # never the sha256 digest shape
    assert "_" in SPEC_ID                           # the semantic pair separator


# --- the store layout: variants + experiment-log + notes.yaml (D84-33) ----------

def test_store_layout_is_variants_experiment_log_and_notes_yaml(store):
    store.append(SPEC_ID, order=0, note_name="capability", kind="kb_insight",
                 body="payload family X")
    store.write_variant(SPEC_ID, "v0", {"ref": "v0", "spec": {}})
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [],
                                            "interpretations": [], "executed": []})
    variants_file = store._root / SPEC_ID / "variants" / "v0.yaml"
    log_file = store._root / SPEC_ID / "experiment-log" / "0.yaml"
    notes_file = store._root / "notes.yaml"
    assert variants_file.exists()
    assert log_file.exists()
    assert notes_file.exists()


def test_store_needs_a_root_or_project_id(tmp_path):
    assert PodMemoryStore(tmp_path)._root == tmp_path
    assert PodMemoryStore(project_id="p1")._root.name == "test-executor-pod"
    with pytest.raises(ValueError):
        PodMemoryStore()


def test_per_project_scoping(tmp_path):
    # Two projects never leak notes or logs into each other (D84-33).
    a = PodMemoryStore(tmp_path / "proj-a")
    b = PodMemoryStore(tmp_path / "proj-b")
    a.append(SPEC_ID, order=0, note_name="n", kind="freeform", body="a")
    b.append(SPEC_ID, order=0, note_name="n", kind="freeform", body="b")
    assert [n["body"] for n in a.read_notes(SPEC_ID)] == ["a"]
    assert [n["body"] for n in b.read_notes(SPEC_ID)] == ["b"]


# --- the closed kinds enum (D84-28) -------------------------------------------

def test_note_kinds_are_closed_and_the_consolidation_kind_is_first():
    assert POD_NOTE_KINDS == ("experiment_summary", "kb_insight", "freeform")


def test_append_rejects_a_kind_outside_the_enum(store):
    with pytest.raises(ValueError):
        store.append(SPEC_ID, order=0, note_name="x", kind="hypothesis_refusal",
                     body="b")


# --- the note key pattern (D84-36) --------------------------------------------

def test_note_key_is_spec_id_colon_order_colon_name():
    assert note_key(SPEC_ID, 2, "experiment") == f"{SPEC_ID}:2:experiment"


def test_append_lands_a_note_under_the_deterministic_key(store):
    store.append(SPEC_ID, order=0, note_name="capability", kind="kb_insight",
                 body="payload family X")
    (note,) = store.read_notes(SPEC_ID)
    assert note["key"] == note_key(SPEC_ID, 0, "capability")
    assert note["spec_id"] == SPEC_ID
    assert note["order"] == 0


def test_note_value_fields_match_the_canonical_d84_32_set(store):
    store.append(SPEC_ID, order=0, note_name="experiment", kind="experiment_summary",
                 body="summary", classification="symptom-absent",
                 symptom_status="clean", kb_primitives_used=["status-diff"],
                 exhaustion_evidence="no new primitive from the terminal KB query",
                 evidence="raw obs 1", provenance={"parent_ref": "v0"})
    (note,) = store.read_notes(SPEC_ID)
    assert set(note) == {
        "key", "spec_id", "order", "note_name", "kind", "body",
        "classification", "symptom_status", "kb_primitives_used", "exhaustion_evidence",
        "evidence", "provenance",
    }
    # D84-36: no _seq/_ref residue anywhere.
    assert "_seq" not in note
    assert "_ref" not in note


def test_append_only_history_is_preserved_and_read_is_latest_first(store):
    store.append(SPEC_ID, order=0, note_name="n", kind="freeform", body="old")
    store.append(SPEC_ID, order=1, note_name="n", kind="freeform", body="new")
    bodies = [n["body"] for n in store.read_notes(SPEC_ID)]
    assert bodies == ["new", "old"]          # append + read-latest (D84-37)


def test_per_spec_isolation(store):
    store.append(SPEC_ID, order=0, note_name="n", kind="freeform", body="a")
    store.append(OTHER_ID, order=0, note_name="n", kind="freeform", body="b")
    assert [n["body"] for n in store.read_notes(SPEC_ID)] == ["a"]
    assert [n["body"] for n in store.read_notes(OTHER_ID)] == ["b"]


# --- the typed attribute read filters (D84-36) ---------------------------------

def test_read_order_filter_selects_the_variant_ordinal(store):
    store.append(SPEC_ID, order=0, note_name="a", kind="freeform", body="one")
    store.append(SPEC_ID, order=1, note_name="b", kind="freeform", body="two")
    hits = store.read_notes(SPEC_ID, order=1)
    assert [n["order"] for n in hits] == [1]


def test_read_kind_filter(store):
    store.append(SPEC_ID, order=0, note_name="a", kind="kb_insight", body="x")
    store.append(SPEC_ID, order=1, note_name="b", kind="freeform", body="y")
    hits = store.read_notes(SPEC_ID, kind="kb_insight")
    assert [n["note_name"] for n in hits] == ["a"]


def test_read_classification_and_symptom_status_filters(store):
    store.append(SPEC_ID, order=0, note_name="a", kind="experiment_summary",
                 body="x", classification="symptom-absent", symptom_status="clean")
    store.append(SPEC_ID, order=1, note_name="b", kind="experiment_summary",
                 body="y", classification="symptom-confirmed", symptom_status="clean")
    assert [n["order"] for n in store.read_notes(
        SPEC_ID, classification="symptom-confirmed")] == [1]
    assert [n["order"] for n in store.read_notes(
        SPEC_ID, symptom_status="clean")] == [1, 0]


# --- the retained substring read filters ---------------------------------------

def test_read_parent_key_ranges_the_key_prefix(store):
    store.append(SPEC_ID, order=0, note_name="a", kind="freeform", body="one")
    store.append(SPEC_ID, order=1, note_name="b", kind="freeform", body="two")
    hits = store.read_notes(SPEC_ID, parent_key=f"{SPEC_ID}:1")
    assert [n["order"] for n in hits] == [1]


def test_read_key_keyword_filters_on_the_note_key(store):
    store.append(SPEC_ID, order=0, note_name="capability", kind="freeform", body="x")
    store.append(SPEC_ID, order=1, note_name="defence", kind="freeform", body="y")
    hits = store.read_notes(SPEC_ID, key_keyword="capab")
    assert [n["note_name"] for n in hits] == ["capability"]


def test_read_body_keyword_filters_on_the_note_body(store):
    store.append(SPEC_ID, order=0, note_name="a", kind="freeform", body="WAF blocked")
    store.append(SPEC_ID, order=1, note_name="b", kind="freeform", body="reflected")
    hits = store.read_notes(SPEC_ID, body_keyword="waf")
    assert [n["note_name"] for n in hits] == ["a"]


def test_zero_matches_is_a_valid_empty_result(store):
    assert store.read_notes(SPEC_ID) == []
    assert store.read_notes(SPEC_ID, body_keyword="nope") == []


# --- the experiment-log slice + variants: per-variant, idempotent overwrite (D84-37)

def test_experiment_log_overwrites_idempotently(store):
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [{"status": 200}],
                                            "interpretations": [], "executed": []})
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [{"status": 404}],
                                            "interpretations": [], "executed": []})
    assert store.read_experiment_log(SPEC_ID, 0)["raw_observations"] == [{"status": 404}]
    # The deterministic path is the address: no unbounded accumulation.
    assert len(list((store._root / SPEC_ID / "experiment-log").iterdir())) == 1


def test_variant_overwrites_idempotently(store):
    store.write_variant(SPEC_ID, "v1", {"ref": "v1", "spec": {"a": 1}})
    store.write_variant(SPEC_ID, "v1", {"ref": "v1", "spec": {"a": 2}})
    assert store.read_variant(SPEC_ID, "v1")["spec"] == {"a": 2}
    assert store.list_variant_refs(SPEC_ID) == ["v1"]


def test_list_variant_orders_enumerates_following_variants(store):
    assert store.list_variant_orders(SPEC_ID) == []
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    store.write_experiment_log(SPEC_ID, 2, {"order": 2, "variant_ref": "v2",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    assert store.list_variant_orders(SPEC_ID) == [0, 2]


def test_experiment_logs_are_per_spec(store):
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    assert store.list_variant_orders(OTHER_ID) == []
    assert store.list_variant_refs(OTHER_ID) == []


def test_variant_ref_and_order_are_the_same_ordinal(store):
    # operator, 2026-08-24: `vN` <-> order N, so a minted variant and its log
    # slice are trivially mappable.
    from polymerhus.attack.hunting.pod.pod_memory import order_of, variant_ref
    assert variant_ref(0) == "v0" and variant_ref(3) == "v3"
    assert order_of("v0") == 0 and order_of("v3") == 3
    assert order_of("") == 0 and order_of("w0") == 0


def test_variant_summary_is_the_terminal_record_of_the_log_slice(store):
    # D84-35: the P3 experiment_summary lands in the variant's log slice, NOT
    # notes.yaml. write_variant_summary sets the terminal record idempotently.
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [{"status": 404}],
                                            "interpretations": [], "executed": ["s1"]})
    store.write_variant_summary(SPEC_ID, 0, "space exhausted; no symptom established")
    from polymerhus.attack.hunting.pod.pod_memory import read_variant_summary
    assert read_variant_summary(store, SPEC_ID, 0) == \
        "space exhausted; no symptom established"
    slice = store.read_experiment_log(SPEC_ID, 0)
    assert slice["experiment_summary"] == "space exhausted; no symptom established"
    assert slice["raw_observations"] == [{"status": 404}]   # D6 preserved
    # A summary write does NOT leak into notes.yaml (kb_insight/freeform only).
    assert store.read_notes(SPEC_ID) == []
    # Idempotent: a re-write replaces the terminal record.
    store.write_variant_summary(SPEC_ID, 0, "revised")
    assert read_variant_summary(store, SPEC_ID, 0) == "revised"


def test_read_variant_summary_fails_open_without_a_store_or_slice(tmp_path):
    from polymerhus.attack.hunting.pod.pod_memory import read_variant_summary
    assert read_variant_summary(None, SPEC_ID, 0) == ""
    # A valid store with no slice on file yields "" (the caller degrades), never a raise.
    assert read_variant_summary(PodMemoryStore(tmp_path), SPEC_ID, 0) == ""


# --- note_keys: the prompt-embedded index (D84-27) ----------------------------

def test_note_keys_lists_the_indexable_keys_newest_first(store):
    store.append(SPEC_ID, order=0, note_name="capability", kind="freeform", body="x")
    store.append(SPEC_ID, order=1, note_name="exhaustion", kind="experiment_summary",
                 body="y")
    assert store.note_keys(SPEC_ID) == [f"{SPEC_ID}:1:exhaustion", f"{SPEC_ID}:0:capability"]
    assert store.note_keys(OTHER_ID) == []


# --- the PodExport body (T7/#183): the pod's OWN terminal result ---------------

ENVELOPE = {
    "verdict": "unsuccessful",
    "evidence": {
        "terminal_reason": "space-exhausted", "iterations": 1, "clean": True,
        "interpretations": [], "init_validation": [], "variant_specs": [],
        "raw_observations": [{"status": 404}],
    },
}


def test_pod_export_round_trip_and_idempotent_overwrite(store):
    """T7 (GP1, D84-37): the export identifier is the run_id - a re-run of the
    same spec overwrites the SAME `<spec_id>/<run_id>.yaml` file (one file, the
    deterministic path is the address), reads back byte-equivalent."""
    store.write_pod_export(SPEC_ID, "run-42", ENVELOPE)
    assert store.read_pod_export(SPEC_ID, "run-42") == ENVELOPE
    # A re-run with the same run_id OVERWRITES, never accumulates.
    revised = {"verdict": "successful", "evidence": {"terminal_reason": "symptom-confirmed"}}
    store.write_pod_export(SPEC_ID, "run-42", revised)
    assert store.read_pod_export(SPEC_ID, "run-42") == revised
    assert len(list((store._root / SPEC_ID).iterdir())) == 1  # only the one export file
    # The file lives at the spec directory root (not in variants/experiment-log).
    assert (store._root / SPEC_ID / "run-42.yaml").exists()


def test_pod_export_is_per_spec(store):
    store.write_pod_export(SPEC_ID, "run-42", ENVELOPE)
    assert store.read_pod_export(OTHER_ID, "run-42") == {}
    assert store.list_pod_exports(OTHER_ID) == []


def test_pod_export_list_enumerates_run_ids(store):
    assert store.list_pod_exports(SPEC_ID) == []
    store.write_pod_export(SPEC_ID, "run-1", ENVELOPE)
    store.write_pod_export(SPEC_ID, "run-2", ENVELOPE)
    assert store.list_pod_exports(SPEC_ID) == ["run-1", "run-2"]


def test_pod_export_read_absent_returns_empty(store):
    assert store.read_pod_export(SPEC_ID, "nope") == {}


def test_pod_export_no_seq_or_ref_on_disk(store):
    store.write_pod_export(SPEC_ID, "run-42", ENVELOPE)
    import yaml
    loaded = yaml.safe_load(
        (store._root / SPEC_ID / "run-42.yaml").read_text(encoding="utf-8"))
    assert "_seq" not in loaded and "_ref" not in loaded


def test_pod_export_run_id_filename_keeps_colon_and_dash_but_not_path(store):
    """GP1/GP2: the run_id is a SINGLE filename segment - the `_`-separator
    rules for multi-part keys don't apply, so `:`/`-` are allowed; but it must
    stay filesystem-safe, so a path separator is sanitised (never nested)."""
    store.write_pod_export(SPEC_ID, "run:1-a", ENVELOPE)
    assert (store._root / SPEC_ID / "run:1-a.yaml").exists()
    assert store.list_pod_exports(SPEC_ID) == ["run:1-a"]
    # A `/` (or `\`) is a path separator - sanitised to `-`, not nested.
    store.write_pod_export(SPEC_ID, "a/b", ENVELOPE)
    assert (store._root / SPEC_ID / "a-b.yaml").exists()
    assert store.list_pod_exports(SPEC_ID) == ["a-b", "run:1-a"]


def test_pod_export_write_failure_raises_for_the_caller_to_degrade(tmp_path):
    store = PodMemoryStore(tmp_path)
    # Make the target path a DIRECTORY so the export write's open-for-write fails (O3).
    (store._root / SPEC_ID).mkdir(parents=True)
    (store._root / SPEC_ID / "run-42.yaml").mkdir()
    with pytest.raises(OSError):
        store.write_pod_export(SPEC_ID, "run-42", ENVELOPE)


# --- fail-open durability semantics -------------------------------------------

def test_corrupt_notes_file_raises_not_silently_returns_empty(tmp_path):
    """A corrupt file raises (O4) rather than returning [] - the rewrite paths
    would otherwise silently destroy every earlier record."""
    store = PodMemoryStore(tmp_path)
    store.append(SPEC_ID, order=0, note_name="a", kind="freeform", body="1")
    path = store._notes_file()
    path.write_text("_seq: [unclosed flow mapping\n", encoding="utf-8")
    with pytest.raises(OSError):
        store.read_notes(SPEC_ID)


def test_append_failure_raises_for_the_caller_to_degrade(tmp_path):
    store = PodMemoryStore(tmp_path / "readonly")
    store._root.mkdir()
    # Make the notes path a DIRECTORY so the append's open-for-write fails (O3).
    (store._root / "notes.yaml").mkdir()
    with pytest.raises(OSError):
        store.append(SPEC_ID, order=0, note_name="a", kind="freeform", body="1")


def test_no_seq_or_ref_anywhere_on_disk(store):
    store.append(SPEC_ID, order=0, note_name="a", kind="freeform", body="1")
    store.write_variant(SPEC_ID, "v0", {"ref": "v0", "spec": {}})
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    notes_text = store._notes_file().read_text(encoding="utf-8")
    log_text = (store._root / SPEC_ID / "experiment-log" / "0.yaml").read_text(
        encoding="utf-8")
    variant_text = (store._root / SPEC_ID / "variants" / "v0.yaml").read_text(
        encoding="utf-8")
    # D84-36: the _seq/_ref COUNTER fields are gone. The `variant_ref` attribute
    # (the variant identifier, D84-34) is a legit field - only the bookkeeping
    # fields (`_seq` / `_ref` as YAML KEYS) are banned.
    import yaml
    for text in (notes_text, log_text, variant_text):
        loaded = yaml.safe_load(text)
        keys = set(loaded.keys()) if isinstance(loaded, dict) else {
            k for r in loaded if isinstance(r, dict) for k in r}
        assert "_seq" not in keys and "_ref" not in keys


# --- the prompt-memory pattern (D84-27) ---------------------------------------

def test_memory_read_guidance_covers_both_bodies_and_typed_filters():
    from polymerhus.attack.hunting.pod.pod_memory import MEMORY_READ_GUIDANCE

    assert "note" in MEMORY_READ_GUIDANCE.lower()
    assert "experiment_summary" in MEMORY_READ_GUIDANCE
    assert "order" in MEMORY_READ_GUIDANCE
    assert "kind" in MEMORY_READ_GUIDANCE
    assert "classification" in MEMORY_READ_GUIDANCE
    assert "symptom_status" in MEMORY_READ_GUIDANCE
    assert "parent_key" in MEMORY_READ_GUIDANCE


def test_compose_memory_guidance_embeds_notes_and_log_identifiers(store):
    store.append(SPEC_ID, order=0, note_name="exhaustion", kind="kb_insight",
                 body="done")
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    guidance = compose_memory_guidance(store, SPEC_ID)
    assert f"{SPEC_ID}:0:exhaustion" in guidance
    assert f"{SPEC_ID}/0" in guidance            # the experiment-log identifier
    assert "experiment_summary" in guidance


def test_compose_memory_guidance_marks_an_empty_index(store):
    guidance = compose_memory_guidance(store, SPEC_ID)
    assert "no notes" in guidance.lower()


def test_compose_memory_guidance_is_fail_open_without_a_store():
    assert compose_memory_guidance(None, SPEC_ID) != ""
