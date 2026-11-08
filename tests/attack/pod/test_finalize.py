"""Unit tier: the one PodExport finalizer.

The finalizer is the ONLY production writer of a PodExport. It assembles the
evidence from an in-memory ExperimentLog or from the durable pod store, returns
an existing export unchanged, and clears the resume cursor only after a durable
terminal exists.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.finalize import (
    PodTerminal,
    finalize_pod,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.pod.types import (
    Interpretation,
    RawObservation,
    VariantSpec,
)

SPEC_ID = "sqli__blind__boolean"
RUN = "run-finalize"


def _seed(store: PodMemoryStore) -> None:
    store.write_variant(
        SPEC_ID, "v0",
        {"ref": "v0", "parent_ref": None, "declined_attribute": "",
         "spec": {"rationale": "seeded"}},
    )
    store.write_experiment_log(SPEC_ID, 0, {
        "order": 0,
        "variant_ref": "v0",
        "raw_observations": [{
            "probe_ref": "sig-a", "variant_ref": "v0", "status": 200,
            "body": "observed",
        }],
        "kb_observations": [],
        "interpretations": [{
            "variant": "v0", "classification": "noise", "note": "seeded note",
        }],
        "executed": ["sig-a"],
    })
    store.write_resume(SPEC_ID, RUN, {
        "schema_version": 1,
        "last_order": 0,
        "current_variant_ref": "v0",
        "iteration": 2,
        "feedback": "",
        "executed": ["sig-a"],
    })


def test_a_harness_terminal_assembles_the_full_store_evidence(tmp_path):
    store = PodMemoryStore(tmp_path)
    _seed(store)

    envelope = finalize_pod(
        store=store,
        spec_id=SPEC_ID,
        run_id=RUN,
        terminal=PodTerminal.infrastructure(
            reason="node-timeout", error="runner_agent idle timeout"),
    )

    evidence = envelope["evidence"]
    assert envelope["verdict"] == "unsuccessful"
    assert evidence["terminal_reason"] == "node-timeout"
    assert evidence["clean"] is False
    assert evidence["iterations"] == 2
    assert evidence["variant_specs"][0]["ref"] == "v0"
    assert evidence["raw_observations"][0]["probe_ref"] == "sig-a"
    assert evidence["interpretations"][0]["note"] == "seeded note"
    assert store.read_resume(SPEC_ID, RUN) == {}


def test_the_in_memory_log_is_used_when_supplied(tmp_path):
    store = PodMemoryStore(tmp_path)
    log = ExperimentLog(store=store, spec_id=SPEC_ID)
    log.record_variant(VariantSpec(ref="v0", spec={"rationale": "memory"}))
    log.record_observation(RawObservation(
        probe_ref="sig-memory", variant_ref="v0", status=200))
    log.record_interpretation(Interpretation(
        variant="v0", classification="noise", note="memory note"))

    envelope = finalize_pod(
        store=store,
        spec_id=SPEC_ID,
        run_id=RUN,
        terminal=PodTerminal.infrastructure(reason="tool-timeout"),
        log=log,
    )

    evidence = envelope["evidence"]
    assert evidence["iterations"] == 1
    assert evidence["variant_specs"][0]["spec"]["rationale"] == "memory"
    assert evidence["raw_observations"][0]["probe_ref"] == "sig-memory"
    assert evidence["interpretations"][0]["note"] == "memory note"


def test_an_existing_export_wins_and_is_returned_unchanged(tmp_path):
    store = PodMemoryStore(tmp_path)
    _seed(store)
    existing = {
        "verdict": "successful",
        "evidence": {"terminal_reason": "symptom-confirmed", "clean": True},
    }
    store.write_pod_export(SPEC_ID, RUN, existing)

    envelope = finalize_pod(
        store=store,
        spec_id=SPEC_ID,
        run_id=RUN,
        terminal=PodTerminal.infrastructure(reason="pod-watchdog-timeout"),
    )

    assert envelope == existing
    assert store.read_resume(SPEC_ID, RUN) == {}


def test_the_finalizer_is_idempotent(tmp_path):
    store = PodMemoryStore(tmp_path)
    _seed(store)

    first = finalize_pod(
        store=store, spec_id=SPEC_ID, run_id=RUN,
        terminal=PodTerminal.infrastructure(
            reason="node-timeout", error="first"),
    )
    second = finalize_pod(
        store=store, spec_id=SPEC_ID, run_id=RUN,
        terminal=PodTerminal.infrastructure(
            reason="pod-watchdog-timeout", error="second"),
    )

    assert second == first
    assert store.read_pod_export(SPEC_ID, RUN) == first


def test_a_harness_reason_forces_a_clean_false_terminal(tmp_path):
    store = PodMemoryStore(tmp_path)
    _seed(store)

    envelope = finalize_pod(
        store=store, spec_id=SPEC_ID, run_id=RUN,
        terminal=PodTerminal(
            verdict="successful", reason="pod-watchdog-timeout",
            clean=True, iterations=9,
        ),
    )

    assert envelope["verdict"] == "unsuccessful"
    assert envelope["evidence"]["clean"] is False
    assert envelope["evidence"]["iterations"] == 9


def test_an_unknown_reason_is_refused(tmp_path):
    store = PodMemoryStore(tmp_path)

    with pytest.raises(ValueError, match="terminal reason"):
        finalize_pod(
            store=store, spec_id=SPEC_ID, run_id=RUN,
            terminal=PodTerminal(
                verdict="unsuccessful", reason="not-a-reason", clean=False),
        )


def test_a_storeless_terminal_returns_the_in_memory_envelope():
    envelope = finalize_pod(
        store=None, spec_id=SPEC_ID, run_id=RUN,
        terminal=PodTerminal.infrastructure(reason="pod-watchdog-timeout"),
    )

    assert envelope["verdict"] == "unsuccessful"
    assert envelope["evidence"]["terminal_reason"] == "pod-watchdog-timeout"
    assert envelope["evidence"]["variant_specs"] == []


def test_only_the_finalizer_writes_pod_exports():
    root = Path(__file__).resolve().parents[3] / "src/polymerhus"
    allowed = {"finalize.py", "pod_memory.py"}
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in allowed:
            continue
        if "write_pod_export" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_a_new_execution_terminal_replaces_the_prior_export(tmp_path):
    store = PodMemoryStore(tmp_path)
    _seed(store)
    store.write_pod_export(SPEC_ID, RUN, {
        "verdict": "successful",
        "evidence": {"terminal_reason": "symptom-confirmed", "clean": True},
    })

    envelope = finalize_pod(
        store=store, spec_id=SPEC_ID, run_id=RUN,
        terminal=PodTerminal.domain(
            verdict="unsuccessful", reason="no-symptom-evidence",
            clean=False, iterations=3),
        replace_existing=True,
    )

    assert envelope["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert envelope["evidence"]["clean"] is False
    assert store.read_pod_export(SPEC_ID, RUN) == envelope
