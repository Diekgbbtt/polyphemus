"""The `/snapshot` data source seam (#278).

`SnapshotSource` is the contract the API depends on: hand it a snapshot, hand
it a health state. `ArtifactStoreSnapshotSource` is the filesystem adapter over
`build_snapshot()`, and `filesystem_source()` is the injectable factory that
reads the environment at call time (never at import). These tests pin the
protocol satisfaction, the env-driven configuration, the dataset override, the
unavailable-source signal, and the health wire shape.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from read_api import source


def _seed_trial(store: Path) -> None:
    trial = store / "jetlinks-1" / "run-a" / "t1"
    trial.mkdir(parents=True)
    (trial / "run-manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "trial_id": "t1",
                "target_id": "jetlinks-1",
                "target_run_id": "run-a",
                "eval_sha": "eval-1",
                "stack_fingerprint": "fp-1",
            }
        ),
        encoding="utf-8",
    )
    (trial / "verdicts.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "vuln_id": "CVE-1",
                    "identified": "identified",
                    "confidence": 0.8,
                    "matched": {"unit": "u", "fault_class": "fc", "symptom": "s"},
                    "eval_sha": "eval-1",
                    "stack_fingerprint": "fp-1",
                }
            ]
        ),
        encoding="utf-8",
    )


# --- the adapter ---------------------------------------------------------------


def test_adapter_satisfies_the_snapshot_source_protocol(tmp_path: Path) -> None:
    adapter = source.ArtifactStoreSnapshotSource(tmp_path)

    assert isinstance(adapter, source.SnapshotSource)


def test_adapter_projects_the_store(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_trial(store)

    snap = source.ArtifactStoreSnapshotSource(store).snapshot()

    assert snap["dataset"] == {"id": "webexploitbench", "name": "WebExploitBench"}
    assert snap["summary"] == {
        "targets": 1,
        "trials": 1,
        "identified": 1,
        "partial": 0,
        "missed": 0,
        "degraded": 0,
    }
    assert snap["successes"][0]["vuln_id"] == "CVE-1"


def test_adapter_applies_the_dataset_override(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_trial(store)

    snap = source.ArtifactStoreSnapshotSource(
        store, dataset_id="custom-set", dataset_name="Custom Set"
    ).snapshot()

    assert snap["dataset"] == {"id": "custom-set", "name": "Custom Set"}


def test_adapter_returns_an_empty_snapshot_for_a_missing_directory(tmp_path: Path) -> None:
    # A configured-but-absent store is still a valid (empty) report, as before.
    snap = source.ArtifactStoreSnapshotSource(tmp_path / "nope").snapshot()

    assert snap["summary"] == {
        "targets": 0,
        "trials": 0,
        "identified": 0,
        "partial": 0,
        "missed": 0,
        "degraded": 0,
    }


def test_unconfigured_adapter_refuses_to_snapshot_without_leaking_a_path() -> None:
    with pytest.raises(source.SnapshotSourceUnavailable) as caught:
        source.ArtifactStoreSnapshotSource(None).snapshot()

    message = str(caught.value)
    assert message
    assert "/" not in message


# --- health --------------------------------------------------------------------


def test_health_is_ok_and_readable_for_a_present_store(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()

    health = source.ArtifactStoreSnapshotSource(store).health()

    assert health.ok is True
    assert health.as_dict() == {
        "status": "ok",
        "store_configured": True,
        "store_readable": True,
        "materialized_trials": 0,
        "project_data_configured": False,
        "project_data_readable": False,
        "graph_client_configured": False,
    }


def test_health_is_degraded_when_unconfigured() -> None:
    health = source.ArtifactStoreSnapshotSource(None).health()

    assert health.ok is False
    assert health.as_dict() == {
        "status": "degraded",
        "store_configured": False,
        "store_readable": False,
        "materialized_trials": 0,
        "project_data_configured": False,
        "project_data_readable": False,
        "graph_client_configured": False,
    }


def test_health_is_degraded_when_the_store_directory_is_absent(tmp_path: Path) -> None:
    health = source.ArtifactStoreSnapshotSource(tmp_path / "nope").health()

    assert health.ok is False
    assert health.as_dict()["store_readable"] is False
    assert health.as_dict()["materialized_trials"] == 0


def test_health_is_degraded_when_the_store_is_not_a_directory(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.write_text("not a directory", encoding="utf-8")

    health = source.ArtifactStoreSnapshotSource(store).health()

    assert health.ok is False
    assert health.as_dict()["store_configured"] is True
    assert health.as_dict()["store_readable"] is False
    assert health.as_dict()["materialized_trials"] == 0


def test_health_counts_materialized_trials_without_degrading(tmp_path: Path) -> None:
    store = tmp_path / "store"
    for target, run, trial in (
        ("jetlinks-1", "run-a", "t1"),
        ("jetlinks-1", "run-a", "t2"),
        ("jetlinks-1", "run-b", "t1"),
    ):
        trial_dir = store / target / run / trial
        trial_dir.mkdir(parents=True)
        (trial_dir / "run-manifest.yaml").write_text("schema_version: 2\n", encoding="utf-8")
    # A staging scratch tree and a live mirror are not materialized Trials.
    (store / "_staging" / "trial-x").mkdir(parents=True)
    (store / "arm-a" / "live" / "pid").mkdir(parents=True)

    health = source.ArtifactStoreSnapshotSource(store).health()

    assert health.ok is True
    assert health.as_dict() == {
        "status": "ok",
        "store_configured": True,
        "store_readable": True,
        "materialized_trials": 3,
        "project_data_configured": False,
        "project_data_readable": False,
        "graph_client_configured": False,
    }


# --- the injectable factory ----------------------------------------------------


def test_filesystem_factory_satisfies_the_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVAL_ARTIFACT_STORE", raising=False)

    assert isinstance(source.filesystem_source(), source.SnapshotSource)


def test_filesystem_factory_reads_the_environment_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVAL_ARTIFACT_STORE", str(tmp_path / "one"))
    first = source.filesystem_source()
    monkeypatch.setenv("EVAL_ARTIFACT_STORE", str(tmp_path / "two"))
    second = source.filesystem_source()

    # Each call re-reads the environment; nothing is captured at import.
    assert first.store == str(tmp_path / "one")
    assert second.store == str(tmp_path / "two")


def test_filesystem_factory_defaults_the_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVAL_DATASET_ID", raising=False)
    monkeypatch.delenv("EVAL_DATASET_NAME", raising=False)

    built = source.filesystem_source()

    assert (built.dataset_id, built.dataset_name) == ("webexploitbench", "WebExploitBench")


def test_filesystem_factory_honors_the_dataset_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVAL_DATASET_ID", "custom-set")
    monkeypatch.setenv("EVAL_DATASET_NAME", "Custom Set")

    built = source.filesystem_source()

    assert (built.dataset_id, built.dataset_name) == ("custom-set", "Custom Set")


# --- resolved sources and unassigned saved data (unified workspace) -------------


PROJECT_ID = "c0641257-a1a9-4e13-acee-6effa28311f5"
INSTANCE = "eval-server-1"


def _seed_identified_trial(
    store: Path,
    *,
    target: str = "comfyui-1",
    run: str = "run-a",
    trial: str = "t1",
    project_id: str = PROJECT_ID,
    instance_id: str = INSTANCE,
) -> None:
    trial_dir = store / target / run / trial
    trial_dir.mkdir(parents=True)
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "trial_id": trial,
                "target_id": target,
                "target_run_id": run,
                "instance_id": instance_id,
                "project_id": project_id,
                "eval_sha": "eval-1",
                "stack_fingerprint": "fp-1",
            }
        ),
        encoding="utf-8",
    )


def _raw_project(root: Path, project_id: str, files: dict[str, bytes]) -> None:
    for relative, data in files.items():
        path = root / project_id / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _graph_payload(project_id: str = PROJECT_ID) -> dict:
    return {
        "project_id": project_id,
        "nodes": [{"id": "n1", "name": "a", "type": "L1Service", "properties": {}}],
        "links": [],
    }


def _first_entry(inventory: dict) -> dict:
    stack = list(inventory["groups"])
    while stack:
        node = stack.pop(0)
        if node["entries"]:
            return node["entries"][0]
        stack.extend(node["children"])
    raise AssertionError("no inventory entries")


class _FakeGraphClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_graph(self, project_id: str) -> object:
        self.calls.append(project_id)
        return self.payload


def test_resolved_graph_uses_the_injected_graph_client(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)
    client = _FakeGraphClient(_graph_payload())
    adapter = source.ArtifactStoreSnapshotSource(
        store,
        instance_id=INSTANCE,
        graph_client_factory=lambda: client,
    )

    body = adapter.resolved_graph("comfyui-1", "run-a", "t1")

    assert body["status"] == "available"
    assert body["source"] == "project_storage"
    assert body["project_id"] == PROJECT_ID
    assert client.calls == [PROJECT_ID]
    assert str(tmp_path) not in repr(body)


def test_resolved_artifacts_collect_raw_hunting_and_skills(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)
    raw = tmp_path / "raw"
    _raw_project(
        raw,
        PROJECT_ID,
        {
            "hunting/orchestration/hunt_configs/produced/prod.yaml": b"a\n",
            "skills/authn/SKILL.md": b"# skill\n",
        },
    )
    adapter = source.ArtifactStoreSnapshotSource(
        store, project_data_root=raw, instance_id=INSTANCE
    )

    body = adapter.list_resolved_artifacts("comfyui-1", "run-a", "t1")

    assert body["status"] == "available"
    assert body["source"] == "project_storage"
    assert body["fallback_reason"] == "project_artifacts_unavailable"
    keys = {group["key"] for group in body["groups"]}
    assert "hunt-configs" in keys and "skills" in keys


def test_resolved_artifact_detail_and_content_round_trip(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)
    raw = tmp_path / "raw"
    _raw_project(
        raw, PROJECT_ID, {"hunting/orchestration/hunt_configs/produced/prod.yaml": b"a\n"}
    )
    adapter = source.ArtifactStoreSnapshotSource(
        store, project_data_root=raw, instance_id=INSTANCE
    )

    inventory = adapter.list_resolved_artifacts("comfyui-1", "run-a", "t1")
    entry = _first_entry(inventory)
    detail = adapter.get_resolved_artifact(
        "comfyui-1", "run-a", "t1", entry["artifact_id"]
    )
    assert detail["entry"]["relative_path"] == entry["relative_path"]

    download = adapter.stream_resolved_artifact(
        "comfyui-1", "run-a", "t1", entry["artifact_id"], entry["sha256"]
    )
    assert b"".join(download.chunks) == b"a\n"


def test_unassigned_saved_data_lists_only_unproven_projects(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store, project_id=PROJECT_ID)
    raw = tmp_path / "raw"
    _raw_project(
        raw, PROJECT_ID, {"hunting/orchestration/hunt_configs/produced/prod.yaml": b"a\n"}
    )
    _raw_project(
        raw,
        "orphan-project",
        {
            "hunting/orchestration/hunt_configs/produced/prod.yaml": b"a\n",
            "skills/authn/SKILL.md": b"# skill\n",
        },
    )
    adapter = source.ArtifactStoreSnapshotSource(
        store, project_data_root=raw, instance_id=INSTANCE
    )

    snapshot = adapter.snapshot()

    assert snapshot["unassigned_saved_data"] == [
        {
            "project_id": "orphan-project",
            "status": "available",
            "hunting": 1,
            "skills": 1,
        }
    ]


def test_unassigned_saved_data_excludes_shared_fault_kb_directory(
    tmp_path: Path,
) -> None:
    """The app provisions DATA_ROOT/hunting/fault-kb.yaml outside projects."""
    store = tmp_path / "store"
    store.mkdir()
    raw = tmp_path / "raw"
    (raw / "hunting").mkdir(parents=True)
    (raw / "hunting" / "fault-kb.yaml").write_text("version: 1\n", encoding="utf-8")
    _raw_project(raw, "orphan-project", {"skills/authn/SKILL.md": b"# skill\n"})
    adapter = source.ArtifactStoreSnapshotSource(
        store, project_data_root=raw, instance_id=INSTANCE
    )

    assert adapter.snapshot()["unassigned_saved_data"] == [
        {
            "project_id": "orphan-project",
            "status": "available",
            "hunting": 0,
            "skills": 1,
        }
    ]


def test_unassigned_saved_data_ignores_a_trial_from_another_instance(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store, instance_id="other-instance")
    raw = tmp_path / "raw"
    _raw_project(
        raw, PROJECT_ID, {"hunting/orchestration/hunt_configs/produced/prod.yaml": b"a\n"}
    )
    adapter = source.ArtifactStoreSnapshotSource(
        store, project_data_root=raw, instance_id=INSTANCE
    )

    rows = adapter.snapshot()["unassigned_saved_data"]

    assert rows == [
        {"project_id": PROJECT_ID, "status": "available", "hunting": 1, "skills": 0}
    ]


def test_unassigned_saved_data_flags_a_symlinked_directory_as_unavailable(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    raw = tmp_path / "raw"
    raw.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (raw / "linked-project").symlink_to(outside, target_is_directory=True)
    adapter = source.ArtifactStoreSnapshotSource(
        store, project_data_root=raw, instance_id=INSTANCE
    )

    rows = adapter.snapshot()["unassigned_saved_data"]

    assert rows == [
        {
            "project_id": "linked-project",
            "status": "unavailable",
            "hunting": 0,
            "skills": 0,
            "reason": "artifact_unsafe",
        }
    ]


def test_health_reports_optional_sources_without_degrading(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    adapter = source.ArtifactStoreSnapshotSource(
        store,
        project_data_root=tmp_path / "raw",
        agent_base_url="http://agent:8080",
        instance_id=INSTANCE,
    )

    health = adapter.health()

    assert health.ok is True
    assert health.as_dict() == {
        "status": "ok",
        "store_configured": True,
        "store_readable": True,
        "materialized_trials": 0,
        "project_data_configured": True,
        "project_data_readable": False,
        "graph_client_configured": True,
    }


def test_filesystem_factory_reads_the_resolved_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVAL_ARTIFACT_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("EVAL_PROJECT_DATA_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("EVAL_AGENT_BASE_URL", "http://agent:8080")
    monkeypatch.setenv("EVAL_INSTANCE_ID", INSTANCE)

    built = source.filesystem_source()

    assert built.project_data_root == str(tmp_path / "raw")
    assert built.agent_base_url == "http://agent:8080"
    assert built.instance_id == INSTANCE


def test_filesystem_factory_is_unavailable_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EVAL_ARTIFACT_STORE", raising=False)

    with pytest.raises(source.SnapshotSourceUnavailable):
        source.filesystem_source().snapshot()


# --- the production overlay -----------------------------------------------------

# The dashboard overlay must wire the resolved sources the SPA reads: the
# read-only raw project data root and the current-graph agent base URL, plus the
# instance id that gates fallback eligibility.
COMPOSE_OVERLAY = (
    Path(__file__).resolve().parents[2] / "eval" / "docker-compose.dashboard.real.yml"
)


def test_compose_overlay_configures_the_resolved_sources_read_only() -> None:
    overlay = yaml.safe_load(COMPOSE_OVERLAY.read_text(encoding="utf-8"))
    api = overlay["services"]["eval-api"]
    environment = api["environment"]

    assert environment["EVAL_ARTIFACT_STORE"] == "/srv/eval-artifacts"
    assert environment["EVAL_PROJECT_DATA_ROOT"] == "/srv/eval-project-data"
    assert environment["EVAL_AGENT_BASE_URL"] == "http://agent:8080"
    # The instance id may be parametrised, but it must be present.
    assert "EVAL_INSTANCE_ID" in environment

    volumes = {volume["target"]: volume for volume in api.get("volumes", [])}
    # The raw project data root is mounted, and every source is an explicit,
    # read-only bind that must already exist.
    assert "/srv/eval-project-data" in volumes
    for target, volume in volumes.items():
        assert volume["type"] == "bind", target
        assert volume["read_only"] is True, target
        assert volume["bind"]["create_host_path"] is False, target
    # The default raw root is the eval instance's persistent data root.
    assert volumes["/srv/eval-project-data"]["source"] == (
        "${EVAL_PROJECT_DATA_ROOT_HOST_PATH:-"
        "/opt/polymerhus-dev/eval/instances/data/eval-server-1}"
    )
    # No destructive service management was added by the overlay.
    assert "down" not in str(api.get("command", ""))


# --- recorded spend (current-usage feature) ------------------------------------

RUNS_ROOT_ENV = "EVAL_RUNS_ROOT"


def _seed_spend_record(
    runs_root: Path,
    *,
    name: str = "spend-a1b2.yaml",
    target: str = "comfyui-1",
    run: str = "run-a",
    trial: str = "t1",
    project_id: str = PROJECT_ID,
    instance_id: str = INSTANCE,
    **fields: object,
) -> None:
    record = {
        "target_id": target,
        "target_run_id": run,
        "trial_id": trial,
        "project_id": project_id,
        "instance_id": instance_id,
        "spent_tokens": 500,
        "spend_overshoot": 0,
        "spend_by_agent": {"recon": {"total_tokens": 1500}},
    }
    record.update(fields)
    path = runs_root / target / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")


def test_snapshot_attaches_recorded_spend_resolved_by_identity(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)
    runs_root = tmp_path / "runs"
    _seed_spend_record(runs_root)

    adapter = source.ArtifactStoreSnapshotSource(store, runs_root=runs_root)
    trial = adapter.snapshot()["trials"][0]

    assert trial["spend"] == {
        "status": "available",
        "spent_tokens": 500,
        "spend_overshoot": 0,
        "spend_by_agent": {"recon": {"total_tokens": 1500}},
        "reason": None,
    }


def test_snapshot_spend_is_unavailable_when_no_runs_root_is_configured(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)

    trial = source.ArtifactStoreSnapshotSource(store).snapshot()["trials"][0]

    assert trial["spend"]["status"] == "unavailable"
    assert trial["spend"]["spent_tokens"] is None
    assert trial["spend"]["reason"] == "spend_root_unconfigured"


def test_compose_overlay_mounts_the_runs_root_read_only() -> None:
    overlay = yaml.safe_load(COMPOSE_OVERLAY.read_text(encoding="utf-8"))
    api = overlay["services"]["eval-api"]

    assert api["environment"]["EVAL_RUNS_ROOT"] == "/srv/eval-runs"
    volumes = {volume["target"]: volume for volume in api.get("volumes", [])}
    runs = volumes["/srv/eval-runs"]
    assert runs["read_only"] is True
    assert runs["bind"]["create_host_path"] is False


def test_filesystem_factory_reads_the_runs_root_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))

    built = source.filesystem_source()

    assert built.runs_root == str(tmp_path / "runs")


def test_snapshot_reads_spend_from_the_legacy_root_too(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)
    primary = tmp_path / "runs"
    legacy = tmp_path / "legacy-runs"
    primary.mkdir()
    _seed_spend_record(legacy, name="historical.yaml")

    adapter = source.ArtifactStoreSnapshotSource(
        store, runs_root=primary, legacy_runs_root=legacy
    )
    trial = adapter.snapshot()["trials"][0]

    assert trial["spend"]["status"] == "available"
    assert trial["spend"]["spent_tokens"] == 500


def test_the_same_runs_root_configured_twice_is_not_ambiguous(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)
    root = tmp_path / "runs"
    _seed_spend_record(root)

    adapter = source.ArtifactStoreSnapshotSource(
        store, runs_root=root, legacy_runs_root=root
    )
    trial = adapter.snapshot()["trials"][0]

    assert trial["spend"]["status"] == "available"
    assert trial["spend"]["spent_tokens"] == 500


def test_a_record_in_two_different_roots_is_ambiguous(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)
    primary = tmp_path / "runs"
    legacy = tmp_path / "legacy-runs"
    _seed_spend_record(primary, name="current.yaml")
    _seed_spend_record(legacy, name="historical.yaml")

    adapter = source.ArtifactStoreSnapshotSource(
        store, runs_root=primary, legacy_runs_root=legacy
    )
    spend = adapter.snapshot()["trials"][0]["spend"]

    assert spend["status"] == "unavailable"
    assert spend["reason"] == "spend_record_ambiguous"


def test_filesystem_factory_reads_the_legacy_runs_root_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVAL_RUNS_LEGACY_ROOT", str(tmp_path / "legacy-runs"))

    built = source.filesystem_source()

    assert built.legacy_runs_root == str(tmp_path / "legacy-runs")


def _inventory_paths(body: dict) -> set[str]:
    paths: set[str] = set()

    def visit(groups: list[dict]) -> None:
        for group in groups:
            for entry in group.get("entries", []):
                paths.add(entry["relative_path"])
            visit(group.get("children", []))

    visit(body.get("groups", []))
    return paths


def test_a_second_request_sees_new_data_without_a_restart(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed_identified_trial(store)
    raw = tmp_path / "raw"
    _raw_project(
        raw,
        PROJECT_ID,
        {"hunting/orchestration/hunt_configs/produced/prod.yaml": b"a\n"},
    )
    runs_root = tmp_path / "runs"
    adapter = source.ArtifactStoreSnapshotSource(
        store, project_data_root=raw, instance_id=INSTANCE, runs_root=runs_root
    )

    first = adapter.snapshot()
    assert [trial["trial_id"] for trial in first["trials"]] == ["t1"]
    assert first["trials"][0]["spend"]["status"] == "unavailable"

    # The next evaluation adds a materialized Trial, an allowlisted artifact and
    # a spend record. The same adapter (no restart, no cache) must see all three.
    _seed_identified_trial(store, trial="t2")
    _raw_project(
        raw,
        PROJECT_ID,
        {"hunting/orchestration/hunt_configs/produced/new.yaml": b"b\n"},
    )
    _seed_spend_record(runs_root, trial="t1")

    second = adapter.snapshot()
    assert [trial["trial_id"] for trial in second["trials"]] == ["t1", "t2"]
    assert second["trials"][0]["spend"]["status"] == "available"
    assert second["trials"][0]["spend"]["spent_tokens"] == 500
    assert "hunting/orchestration/hunt_configs/produced/new.yaml" in _inventory_paths(
        adapter.list_resolved_artifacts("comfyui-1", "run-a", "t1")
    )


def test_filesystem_factory_leaves_the_legacy_root_unset_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EVAL_RUNS_LEGACY_ROOT", raising=False)

    built = source.filesystem_source()

    assert built.legacy_runs_root is None
