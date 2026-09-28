"""The evidence-chain resolver and its observability reasoning seam (#271).

The chain is resolved from the instance data root by identity: the parent hunt
config, the child `TestImplementationSpec` directory, the child experiment logs,
and the yielded `PodExport`. Every unresolved required element is a named
validation error - a positive verdict with no auditable chain is refused. The
optional Langfuse seam is injected and read-only; absent one, the reasoning
refs stay empty.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator import evidence
from orchestrator.files import (
    FileStore,
    hunt_configs_dir,
    hunter_test_specs_dir,
    pod_experiment_logs_dir,
    pod_spec_dir,
)


class SeamFileStore(FileStore):
    """Records the read primitives the resolver must route through the seam."""

    def __init__(self) -> None:
        self.is_dir_calls: list[Path] = []
        self.glob_calls: list[tuple[Path, str]] = []

    def is_dir(self, path) -> bool:  # type: ignore[override]
        self.is_dir_calls.append(Path(path))
        return super().is_dir(path)

    def glob(self, directory, pattern) -> list[Path]:  # type: ignore[override]
        self.glob_calls.append((Path(directory), pattern))
        return super().glob(directory, pattern)


def seed_chain(tmp_path, files: FileStore, *, project: str = "pid"):
    """Create a full, resolvable chain under `tmp_path/data`; return the root."""
    root = tmp_path / "data"
    files.write_text(
        hunt_configs_dir(root, project, "produced") / "unit_CWE-89_sqli.yaml",
        "id: unit_CWE-89_sqli\n",
    )
    spec_dir = hunter_test_specs_dir(root, project) / "unit_CWE-89_sqli"
    files.write_text(spec_dir / "produced" / "sqli_error.yaml", "id: sqli_error\n")
    logs = pod_experiment_logs_dir(root, project, "sqli_error")
    files.write_text(logs / "0.yaml", "order: 0\n")
    files.write_text(logs / "1.yaml", "order: 1\n")
    pod = pod_spec_dir(root, project, "sqli_error")
    files.write_text(pod / "run1.yaml", "verdict: successful\n")
    return root


def _target(**overrides) -> evidence.EvidenceTarget:
    base = dict(
        project_id="pid",
        hunt_config="unit_CWE-89_sqli",
        fault_key="unit_CWE-89_sqli",
        spec_id="sqli_error",
        pod_export="run1",
    )
    base.update(overrides)
    return evidence.EvidenceTarget(**base)


# --- resolution ----------------------------------------------------------------


def test_resolves_every_chain_element_relative_to_the_data_root(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)

    chain = evidence.resolve_evidence(root, _target(), files=files)

    assert chain.hunt_config == (
        "pid/hunting/orchestration/hunt_configs/produced/unit_CWE-89_sqli.yaml"
    )
    assert chain.spec_dir == "pid/hunting/hunter/test-specs/unit_CWE-89_sqli"
    assert chain.experiment_logs == (
        "pid/hunting/test-executor-pod/sqli_error/experiment-log/0.yaml",
        "pid/hunting/test-executor-pod/sqli_error/experiment-log/1.yaml",
    )
    assert chain.pod_export == "pid/hunting/test-executor-pod/sqli_error/run1.yaml"
    assert chain.reasoning == ()
    # The resolved paths validate against the same root.
    evidence.validate_evidence(chain, root, files=files)


def test_hunt_config_resolves_from_the_consumed_side(tmp_path) -> None:
    files = FileStore()
    root = tmp_path / "data"
    files.write_text(
        hunt_configs_dir(root, "pid", "consumed") / "unit_CWE-89_sqli.yaml",
        "id: unit_CWE-89_sqli\n",
    )
    spec_dir = hunter_test_specs_dir(root, "pid") / "unit_CWE-89_sqli"
    files.write_text(spec_dir / "produced" / "sqli_error.yaml", "id: s\n")
    files.write_text(pod_experiment_logs_dir(root, "pid", "sqli_error") / "0.yaml", "o: 0\n")
    files.write_text(pod_spec_dir(root, "pid", "sqli_error") / "run1.yaml", "v: s\n")

    chain = evidence.resolve_evidence(root, _target(), files=files)

    assert chain.hunt_config == (
        "pid/hunting/orchestration/hunt_configs/consumed/unit_CWE-89_sqli.yaml"
    )


def test_missing_hunt_config_is_a_validation_error(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)
    # Remove the hunt config from the produced side.
    (
        root / "pid/hunting/orchestration/hunt_configs/produced/unit_CWE-89_sqli.yaml"
    ).unlink()

    with pytest.raises(evidence.EvidenceError, match="hunt_config"):
        evidence.resolve_evidence(root, _target(), files=files)


def test_missing_spec_dir_is_a_validation_error(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)

    with pytest.raises(evidence.EvidenceError, match="spec_dir"):
        evidence.resolve_evidence(root, _target(fault_key="unit_CWE-999_nope"), files=files)


def test_require_dir_rejects_a_file_where_a_directory_is_required(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)
    # A regular file sitting where the fault-key family directory belongs.
    spec_root = hunter_test_specs_dir(root, "pid")
    (spec_root / "unit_CWE-1_x").write_text("not a dir\n", encoding="utf-8")

    with pytest.raises(evidence.EvidenceError, match="directory"):
        evidence.resolve_evidence(root, _target(fault_key="unit_CWE-1_x"), files=files)


def test_resolve_evidence_routes_reads_through_the_file_store_seam(tmp_path) -> None:
    files = SeamFileStore()
    root = seed_chain(tmp_path, files)

    evidence.resolve_evidence(root, _target(), files=files)

    # The hunt-config lookup and the spec-dir guard both went through the seam.
    assert files.glob_calls
    assert files.is_dir_calls


def test_missing_experiment_logs_are_a_validation_error(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)

    with pytest.raises(evidence.EvidenceError, match="experiment"):
        evidence.resolve_evidence(root, _target(spec_id="unknown_spec"), files=files)


def test_missing_pod_export_is_a_validation_error(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)

    with pytest.raises(evidence.EvidenceError, match="pod_export"):
        evidence.resolve_evidence(root, _target(pod_export="nope"), files=files)


def test_pod_export_is_discovered_when_not_named(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)

    chain = evidence.resolve_evidence(root, _target(pod_export=None), files=files)

    assert chain.pod_export.endswith("sqli_error/run1.yaml")


def test_ambiguous_pod_export_is_a_validation_error(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)
    files.write_text(
        pod_spec_dir(root, "pid", "sqli_error") / "run2.yaml", "verdict: unsuccessful\n"
    )

    with pytest.raises(evidence.EvidenceError, match="ambiguous"):
        evidence.resolve_evidence(root, _target(pod_export=None), files=files)


# --- validation ----------------------------------------------------------------


def test_validate_rejects_a_missing_chain_file(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)
    chain = evidence.resolve_evidence(root, _target(), files=files)
    (
        root / "pid/hunting/test-executor-pod/sqli_error/run1.yaml"
    ).unlink()

    with pytest.raises(evidence.EvidenceError, match="pod_export"):
        evidence.validate_evidence(chain, root, files=files)


def test_validate_rejects_an_absolute_or_traversing_path(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)
    chain = evidence.EvidenceChain(
        hunt_config="/etc/passwd",
        spec_dir="pid/../outside",
        experiment_logs=("pid/x.yaml",),
        pod_export="pid/y.yaml",
    )

    with pytest.raises(evidence.EvidenceError):
        evidence.validate_evidence(chain, root, files=files)


# --- the observability reasoning seam ------------------------------------------


def test_reasoning_refs_are_mapped_and_ordered_by_workflow_phase(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)
    observations = [
        {"phase": "hunting", "decision_node": "d3", "rationale": "r3", "observation_ref": "o3"},
        {"phase": "recon", "decision_node": "d1", "rationale": "r1", "observation_ref": "o1"},
        {"phase": "analysis", "decision_node": "d2", "rationale": "r2", "observation_ref": "o2"},
    ]
    seen = {}

    def source(trace_id: str):
        seen["trace"] = trace_id
        return observations

    chain = evidence.resolve_evidence(
        root, _target(trace_id="trace-1"), files=files, reasoning_source=source
    )

    assert seen["trace"] == "trace-1"
    assert [r.phase for r in chain.reasoning] == ["recon", "analysis", "hunting"]
    assert chain.reasoning[0].decision_node == "d1"
    assert chain.reasoning[0].observation_ref == "o1"


def test_reasoning_is_empty_without_a_source(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)

    chain = evidence.resolve_evidence(root, _target(trace_id="t"), files=files)

    assert chain.reasoning == ()


def test_reasoning_is_empty_without_a_trace_id(tmp_path) -> None:
    files = FileStore()
    root = seed_chain(tmp_path, files)

    def source(trace_id: str):  # pragma: no cover - must not be called
        raise AssertionError("the source must not be read without a trace id")

    chain = evidence.resolve_evidence(root, _target(), files=files, reasoning_source=source)

    assert chain.reasoning == ()


def test_map_reasoning_rejects_an_unknown_phase() -> None:
    with pytest.raises(evidence.EvidenceError, match="phase"):
        evidence.map_reasoning(
            [{"phase": "nope", "decision_node": "d", "rationale": "r", "observation_ref": "o"}]
        )


def test_map_reasoning_rejects_a_missing_field() -> None:
    with pytest.raises(evidence.EvidenceError, match="decision_node"):
        evidence.map_reasoning(
            [{"phase": "recon", "rationale": "r", "observation_ref": "o"}]
        )
