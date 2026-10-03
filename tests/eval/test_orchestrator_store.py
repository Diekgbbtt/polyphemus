"""The artifact store: one-way sync rendering and the self-contained trial tree (#273).

The store is a sink (D7/D12): lsyncd streams each instance data root into
`<store>/<instance>/live/`, and the materializer only ever reads the instance
data root and writes under the store. These tests cover the rendered one-way
config and unit, the per-trial materialization (verdicts, diagnoses, the
structure-preserving evidence copy), the post-copy resolution check, idempotent
re-materialization, the run manifest, and the structural guarantee that no
write escapes the store root.
"""
from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path

import pytest
import yaml

from orchestrator import store
from orchestrator.files import FileStore
from orchestrator.setup import Instance, TargetRun, TargetConfig

EVAL_SHA = "eval-sha-1"
FP = "fp-1"


# --- fixtures and helpers ------------------------------------------------------


def _record_payload(**overrides) -> dict:
    payload = {
        "trial_id": "trial-1",
        "instance_id": "arm-a",
        "target_id": "jetlinks-1",
        "project_id": "pid",
        "start_phase": "recon",
        "terminal": "complete",
        "phases": [
            {"phase": "recon", "entered": True, "status": "complete", "run_id": "recon-1"},
            {"phase": "hunting", "entered": True, "status": "complete", "run_id": "hunt-1"},
        ],
        "started_at": "2026-09-28T10:00:00+00:00",
        "finished_at": "2026-09-28T11:00:00+00:00",
        "eval_sha": EVAL_SHA,
        "stack_fingerprint": FP,
    }
    payload.update(overrides)
    return payload


def _verdict_row(vuln_id: str = "v1", identified: str = "identified") -> dict:
    return {
        "vuln_id": vuln_id,
        "identified": identified,
        "confidence": 0.9,
        "matched": {"unit": "u", "fault_class": "fc", "symptom": "s"},
        "evidence_chain": {
            "hunt_config": "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml",
            "spec_dir": "pid/hunting/hunter/test-specs/fault-a",
            "experiment_logs": [
                "pid/hunting/test-executor-pod/spec-1/experiment-log/order-0.yaml"
            ],
            "pod_export": "pid/hunting/test-executor-pod/spec-1/export.yaml",
        },
        "eval_sha": EVAL_SHA,
        "stack_fingerprint": FP,
    }


def _diagnosis_row(vuln_id: str = "v1") -> dict:
    return {
        "vuln": vuln_id,
        "failure_mode": "surface_gap",
        "root_cause": {
            "type": "implementation_defect",
            "combination_of": [],
            "extended_description": "d",
        },
        "diagnosis_overview": "o",
        "evidences": [{"source": "s", "ref": "r", "note": "n"}],
        "closest_issue": None,
        "proposed_issue": {"title": "gap", "body": "b", "labels": []},
        "eval_sha": EVAL_SHA,
        "stack_fingerprint": FP,
    }


def _make_data_root(root: Path) -> Path:
    """Populate a minimal instance data root matching the evidence chain paths."""
    (root / "pid/hunting/orchestration/hunt_configs/consumed").mkdir(parents=True)
    (root / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml").write_text(
        "config: cfg\n", encoding="utf-8"
    )
    (root / "pid/hunting/hunter/test-specs/fault-a").mkdir(parents=True)
    (root / "pid/hunting/hunter/test-specs/fault-a/spec.yaml").write_text(
        "spec: a\n", encoding="utf-8"
    )
    (root / "pid/hunting/test-executor-pod/spec-1/experiment-log").mkdir(parents=True)
    (root / "pid/hunting/test-executor-pod/spec-1/experiment-log/order-0.yaml").write_text(
        "order: 0\n", encoding="utf-8"
    )
    (root / "pid/hunting/test-executor-pod/spec-1/export.yaml").write_text(
        "export: 1\n", encoding="utf-8"
    )
    return root


