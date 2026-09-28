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


class _RecordingFileStore(FileStore):
    """A `FileStore` that records every write path, to prove the sink invariant."""

    def __init__(self) -> None:
        self.writes: list[Path] = []

    def write_text(self, path, text) -> None:  # type: ignore[override]
        self.writes.append(Path(path))
        super().write_text(path, text)

    def write_text_atomic(self, path, text) -> None:  # type: ignore[override]
        self.writes.append(Path(path))
        super().write_text_atomic(path, text)

    def write_bytes_atomic(self, path, data) -> None:  # type: ignore[override]
        self.writes.append(Path(path))
        super().write_bytes_atomic(path, data)


def _setup(store_dir: Path, *, instance_ids=("arm-a",)) -> object:
    from orchestrator.setup import EvalSetup

    instances = tuple(
        Instance(
            instance_id=iid,
            targets=(
                TargetRun(
                    target_id="jetlinks-1",
                    target_config=TargetConfig(
                        lifecycle="targetctl", params={"target": "jetlinks"}
                    ),
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


def test_materialize_is_idempotent_and_replaces_a_changed_copy(tmp_path) -> None:
    trial_dir, data_root = _make_trial(tmp_path)
    store_dir = tmp_path / "store"
    files = FileStore()
    cfg = data_root / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml"

    first = store.materialize(trial_dir, store=store_dir, data_root=data_root, files=files)
    cfg.write_text("config: edited\n", encoding="utf-8")
    second = store.materialize(trial_dir, store=store_dir, data_root=data_root, files=files)

    assert first == second
    copied = first / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml"
    assert copied.read_text(encoding="utf-8") == "config: edited\n"
    # No temp file survived the atomic replacement.
    assert sorted(p.name for p in copied.parent.iterdir()) == ["cfg.yaml"]


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


def test_render_lsyncd_config_rejects_a_source_outside_the_data_root(tmp_path) -> None:
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


def test_deploy_readme_documents_the_one_way_install() -> None:
    readme = Path(store.__file__).parent / "systemd" / "README.md"
    text = readme.read_text(encoding="utf-8")

    assert "render-sync" in text
    assert "lsyncd" in text
    assert "one-way" in text.lower()
