"""Resolved Hunting/Skill artifacts across schema v1 and v2 (unified workspace).

The resolved artifact layer must pick the immutable schema-v2 capture when it
exists, otherwise safely fall back to the matching instance's raw project
directory, and never trust a client path. These tests exercise the resolver
directly (no HTTP), pinning the source contract, the fallback reasons, and the
path-safe failures.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from orchestrator import project_artifacts as artifact_catalog
from orchestrator import project_graph as artifact_graph
from orchestrator import store as artifact_store
from orchestrator.files import FileStore
from read_api import artifacts as artifact_reader
from read_api import resolved_artifacts as resolved
from read_api.resolved import TrialContext

TARGET = "comfyui-1"
RUN = "run-a"
TRIAL = "t1"
PROJECT_ID = "c0641257-a1a9-4e13-acee-6effa28311f5"
INSTANCE = "eval-server-1"
CAPTURED_AT = "2024-01-01T00:00:00+00:00"
COPIED_AT = "2024-01-01T00:00:00+00:00"

HUNTING_FILES = {
    "hunting/orchestration/hunt_configs/produced/prod.yaml": b"kind: hunt-config\n",
    "hunting/orchestration/hunt_configs/consumed/cons.yaml": b"kind: hunt-config\n",
    "hunting/test-executor-pod/spec-1/variants/variant.yaml": b"kind: pod-variant\n",
    "hunting/test-executor-pod/spec-1/export.yaml": b"kind: pod-export\n",
}
SKILL_FILES = {
    "skills/authn/SKILL.md": b"# Authn skill\n",
    "skills/authn/scripts/run.sh": b"echo run\n",
}


def _context(
    *,
    project_id: str | None = PROJECT_ID,
    instance_id: str | None = INSTANCE,
    eligible: bool = True,
) -> TrialContext:
    return TrialContext(
        target_id=TARGET,
        target_run_id=RUN,
        trial_id=TRIAL,
        project_id=project_id,
        instance_id=instance_id,
        fallback_eligible=eligible,
    )


def _write_raw(data_root: Path, files: dict[str, bytes]) -> Path:
    project_root = data_root / PROJECT_ID
    for relative, data in files.items():
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return project_root


def _write_v1_trial(store: Path) -> Path:
    trial_dir = store / TARGET / RUN / TRIAL
    trial_dir.mkdir(parents=True)
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "trial_id": TRIAL,
                "target_id": TARGET,
                "target_run_id": RUN,
                "instance_id": INSTANCE,
                "project_id": PROJECT_ID,
            }
        ),
        encoding="utf-8",
    )
    return trial_dir


def _write_v2_trial(store: Path, project_files: dict[str, bytes]) -> Path:
    """A schema-v2 Trial whose captured inventory is built by the real helpers."""
    trial_dir = store / TARGET / RUN / TRIAL
    project_root = trial_dir / PROJECT_ID
    for relative, data in project_files.items():
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    files = FileStore()
    artifacts = artifact_catalog.collect_project_artifacts(
        trial_dir, PROJECT_ID, files=files
    )
    capture = artifact_graph.capture_project_graph(
        {"project_id": PROJECT_ID, "nodes": [], "links": []},
        project_id=PROJECT_ID,
        captured_at=CAPTURED_AT,
        destination=trial_dir / artifact_graph.PROJECT_GRAPH_FILENAME,
        files=files,
    )
    snapshot = artifact_store.ProjectSnapshot(
        available=True,
        project_id=PROJECT_ID,
        captured_at=CAPTURED_AT,
        graph_sha256=capture.sha256,
        graph_node_count=0,
        graph_link_count=0,
        artifacts=artifacts,
    )
    manifest = artifact_store.build_run_manifest(
        {
            "trial_id": TRIAL,
            "target_id": TARGET,
            "target_run_id": RUN,
            "instance_id": INSTANCE,
            "project_id": PROJECT_ID,
            "start_phase": "hunting",
            "terminal": "complete",
            "phases": [],
            "eval_sha": "eval-1",
            "stack_fingerprint": "fp-1",
        },
        [],
        COPIED_AT,
        diagnoses_present=False,
        project_snapshot=snapshot,
    )
    fingerprint = artifact_store._snapshot_sha256(trial_dir, manifest, files)
    manifest["project_snapshot"]["snapshot_sha256"] = fingerprint
    manifest["project_artifacts"]["snapshot_sha256"] = fingerprint
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return trial_dir


def _paths(inventory: resolved.ResolvedInventory) -> set[str]:
    return {entry["relative_path"] for entry in inventory.entries}


# --- source selection -----------------------------------------------------------


def test_captured_v2_inventory_wins_over_different_raw_files(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v2_trial(store, HUNTING_FILES)
    data_root = tmp_path / "raw"
    _write_raw(data_root, {"hunting/orchestration/hunt_configs/produced/other.yaml": b"x\n"})

    inventory = resolved.resolve_inventory(
        store, data_root, _context(), files=FileStore()
    )
    assert inventory.status == "available"
    assert inventory.source == resolved.TRIAL_SNAPSHOT
    assert inventory.fallback_reason is None
    assert "hunting/orchestration/hunt_configs/produced/other.yaml" not in _paths(inventory)
    assert "hunting/orchestration/hunt_configs/produced/prod.yaml" in _paths(inventory)


def test_v1_matching_instance_collects_raw_hunting_and_skills(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    data_root = tmp_path / "raw"
    _write_raw(data_root, {**HUNTING_FILES, **SKILL_FILES})

    inventory = resolved.resolve_inventory(
        store, data_root, _context(), files=FileStore()
    )
    assert inventory.status == "available"
    assert inventory.source == resolved.PROJECT_STORAGE
    assert inventory.project_id == PROJECT_ID
    assert _paths(inventory) == set(HUNTING_FILES) | set(SKILL_FILES)

    body = resolved.inventory_response(inventory, TARGET, RUN, TRIAL)
    assert body["source"] == "project_storage"
    assert body["fallback_reason"] == "project_artifacts_unavailable"
    assert body["status"] == "available"


@pytest.mark.parametrize(
    "context",
    [
        _context(instance_id="other", eligible=False),
        _context(project_id=None, eligible=False),
    ],
)
def test_v1_ineligible_context_does_not_read_raw(
    tmp_path: Path, context: TrialContext
) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    data_root = tmp_path / "raw"
    _write_raw(data_root, HUNTING_FILES)

    seen: list[str] = []

    class _Spy(FileStore):
        def exists(self, path):  # type: ignore[override]
            seen.append(str(path))
            return super().exists(path)

    inventory = resolved.resolve_inventory(store, data_root, context, files=_Spy())
    assert inventory.status == "unavailable"
    assert inventory.source == resolved.PROJECT_STORAGE
    assert inventory.entries == ()
    assert seen == []


def test_incoherent_v2_capture_falls_back_with_stable_reason(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _write_v2_trial(store, HUNTING_FILES)
    manifest_path = trial_dir / "run-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["project_artifacts"]["snapshot_sha256"] = "different-fingerprint"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    data_root = tmp_path / "raw"
    _write_raw(data_root, SKILL_FILES)

    inventory = resolved.resolve_inventory(
        store, data_root, _context(), files=FileStore()
    )
    assert inventory.source == resolved.PROJECT_STORAGE
    assert inventory.fallback_reason == "project_snapshot_unavailable"
    assert _paths(inventory) == set(SKILL_FILES)


def test_two_trials_sharing_a_project_share_project_storage(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    data_root = tmp_path / "raw"
    _write_raw(data_root, HUNTING_FILES)

    first = resolved.resolve_inventory(store, data_root, _context(), files=FileStore())
    second = resolved.resolve_inventory(
        store, data_root, _context(project_id=PROJECT_ID), files=FileStore()
    )
    assert first.source == second.source == resolved.PROJECT_STORAGE
    assert _paths(first) == _paths(second)
    assert (
        resolved.inventory_response(first, TARGET, RUN, TRIAL)["source"]
        == resolved.inventory_response(second, TARGET, RUN, "t2")["source"]
    )


def test_missing_raw_project_directory_is_available_and_empty(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    data_root = tmp_path / "raw"
    data_root.mkdir()

    inventory = resolved.resolve_inventory(
        store, data_root, _context(), files=FileStore()
    )
    assert inventory.status == "available"
    assert inventory.source == resolved.PROJECT_STORAGE
    body = resolved.inventory_response(inventory, TARGET, RUN, TRIAL)
    assert body["groups"] == []


def test_unconfigured_raw_root_is_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())
    assert inventory.status == "unavailable"
    assert inventory.reason == "project_data_unavailable"


def test_symlinked_raw_project_is_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    data_root = tmp_path / "raw"
    data_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (data_root / PROJECT_ID).symlink_to(outside, target_is_directory=True)

    inventory = resolved.resolve_inventory(
        store, data_root, _context(), files=FileStore()
    )
    assert inventory.status == "unavailable"
    assert inventory.reason == "artifact_unsafe"


# --- detail and content ---------------------------------------------------------


def _raw_inventory(tmp_path: Path) -> resolved.ResolvedInventory:
    store = tmp_path / "store"
    _write_v1_trial(store)
    data_root = tmp_path / "raw"
    _write_raw(data_root, {**HUNTING_FILES, **SKILL_FILES})
    return resolved.resolve_inventory(store, data_root, _context(), files=FileStore())


def test_detail_binds_the_content_url_to_the_entry_digest(tmp_path: Path) -> None:
    inventory = _raw_inventory(tmp_path)
    entry = next(
        e for e in inventory.entries if e["relative_path"].endswith("prod.yaml")
    )
    body = resolved.detail_response(inventory, TARGET, RUN, TRIAL, entry["artifact_id"])
    assert body["entry"] == entry
    assert f"expected_sha256={entry['sha256']}" in body["content_url"]
    assert "/resolved-artifacts/" in body["content_url"]


def test_detail_of_unknown_artifact_is_not_found(tmp_path: Path) -> None:
    inventory = _raw_inventory(tmp_path)
    with pytest.raises(artifact_reader.ArtifactLookupError) as excinfo:
        resolved.detail_response(inventory, TARGET, RUN, TRIAL, "not-an-id")
    assert excinfo.value.code == "artifact_not_found"
    assert excinfo.value.status_code == 404


def test_digest_change_between_detail_and_content_is_rejected(tmp_path: Path) -> None:
    inventory = _raw_inventory(tmp_path)
    entry = next(
        e for e in inventory.entries if e["relative_path"].endswith("prod.yaml")
    )
    download = resolved.content_download(
        inventory, entry["artifact_id"], entry["sha256"]
    )
    assert b"".join(download.chunks) == HUNTING_FILES[entry["relative_path"]]

    with pytest.raises(artifact_reader.ArtifactLookupError) as excinfo:
        resolved.content_download(inventory, entry["artifact_id"], "deadbeef")
    assert excinfo.value.code == "artifact_digest_mismatch"
    assert excinfo.value.status_code == 409


def test_disappearing_raw_file_is_a_safe_coded_failure(tmp_path: Path) -> None:
    inventory = _raw_inventory(tmp_path)
    entry = next(
        e for e in inventory.entries if e["relative_path"].endswith("prod.yaml")
    )
    (inventory.root / entry["relative_path"]).unlink()
    with pytest.raises(artifact_reader.ArtifactLookupError) as excinfo:
        resolved.content_download(inventory, entry["artifact_id"], entry["sha256"])
    assert excinfo.value.code == "artifact_missing"
    assert "/" not in str(excinfo.value)


def test_unavailable_inventory_detail_is_coded_not_a_path(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())
    with pytest.raises(artifact_reader.ArtifactLookupError) as excinfo:
        resolved.detail_response(inventory, TARGET, RUN, TRIAL, "whatever")
    assert excinfo.value.code == "project_data_unavailable"
    assert "/" not in str(excinfo.value)


def test_inventory_and_detail_never_serialize_a_host_path(tmp_path: Path) -> None:
    inventory = _raw_inventory(tmp_path)
    body = resolved.inventory_response(inventory, TARGET, RUN, TRIAL)
    assert str(tmp_path) not in repr(body)


# --- nested HuntConfigs through the resolved layer ------------------------------

NESTED_HUNTING_FILES = {
    "hunting/orchestration/hunt_configs/produced/read/save URL.yaml": b"kind: hunt-config\nside: produced\n",
    "hunting/orchestration/hunt_configs/produced/role/permission assignment.yaml": b"kind: hunt-config\nside: produced\n",
    "hunting/orchestration/hunt_configs/consumed/sign/template label.yaml": b"kind: hunt-config\nside: consumed\n",
}


def _nested_raw_inventory(tmp_path: Path) -> resolved.ResolvedInventory:
    store = tmp_path / "store"
    _write_v1_trial(store)  # capture unavailable -> raw project storage
    data_root = tmp_path / "raw"
    _write_raw(data_root, {**NESTED_HUNTING_FILES, **SKILL_FILES})
    return resolved.resolve_inventory(store, data_root, _context(), files=FileStore())


def test_raw_fallback_exposes_nested_hunt_configs_verbatim(tmp_path: Path) -> None:
    inventory = _nested_raw_inventory(tmp_path)

    assert inventory.status == "available"
    assert inventory.source == resolved.PROJECT_STORAGE
    assert set(NESTED_HUNTING_FILES) <= _paths(inventory)
    by_path = {entry["relative_path"]: entry for entry in inventory.entries}
    for path, data in NESTED_HUNTING_FILES.items():
        entry = by_path[path]
        assert entry["kind"] == "hunt_config"
        assert entry["representation"] == "yaml"
        assert entry["artifact_id"] == hashlib.sha256(path.encode()).hexdigest()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()

    body = resolved.inventory_response(inventory, TARGET, RUN, TRIAL)
    hunt_configs = {group["key"]: group for group in body["groups"]}["hunt-configs"]
    assert {child["key"] for child in hunt_configs["children"]} == {
        "hunt-configs/produced",
        "hunt-configs/consumed",
    }


def test_nested_hunt_configs_for_a_trial_with_no_store_capture(tmp_path: Path) -> None:
    # A Trial with no store tree at all: the resolved layer reads raw directly.
    store = tmp_path / "store"
    data_root = tmp_path / "raw"
    _write_raw(data_root, NESTED_HUNTING_FILES)

    inventory = resolved.resolve_inventory(
        store, data_root, _context(), files=FileStore()
    )

    assert inventory.status == "available"
    assert inventory.source == resolved.PROJECT_STORAGE
    assert set(NESTED_HUNTING_FILES) <= _paths(inventory)


def test_nested_detail_and_content_round_trip(tmp_path: Path) -> None:
    inventory = _nested_raw_inventory(tmp_path)
    entry = next(
        e for e in inventory.entries if e["relative_path"].endswith("read/save URL.yaml")
    )

    detail = resolved.detail_response(inventory, TARGET, RUN, TRIAL, entry["artifact_id"])
    assert detail["entry"] == entry
    assert f"expected_sha256={entry['sha256']}" in detail["content_url"]

    download = resolved.content_download(
        inventory, entry["artifact_id"], entry["sha256"]
    )
    assert b"".join(download.chunks) == NESTED_HUNTING_FILES[entry["relative_path"]]


def test_nested_wrong_expected_digest_is_409(tmp_path: Path) -> None:
    inventory = _nested_raw_inventory(tmp_path)
    entry = next(
        e for e in inventory.entries if e["relative_path"].endswith("read/save URL.yaml")
    )

    with pytest.raises(artifact_reader.ArtifactLookupError) as excinfo:
        resolved.content_download(inventory, entry["artifact_id"], "deadbeef")

    assert excinfo.value.code == "artifact_digest_mismatch"
    assert excinfo.value.status_code == 409


def test_captured_v2_inventory_includes_nested_hunt_configs(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v2_trial(store, {**HUNTING_FILES, **NESTED_HUNTING_FILES})

    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())

    assert inventory.source == resolved.TRIAL_SNAPSHOT
    assert set(NESTED_HUNTING_FILES) <= _paths(inventory)


def test_raw_fallback_rejects_a_nested_symlinked_dir(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    data_root = tmp_path / "raw"
    project_root = _write_raw(data_root, NESTED_HUNTING_FILES)
    (tmp_path / "outside").mkdir()
    (
        project_root / "hunting/orchestration/hunt_configs/produced/linked"
    ).symlink_to(tmp_path / "outside", target_is_directory=True)

    inventory = resolved.resolve_inventory(
        store, data_root, _context(), files=FileStore()
    )

    assert inventory.status == "unavailable"
    assert inventory.reason == "artifact_unsafe"
    assert str(tmp_path) not in repr(inventory)


# --- v1 store: saved artifacts with no v2 snapshot and no raw project ----------

# What the producer really copies into a v1 Trial tree, at data-root-relative
# paths (project-prefixed): the hunt_config file, the spec_dir *directory*'s
# children, the experiment logs, the pod export and a skill bundle.
V1_CHAIN_FILES = {
    "hunting/orchestration/hunt_configs/consumed/hunt.yaml": b"kind: hunt-config\n",
    "hunting/hunter/test-specs/fault-a/produced/spec-1.yaml": b"kind: test-spec\n",
    "hunting/hunter/test-specs/fault-a/produced/spec-2.yaml": b"kind: test-spec\n",
    "hunting/test-executor-pod/spec-1/experiment-log/0.yaml": b"kind: experiment-log\n",
    "hunting/test-executor-pod/spec-1/export.yaml": b"kind: pod-export\n",
    "skills/authn/SKILL.md": b"# Authn skill\n",
}


def _v1_manifest(project_id: str = PROJECT_ID) -> dict:
    return {
        "schema_version": 1,
        "trial_id": TRIAL,
        "target_id": TARGET,
        "target_run_id": RUN,
        "instance_id": INSTANCE,
        "project_id": project_id,
        "chain_sources": [],
        "diagnoses_present": False,
    }


def _write_v1_store(
    store: Path,
    project_files: dict[str, bytes],
    *,
    manifest: dict | None = None,
) -> Path:
    """A v1 Trial tree: the manifest plus the copied `<project_id>/...` subtree."""
    trial_dir = store / TARGET / RUN / TRIAL
    trial_dir.mkdir(parents=True, exist_ok=True)
    project_id = (manifest or _v1_manifest()).get("project_id", PROJECT_ID)
    for relative, data in project_files.items():
        path = trial_dir / project_id / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(manifest or _v1_manifest(), sort_keys=False), encoding="utf-8"
    )
    return trial_dir


def test_v1_store_without_raw_exposes_saved_artifacts(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_store(store, V1_CHAIN_FILES)

    # Another instance and no raw root: the Trial's own saved evidence still reads.
    inventory = resolved.resolve_inventory(
        store, None, _context(instance_id="other-instance", eligible=False), files=FileStore()
    )

    assert inventory.status == "available"
    assert inventory.source == resolved.TRIAL_SNAPSHOT
    assert inventory.project_id == PROJECT_ID
    assert _paths(inventory) == set(V1_CHAIN_FILES)
    assert {entry["origin"] for entry in inventory.entries} == {"captured"}
    assert str(tmp_path) not in repr(inventory)


def test_v1_store_spec_dir_descendants_are_collected(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_store(store, V1_CHAIN_FILES)

    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())

    paths = _paths(inventory)
    assert "hunting/hunter/test-specs/fault-a/produced/spec-1.yaml" in paths
    assert "hunting/hunter/test-specs/fault-a/produced/spec-2.yaml" in paths


def test_v1_store_wins_a_shared_path_and_labels_current_only(tmp_path: Path) -> None:
    store = tmp_path / "store"
    shared = "hunting/orchestration/hunt_configs/produced/shared.yaml"
    store_only = "hunting/hunter/test-specs/fault-a/produced/store-only.yaml"
    raw_only = "hunting/orchestration/hunt_configs/produced/raw-only.yaml"
    _write_v1_store(store, {shared: b"store bytes\n", store_only: b"stored\n"})
    data_root = tmp_path / "raw"
    _write_raw(data_root, {shared: b"raw bytes\n", raw_only: b"current\n"})

    inventory = resolved.resolve_inventory(store, data_root, _context(), files=FileStore())

    by_path = {entry["relative_path"]: entry for entry in inventory.entries}
    assert by_path[shared]["sha256"] == hashlib.sha256(b"store bytes\n").hexdigest()
    assert by_path[shared]["origin"] == "captured"
    assert by_path[store_only]["origin"] == "captured"
    assert by_path[raw_only]["sha256"] == hashlib.sha256(b"current\n").hexdigest()
    assert by_path[raw_only]["origin"] == "current"

    # The shared identity/bytes come from the store, never the raw copy.
    captured = resolved.content_download(
        inventory, by_path[shared]["artifact_id"], by_path[shared]["sha256"]
    )
    assert b"".join(captured.chunks) == b"store bytes\n"
    current = resolved.content_download(
        inventory, by_path[raw_only]["artifact_id"], by_path[raw_only]["sha256"]
    )
    assert b"".join(current.chunks) == b"current\n"


def test_v1_store_detail_and_content_round_trip(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_store(store, V1_CHAIN_FILES)
    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())
    entry = next(
        e for e in inventory.entries if e["relative_path"].endswith("export.yaml")
    )

    detail = resolved.detail_response(inventory, TARGET, RUN, TRIAL, entry["artifact_id"])
    assert detail["entry"] == entry
    assert entry["origin"] == "captured"

    download = resolved.content_download(
        inventory, entry["artifact_id"], entry["sha256"]
    )
    assert b"".join(download.chunks) == V1_CHAIN_FILES[entry["relative_path"]]


def test_v1_store_wrong_expected_digest_is_409(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_store(store, V1_CHAIN_FILES)
    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())
    entry = next(
        e for e in inventory.entries if e["relative_path"].endswith("hunt.yaml")
    )

    with pytest.raises(artifact_reader.ArtifactLookupError) as excinfo:
        resolved.content_download(inventory, entry["artifact_id"], "deadbeef")

    assert excinfo.value.code == "artifact_digest_mismatch"
    assert excinfo.value.status_code == 409


def test_v1_store_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_store(store, V1_CHAIN_FILES, manifest=_v1_manifest() | {"target_id": "other"})

    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())

    assert inventory.status == "unavailable"
    assert inventory.reason == "trial_identity_mismatch"
    assert str(tmp_path) not in repr(inventory)


def test_v1_store_project_mismatch_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_store(store, V1_CHAIN_FILES, manifest=_v1_manifest("other-project"))

    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())

    assert inventory.status == "unavailable"
    assert inventory.reason == "project_id_mismatch"


def test_v1_store_missing_manifest_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = store / TARGET / RUN / TRIAL
    (trial_dir / PROJECT_ID / "hunting/orchestration/hunt_configs/produced").mkdir(
        parents=True
    )
    (trial_dir / PROJECT_ID / "hunting/orchestration/hunt_configs/produced/x.yaml").write_bytes(
        b"x\n"
    )

    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())

    assert inventory.status == "unavailable"
    assert inventory.reason == "manifest_missing"
    assert str(tmp_path) not in repr(inventory)


def test_v1_store_symlinked_project_subtree_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _write_v1_store(store, {})
    (tmp_path / "outside").mkdir()
    (trial_dir / PROJECT_ID).symlink_to(tmp_path / "outside", target_is_directory=True)

    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())

    assert inventory.status == "unavailable"
    assert inventory.reason == "artifact_unsafe"
    assert str(tmp_path) not in repr(inventory)


def test_v1_store_symlinked_artifact_fails_closed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_store(store, {"hunting/orchestration/hunt_configs/produced/ok.yaml": b"ok\n"})
    outside = tmp_path / "outside.yaml"
    outside.write_bytes(b"x\n")
    link = (
        store
        / TARGET
        / RUN
        / TRIAL
        / PROJECT_ID
        / "hunting/orchestration/hunt_configs/produced/evil.yaml"
    )
    link.symlink_to(outside)

    inventory = resolved.resolve_inventory(store, None, _context(), files=FileStore())

    assert inventory.status == "unavailable"
    assert inventory.reason == "artifact_unsafe"