def _make_trial(
    tmp_path: Path,
    *,
    rows: list[dict] | None = None,
    diagnoses: list[dict] | None = None,
    record: dict | None = None,
) -> tuple[Path, Path]:
    """A source trial dir plus the instance data root its verdicts reference."""
    data_root = _make_data_root(tmp_path / "data")
    trial_dir = tmp_path / "runs" / "jetlinks-1" / "trial-1"
    trial_dir.mkdir(parents=True)
    if rows is None:
        rows = [_verdict_row()]
    (trial_dir / "verdicts.yaml").write_text(
        yaml.safe_dump(rows, sort_keys=False), encoding="utf-8"
    )
    if diagnoses is not None:
        (trial_dir / "diagnoses.yaml").write_text(
            yaml.safe_dump(diagnoses, sort_keys=False), encoding="utf-8"
        )
    (trial_dir / "trial.yaml").write_text(
        yaml.safe_dump(record or _record_payload(), sort_keys=False), encoding="utf-8"
    )
    return trial_dir, data_root


GRAPH_JSON = {
    "project_id": "pid",
    "nodes": [{"id": "n1", "name": "a", "type": "L1Service", "properties": {}}],
    "links": [],
}


def _add_graph(
    trial_dir: Path,
    *,
    digest: str | None = None,
    captured_at: str = "2026-10-03T00:00:00+00:00",
) -> dict:
    """Write the captured graph beside `trial.yaml` and return its record metadata."""
    data = json.dumps(GRAPH_JSON).encode("utf-8")
    (trial_dir / "project-graph.json").write_bytes(data)
    return {
        "status": "available",
        "captured_at": captured_at,
        "sha256": digest if digest is not None else hashlib.sha256(data).hexdigest(),
        "node_count": len(GRAPH_JSON["nodes"]),
        "link_count": len(GRAPH_JSON["links"]),
        "failure": None,
    }


def _rewrite_record(trial_dir: Path, **overrides) -> dict:
    record = _record_payload(**overrides)
    (trial_dir / "trial.yaml").write_text(
        yaml.safe_dump(record, sort_keys=False), encoding="utf-8"
    )
    return record


def _add_skill(data_root: Path, name: str = "authn") -> Path:
    path = data_root / "pid" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# authn\n", encoding="utf-8")
    return path


def _staging_entries(store_dir: Path) -> list[Path]:
    staging = store_dir / "_staging"
    return sorted(staging.iterdir()) if staging.exists() else []


class _RecordingFileStore(FileStore):
    """A `FileStore` that records every write path, to prove the sink invariant.

    It also records the read-side primitives so the chain copy's use of the
    filesystem seam is provable.
    """

    def __init__(self) -> None:
        self.writes: list[Path] = []
        self.is_file_calls: list[Path] = []
        self.is_dir_calls: list[Path] = []

    def write_text(self, path, text) -> None:  # type: ignore[override]
        self.writes.append(Path(path))
        super().write_text(path, text)

    def write_text_atomic(self, path, text) -> None:  # type: ignore[override]
        self.writes.append(Path(path))
        super().write_text_atomic(path, text)

    def write_bytes_atomic(self, path, data) -> None:  # type: ignore[override]
        self.writes.append(Path(path))
        super().write_bytes_atomic(path, data)

    def is_file(self, path) -> bool:  # type: ignore[override]
        self.is_file_calls.append(Path(path))
        return super().is_file(path)

    def is_dir(self, path) -> bool:  # type: ignore[override]
        self.is_dir_calls.append(Path(path))
        return super().is_dir(path)


def _setup(store_dir: Path, *, instance_ids=("arm-a",)) -> object:
    from orchestrator.setup import EvalSetup

    instances = tuple(
        Instance(
            instance_id=iid,
            targets=(
                TargetRun(
                    target_key="webexploitbench/jetlinks", target_id="jetlinks-1"
                ),
            ),
        )
        for iid in instance_ids
    )
    return EvalSetup(schema_version=1, artifact_store=str(store_dir), instances=instances)


# --- layout -------------------------------------------------------------------


def test_layout_gives_the_live_mirror_and_the_per_trial_tree_distinct_paths(tmp_path) -> None:
    store_dir = tmp_path / "store"

    assert store.live_mirror_dir(store_dir, "arm-a") == store_dir / "arm-a" / "live"
    assert store.store_trial_dir(store_dir, "jetlinks-1", "arm-a", "trial-1") == (
        store_dir / "jetlinks-1" / "arm-a" / "trial-1"
    )


