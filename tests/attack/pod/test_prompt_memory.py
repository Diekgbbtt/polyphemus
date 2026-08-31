"""Unit tier: T7 (#157) - the prompt-memory pattern (D84-27).

`MEMORY_READ_GUIDANCE` (persistent SYSTEM block) + `compose_memory_guidance`
(the per-turn USER-side INDEXABLE key-list header) embed into the Runner's lap
opener and the Triager's delta. NO deterministic retrieval stage: the agent
indexes the key-list, then calls the `note` tool. The Triager's delta reads the
verbatim P3 consolidation note from the pod-owned store (D84-23), plus the
filtered triager context and variant_refs - no structured RunnerStep.
"""
from __future__ import annotations

import pytest

from polymerhus.attack.hunting.pod.context import (
    ExperimentLog,
    compose_runner_delta,
    compose_triager_delta,
)
from polymerhus.attack.hunting.pod.pod_memory import (
    PodMemoryStore,
    compose_memory_guidance,
    spec_identifier,
)
from polymerhus.attack.hunting.pod.types import RawObservation, VariantSpec

SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/", "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability",
}

_NOTE_BODY = "Symptom absent across the whole vector space; terminal KB query returned the identical primitive set - genuinely exhausted."


@pytest.fixture
def store(tmp_path):
    return PodMemoryStore(tmp_path)


@pytest.fixture
def spec_id():
    return spec_identifier("sqli", "blind")


@pytest.fixture
def log():
    log = ExperimentLog()
    log.record_variant(VariantSpec(ref="v0", spec=SPEC))
    log.record_variant(VariantSpec(ref="v1", parent_ref="v0", spec=SPEC))
    log.mark_executed("sig-1")
    return log


# --- the Runner's lap opener embeds the memory guidance ------------------------

def test_runner_delta_embeds_the_indexable_memory_guidance(log, store, spec_id):
    delta = compose_runner_delta(log, SPEC, feedback="decline the path into /api",
                                 iteration=2, budget=8, store=store, spec_id=spec_id)
    assert "Lap 2" in delta
    assert "decline the path into /api" in delta
    assert "sig-1" in delta
    # D84-27: the per-turn indexable key-list + reading guidance ride the opener.
    assert "indexable keys" in delta.lower()
    assert "experiment_summary" in delta


def test_runner_delta_lists_the_on_file_notes(log, store, spec_id):
    store.append(spec_id, order=1, note_name="capability", kind="kb_insight",
                 body="payload family X")
    delta = compose_runner_delta(log, SPEC, "", 1, 8, store=store, spec_id=spec_id)
    assert f"{spec_id}:1:capability" in delta


def test_runner_delta_is_fail_open_without_a_store(log, spec_id):
    delta = compose_runner_delta(log, SPEC, "", 1, 8, store=None, spec_id=spec_id)
    assert "Lap 1" in delta
    assert "indexable keys" in delta.lower()
    assert "no notes on file" in delta.lower()


# --- the Triager's delta: verbatim note + context + memory guidance ------------

def test_triager_delta_reads_the_verbatim_p3_note(log, store, spec_id):
    # D84-35: the summary is the TERMINAL RECORD of the variant's log slice,
    # so the delta's read resolves it from there (read_variant_summary).
    store.write_experiment_log(spec_id, 1, {"order": 1, "variant_ref": "v1",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    store.write_variant_summary(spec_id, 1, _NOTE_BODY)
    obs = RawObservation(status=404, body="not found")
    delta = compose_triager_delta(log, SPEC, obs, store=store, spec_id=spec_id, order=1)
    assert _NOTE_BODY in delta                          # verbatim, un-truncated
    assert "404" in delta                               # the filtered context
    assert "v0" in delta and "v1" in delta              # variant_refs for dedup
    assert "indexable keys" in delta.lower()            # the memory guidance
    assert "experiment_summary" in delta


def test_triager_delta_falls_back_when_no_consolidation_note_yet(log, store, spec_id):
    delta = compose_triager_delta(log, SPEC, None, store=store, spec_id=spec_id, order=0)
    assert "no consolidation note" in delta.lower()     # fail-open: no note yet
    assert "v0" in delta                                # the context still flows


def test_triager_delta_is_fail_open_without_a_store(log, spec_id):
    delta = compose_triager_delta(log, SPEC, None, store=None, spec_id=spec_id, order=0)
    assert "no consolidation note" in delta.lower()
    assert "variant" in delta.lower()
    assert "indexable keys" in delta.lower()


# --- the shared memory-guidance surface ----------------------------------------

def test_memory_guidance_is_the_indexable_list_plus_the_reading_contract(store, spec_id):
    store.append(spec_id, order=0, note_name="capability", kind="kb_insight",
                 body="x")
    guidance = compose_memory_guidance(store, spec_id)
    assert f"{spec_id}:0:capability" in guidance
    for token in ("parent_key", "key_keyword", "body_keyword", "experiment_summary",
                  "kb_insight", "freeform"):
        assert token in guidance


# --- the experiment-log identifiers (D84-27): the OTHER half of the index ------

def test_memory_guidance_renders_the_experiment_log_identifiers(store, spec_id):
    # T4/D84-27: the key-list covers BOTH the note keys AND the experiment-log
    # identifiers (spec id + the orders present on file), so the Runner/Triager
    # can index into any persisted experiment-log slice.
    store.write_experiment_log(spec_id, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    store.write_experiment_log(spec_id, 2, {"order": 2, "variant_ref": "v2",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    store.append(spec_id, order=0, note_name="capability", kind="kb_insight", body="x")
    guidance = compose_memory_guidance(store, spec_id)
    assert "# Experiment logs" in guidance          # the section renders
    assert f"{spec_id}/0" in guidance               # each order on file is listed
    assert f"{spec_id}/2" in guidance
    assert "# Notes" in guidance                    # the notes half still renders
    assert f"{spec_id}:0:capability" in guidance


def test_memory_guidance_renders_an_empty_experiment_logs_index_without_a_section(store, spec_id):
    # No orders on file: the # Experiment logs section is omitted entirely
    # (fail-open), while the notes index still renders.
    store.append(spec_id, order=0, note_name="capability", kind="kb_insight", body="x")
    guidance = compose_memory_guidance(store, spec_id)
    assert "# Experiment logs" not in guidance
    assert "# Notes" in guidance


def test_memory_guidance_documents_the_experiment_log_slice_read(store, spec_id):
    # T4: the reading guidance tells the agent it can read the experiment-log
    # slice body by its <spec_id>/<order> identifier, alongside the notes.
    guidance = compose_memory_guidance(store, spec_id)
    assert "experiment-log" in guidance
    assert "experiment_log" in guidance             # the slice read kind
    assert "experiment_summary" in guidance
    assert "order" in guidance