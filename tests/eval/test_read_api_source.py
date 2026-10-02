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
    }


def test_health_is_degraded_when_unconfigured() -> None:
    health = source.ArtifactStoreSnapshotSource(None).health()

    assert health.ok is False
    assert health.as_dict() == {
        "status": "degraded",
        "store_configured": False,
        "store_readable": False,
    }


def test_health_is_degraded_when_the_store_directory_is_absent(tmp_path: Path) -> None:
    health = source.ArtifactStoreSnapshotSource(tmp_path / "nope").health()

    assert health.as_dict()["store_readable"] is False


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


def test_filesystem_factory_is_unavailable_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EVAL_ARTIFACT_STORE", raising=False)

    with pytest.raises(source.SnapshotSourceUnavailable):
        source.filesystem_source().snapshot()