def test_instance_data_root_is_the_instance_worktree_data_dir(tmp_path) -> None:
    instances_root = tmp_path / "instances"

    assert store.instance_data_root(instances_root, "arm-a") == (
        instances_root / "arm-a" / "data"
    )


# --- sync rendering -----------------------------------------------------------


def test_lsyncd_config_streams_the_data_root_into_the_store_one_way(tmp_path) -> None:
    spec = store.SyncSpec(
        instance_id="arm-a",
        data_root=tmp_path / "instances" / "arm-a" / "data",
        store=tmp_path / "store",
    )

    config = store.render_lsyncd_config(spec)

    assert f'source = "{spec.data_root}/"' in config
    assert f'target = "{spec.live_dir}/"' in config
    # Strictly one-way: the store is never a source for a sync back.
    assert f'source = "{tmp_path / "store"}' not in config
    assert config.count("sync {") == 1
    assert "delete = false" in config
    assert "default.rsync" in config


def test_plan_sync_emits_one_config_and_unit_per_instance(tmp_path) -> None:
    setup = _setup(tmp_path / "store", instance_ids=("arm-a", "arm-b"))

    plan = store.plan_sync(
        setup,
        instances_root=tmp_path / "instances",
        out_dir=tmp_path / "store" / "_sync",
    )

    by_name = {file.path.name: file for file in plan.files}
    assert set(by_name) == {
        "eval-store-arm-a.conf",
        "eval-store-arm-b.conf",
        "eval-store-arm-a.service",
        "eval-store-arm-b.service",
    }
    # One sync block per config, each with its own data root.
    assert by_name["eval-store-arm-a.conf"].content.count("sync {") == 1
    assert "instances/arm-a/data" in by_name["eval-store-arm-a.conf"].content
    assert "arm-b/data" in by_name["eval-store-arm-b.conf"].content


def test_rendered_unit_invokes_lsyncd_on_the_instances_config(tmp_path) -> None:
    spec = store.SyncSpec(
        instance_id="arm-a",
        data_root=tmp_path / "instances" / "arm-a" / "data",
        store=tmp_path / "store",
    )

    unit = store.render_unit(spec)

    assert "ExecStart=" in unit
    assert "lsyncd" in unit
    assert str(spec.config_path(tmp_path / "store" / "_sync")) in unit
    assert "Restart=" in unit
    assert "one-way" in unit.lower()


def test_write_sync_materializes_the_rendered_files(tmp_path) -> None:
    setup = _setup(tmp_path / "store")
    files = FileStore()
    out_dir = tmp_path / "store" / "_sync"
    plan = store.plan_sync(setup, instances_root=tmp_path / "instances", out_dir=out_dir)

    written = store.write_sync(plan, files=files)

    assert {path.name for path in written} == {
        "eval-store-arm-a.conf",
        "eval-store-arm-a.service",
    }
    for path in written:
        assert path.exists()


# --- materialize --------------------------------------------------------------


def test_materialize_assembles_the_full_trial_tree(tmp_path) -> None:
    trial_dir, data_root = _make_trial(
        tmp_path,
        rows=[_verdict_row(identified="missed")],
        diagnoses=[
            {
                "vuln": "v1",
                "failure_mode": "surface_gap",
                "root_cause": {
                    "type": "implementation_defect",
                    "combination_of": [],
                    "extended_description": "d",
                },
                "diagnosis_overview": "o",
                "evidences": [{"source": "s", "ref": "r", "note": "n"}],
                "closest_issue": None,
                "proposed_issue": {"title": "gap", "body": "b", "labels": []},
                "eval_sha": EVAL_SHA,
                "stack_fingerprint": FP,
            }
        ],
    )
    store_dir = tmp_path / "store"

    dest = store.materialize(
        trial_dir, store=store_dir, data_root=data_root, files=FileStore()
    )

    assert dest == store_dir / "jetlinks-1" / "arm-a" / "trial-1"
    for name in (
        "verdicts.yaml",
        "diagnoses.yaml",
        "run-manifest.yaml",
        "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml",
        "pid/hunting/hunter/test-specs/fault-a/spec.yaml",
        "pid/hunting/test-executor-pod/spec-1/experiment-log/order-0.yaml",
        "pid/hunting/test-executor-pod/spec-1/export.yaml",
    ):
        assert (dest / name).exists(), name


def test_materialize_preserves_chain_structure_so_relative_paths_resolve(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    store_dir = tmp_path / "store"

    dest = store.materialize(
        trial_dir, store=store_dir, data_root=data_root, files=FileStore()
    )

    # The copied verdicts resolve against the trial dir itself (no live stack).
    from orchestrator import verdicts

    rows = verdicts.load_verdicts(
        dest / "verdicts.yaml",
        files=FileStore(),
        data_root=dest,
        eval_sha=EVAL_SHA,
        stack_fingerprint=FP,
    )
    assert rows[0].evidence_chain.hunt_config == (
        "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml"
    )


def test_materialize_surfaces_a_named_failure_for_a_missing_chain_file(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    (data_root / "pid/hunting/test-executor-pod/spec-1/export.yaml").unlink()

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir,
            store=tmp_path / "store",
            data_root=data_root,
            files=FileStore(),
        )

    assert excinfo.value.failure == "chain_unresolved"
    assert not (tmp_path / "store" / "jetlinks-1" / "arm-a" / "trial-1").exists()


def test_materialize_publishes_schema_v2_graph_and_artifacts(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    _add_skill(data_root)
    graph_meta = _add_graph(trial_dir)
    _rewrite_record(trial_dir, project_graph=graph_meta)

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
    )

    manifest = yaml.safe_load((dest / store.RUN_MANIFEST).read_text(encoding="utf-8"))
    assert store.STORE_SCHEMA_VERSION == 2
    assert manifest["schema_version"] == 2
    for section in ("project_snapshot", "project_artifacts", "project_graph"):
        assert manifest[section]["status"] == "available", section
        assert manifest[section]["project_id"] == "pid"
        assert manifest[section]["captured_at"] == graph_meta["captured_at"]
    assert (
        manifest["project_artifacts"]["snapshot_sha256"]
        == manifest["project_snapshot"]["snapshot_sha256"]
    )
    assert manifest["project_snapshot"]["snapshot_sha256"]
    assert manifest["project_graph"]["sha256"] == graph_meta["sha256"]
    assert manifest["project_graph"]["node_count"] == 1
    assert manifest["project_graph"]["link_count"] == 0
    # The manifest never carries a host path.
    assert str(tmp_path) not in yaml.safe_dump(manifest)

    entries = {
        entry["relative_path"]: entry
        for entry in manifest["project_artifacts"]["entries"]
    }
    assert "hunting/orchestration/hunt_configs/consumed/cfg.yaml" in entries
    assert "hunting/test-executor-pod/spec-1/export.yaml" in entries
    assert "hunting/test-executor-pod/spec-1/experiment-log/order-0.yaml" in entries
    assert "skills/authn/SKILL.md" in entries

    assert (dest / "project-graph.json").exists()
    assert (dest / "pid/skills/authn/SKILL.md").exists()
    assert (dest / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml").exists()


def test_auxiliary_failure_publishes_core_with_project_snapshot_unavailable(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
    )

    manifest = yaml.safe_load((dest / store.RUN_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    for section in ("project_snapshot", "project_artifacts", "project_graph"):
        assert manifest[section]["status"] == "unavailable", section
    assert manifest["project_snapshot"]["failure"] == "project_graph_unavailable"
    assert manifest["project_artifacts"]["failure"] == "project_graph_unavailable"
    assert manifest["project_graph"]["failure"] == "project_graph_unavailable"
    assert manifest["project_artifacts"]["entries"] == []
    assert not (dest / "project-graph.json").exists()
    # The validated core eval bundle is still published and readable.
    assert (dest / "verdicts.yaml").exists()
    assert (dest / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml").exists()


def test_equal_rematerialization_preserves_original_timestamps(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    store_dir = tmp_path / "store"
    files = FileStore()

    dest = store.materialize(trial_dir, store=store_dir, data_root=data_root, files=files)
    before_manifest = (dest / store.RUN_MANIFEST).read_text(encoding="utf-8")
    before_mtimes = {
        path.relative_to(dest).as_posix(): path.stat().st_mtime_ns
        for path in dest.rglob("*")
        if path.is_file()
    }

    second = store.materialize(trial_dir, store=store_dir, data_root=data_root, files=files)

    assert second == dest
    assert (dest / store.RUN_MANIFEST).read_text(encoding="utf-8") == before_manifest
    after_mtimes = {
        path.relative_to(dest).as_posix(): path.stat().st_mtime_ns
        for path in dest.rglob("*")
        if path.is_file()
    }
    assert after_mtimes == before_mtimes
    assert _staging_entries(store_dir) == []


def test_changed_rematerialization_refuses_snapshot_conflict(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    store_dir = tmp_path / "store"
    files = FileStore()
    cfg = data_root / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml"

    dest = store.materialize(trial_dir, store=store_dir, data_root=data_root, files=files)
    before_manifest = (dest / store.RUN_MANIFEST).read_text(encoding="utf-8")
    cfg.write_text("config: edited\n", encoding="utf-8")

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(trial_dir, store=store_dir, data_root=data_root, files=files)

    assert excinfo.value.failure == "snapshot_conflict"
    # The published tree is immutable: neither the manifest nor the copy changed.
    assert (dest / store.RUN_MANIFEST).read_text(encoding="utf-8") == before_manifest
    copied = dest / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml"
    assert copied.read_text(encoding="utf-8") == "config: cfg\n"
    assert _staging_entries(store_dir) == []


def test_core_failure_leaves_no_visible_trial_or_staging_tree(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    store_dir = tmp_path / "store"
    (data_root / "pid/hunting/test-executor-pod/spec-1/export.yaml").unlink()

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(trial_dir, store=store_dir, data_root=data_root, files=FileStore())

    assert excinfo.value.failure == "chain_unresolved"
    assert str(tmp_path) not in str(excinfo.value)
    assert not (store_dir / "jetlinks-1").exists()
    assert _staging_entries(store_dir) == []


def test_evidence_and_project_snapshot_copy_the_same_path_once(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    graph_meta = _add_graph(trial_dir)
    _rewrite_record(trial_dir, project_graph=graph_meta)
    files = _RecordingFileStore()

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=files
    )

    overlapping = dest / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml"
    assert overlapping.exists()
    # The staging write happens once even though the evidence chain and the
    # artifact inventory both cover this path (the final tree is one rename).
    staged_overlap = [
        path
        for path in files.writes
        if "_staging" in path.parts
        and path.as_posix().endswith(
            "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml"
        )
    ]
    assert len(staged_overlap) == 1
    # The shared path is still part of the published inventory.
    manifest = yaml.safe_load((dest / store.RUN_MANIFEST).read_text(encoding="utf-8"))
    paths = {entry["relative_path"] for entry in manifest["project_artifacts"]["entries"]}
    assert "hunting/orchestration/hunt_configs/consumed/cfg.yaml" in paths


def test_project_symlink_publishes_no_partial_auxiliary_snapshot(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    graph_meta = _add_graph(trial_dir)
    _rewrite_record(trial_dir, project_graph=graph_meta)
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    references = data_root / "pid/skills/authn/references"
    references.mkdir(parents=True)
    (references / "evil.md").symlink_to(outside)

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
    )

    manifest = yaml.safe_load((dest / store.RUN_MANIFEST).read_text(encoding="utf-8"))
    for section in ("project_snapshot", "project_artifacts", "project_graph"):
        assert manifest[section]["status"] == "unavailable", section
    assert manifest["project_snapshot"]["failure"] == "artifact_unsafe"
    assert manifest["project_artifacts"]["entries"] == []
    assert not (dest / "project-graph.json").exists()
    assert (dest / "verdicts.yaml").exists()


def test_graph_digest_mismatch_publishes_no_partial_auxiliary_snapshot(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    graph_meta = _add_graph(trial_dir, digest="0" * 64)
    _rewrite_record(trial_dir, project_graph=graph_meta)

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
    )

    manifest = yaml.safe_load((dest / store.RUN_MANIFEST).read_text(encoding="utf-8"))
    for section in ("project_snapshot", "project_artifacts", "project_graph"):
        assert manifest[section]["status"] == "unavailable", section
    assert manifest["project_snapshot"]["failure"] == "project_graph_invalid"
    assert manifest["project_artifacts"]["entries"] == []
    assert not (dest / "project-graph.json").exists()
    assert (dest / "verdicts.yaml").exists()


def test_run_manifest_carries_the_trial_pointers(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    store_dir = tmp_path / "store"

    dest = store.materialize(
        trial_dir,
        store=store_dir,
        data_root=data_root,
        files=FileStore(),
        now=lambda: "2026-09-28T12:00:00+00:00",
    )

    manifest = yaml.safe_load((dest / "run-manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == store.STORE_SCHEMA_VERSION
    assert manifest["trial_id"] == "trial-1"
    assert manifest["target_id"] == "jetlinks-1"
    assert manifest["target_run_id"] == "arm-a"
    assert manifest["instance_id"] == "arm-a"
    assert manifest["project_id"] == "pid"
    assert manifest["phases"][0]["run_id"] == "recon-1"
    assert manifest["phases"][1]["run_id"] == "hunt-1"
    assert manifest["eval_sha"] == EVAL_SHA
    assert manifest["stack_fingerprint"] == FP
    assert manifest["copied_at"] == "2026-09-28T12:00:00+00:00"
    assert "pid/hunting/hunter/test-specs/fault-a" in manifest["chain_sources"]


def test_run_manifest_carries_the_phase_stop_run_id(tmp_path) -> None:
    # The stop verb's run id differs from the phase's consumer id for analysis,
    # so the manifest must carry `stop_run_id` for a store reader to terminate.
    record = _record_payload(
        phases=[
            {
                "phase": "analysis",
                "entered": True,
                "status": "stopped",
                "run_id": "a1",
                "stop_run_id": "r0",
            }
        ]
    )
    trial_dir, data_root = _make_trial(tmp_path, record=record)

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
    )

    manifest = yaml.safe_load((dest / "run-manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["phases"][0]["stop_run_id"] == "r0"


def test_materialize_honours_an_explicit_target_run_id(tmp_path) -> None:
    trial_dir, data_root = _make_trial(
        tmp_path, record=_record_payload(target_run_id="runner-1")
    )

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
    )

    assert dest == tmp_path / "store" / "jetlinks-1" / "runner-1" / "trial-1"


def test_materialize_never_writes_outside_the_store_root(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    store_dir = tmp_path / "store"
    files = _RecordingFileStore()

    store.materialize(trial_dir, store=store_dir, data_root=data_root, files=files)

    assert files.writes, "materialize wrote nothing"
    for path in files.writes:
        assert store.is_within(store_dir, path), path


def test_materialize_chain_copy_routes_through_the_file_store_seam(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    files = _RecordingFileStore()

    store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=files
    )

    # Validate-then-copy classifies every source through the seam.
    assert files.is_file_calls
    assert files.is_dir_calls


def test_materialize_accepts_absent_diagnoses_when_nothing_is_diagnosable(tmp_path) -> None:
    trial_dir, data_root = _make_trial(
        tmp_path, rows=[_verdict_row(identified="identified")]
    )

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
    )

    assert (dest / "verdicts.yaml").exists()
    assert not (dest / "diagnoses.yaml").exists()
    manifest = yaml.safe_load((dest / "run-manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["diagnoses_present"] is False


def test_materialize_requires_diagnoses_when_a_verdict_is_diagnosable(tmp_path) -> None:
    trial_dir, data_root = _make_trial(
        tmp_path, rows=[_verdict_row(identified="missed")]
    )

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "diagnoses_missing"


def test_materialize_copies_a_present_diagnoses_file(tmp_path) -> None:
    trial_dir, data_root = _make_trial(
        tmp_path,
        rows=[_verdict_row(identified="missed")],
        diagnoses=[
            {
                "vuln": "v1",
                "failure_mode": "surface_gap",
                "root_cause": {
                    "type": "implementation_defect",
                    "combination_of": [],
                    "extended_description": "d",
                },
                "diagnosis_overview": "o",
                "evidences": [{"source": "s", "ref": "r", "note": "n"}],
                "closest_issue": None,
                "proposed_issue": {"title": "gap", "body": "b", "labels": []},
                "eval_sha": EVAL_SHA,
                "stack_fingerprint": FP,
            }
        ],
    )

    dest = store.materialize(
        trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
    )

    assert (dest / "diagnoses.yaml").exists()


def test_is_within_rejects_a_path_outside_the_root(tmp_path) -> None:
    root = tmp_path / "store"

    assert store.is_within(root, root / "a" / "b")
    assert not store.is_within(root, tmp_path / "elsewhere" / "b")


def test_render_lsyncd_config_sources_only_the_data_root(tmp_path) -> None:
    # The config is generated from the data root only; a store path can never
    # be smuggled in as the source.
    spec = store.SyncSpec(
        instance_id="arm-a", data_root=tmp_path / "d", store=tmp_path / "store"
    )
    config = store.render_lsyncd_config(spec)

    for line in config.splitlines():
        if line.strip().startswith("target ="):
            assert str(tmp_path / "store") in line
        if line.strip().startswith("source ="):
            assert str(tmp_path / "d") in line


def test_render_lsyncd_config_refuses_a_store_inside_the_data_root(tmp_path) -> None:
    spec = store.SyncSpec(
        instance_id="arm-a",
        data_root=tmp_path / "data",
        store=tmp_path / "data" / "store",
    )

    with pytest.raises(store.StoreError) as excinfo:
        store.render_lsyncd_config(spec)

    assert excinfo.value.failure == "sync_layout"


# --- named failure codes (#273 review) ----------------------------------------


def test_materialize_names_a_record_missing_failure(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    (trial_dir / "trial.yaml").unlink()

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "record_missing"


def test_materialize_names_a_record_invalid_failure(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    (trial_dir / "trial.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "record_invalid"


def test_materialize_names_a_verdicts_invalid_failure(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    (trial_dir / "verdicts.yaml").write_text("just: a mapping\n", encoding="utf-8")

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "verdicts_invalid"


def test_materialize_rejects_a_defective_diagnosis_before_the_copy(tmp_path) -> None:
    bad = _diagnosis_row()
    bad["failure_mode"] = "made_up"
    trial_dir, data_root = _make_trial(
        tmp_path,
        rows=[_verdict_row(identified="missed")],
        diagnoses=[bad],
    )

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "diagnoses_invalid"
    # It failed before landing anything in the authoritative tree.
    assert not (tmp_path / "store" / "jetlinks-1").exists()


def test_materialize_rejects_a_diagnosis_with_an_invented_identity(tmp_path) -> None:
    # Every diagnosis row must carry the trial record's SHAs, exactly like a
    # verdict row; an invented or missing one never lands in the store.
    invented = _diagnosis_row()
    invented["eval_sha"] = "invented-sha"
    trial_dir, data_root = _make_trial(
        tmp_path, rows=[_verdict_row(identified="missed")], diagnoses=[invented]
    )

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "diagnoses_invalid"
    assert "eval_sha" in str(excinfo.value)
    assert not (tmp_path / "store" / "jetlinks-1").exists()

    absent = _diagnosis_row()
    del absent["eval_sha"]
    (trial_dir / "diagnoses.yaml").write_text(
        yaml.safe_dump([absent], sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "diagnoses_invalid"


def test_materialize_rejects_an_unpaired_empty_diagnoses(tmp_path) -> None:
    trial_dir, data_root = _make_trial(
        tmp_path,
        rows=[_verdict_row(identified="missed")],
        diagnoses=[],
    )

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "diagnoses_invalid"
    # The missed verdict has no entry; nothing landed in the store.
    assert not (tmp_path / "store" / "jetlinks-1").exists()


def test_materialize_rejects_a_partially_paired_diagnoses(tmp_path) -> None:
    trial_dir, data_root = _make_trial(
        tmp_path,
        rows=[_verdict_row("v1", "missed"), _verdict_row("v2", "missed")],
        diagnoses=[_diagnosis_row("v1")],
    )

    with pytest.raises(store.StoreError) as excinfo:
        store.materialize(
            trial_dir, store=tmp_path / "store", data_root=data_root, files=FileStore()
        )

    assert excinfo.value.failure == "diagnoses_invalid"
    assert "v2" in str(excinfo.value)
    assert not (tmp_path / "store" / "jetlinks-1").exists()


def test_deploy_readme_documents_the_one_way_install() -> None:
    readme = Path(store.__file__).parent / "systemd" / "README.md"
    text = readme.read_text(encoding="utf-8")

    assert "render-sync" in text
    assert "lsyncd" in text
    assert "one-way" in text.lower()
