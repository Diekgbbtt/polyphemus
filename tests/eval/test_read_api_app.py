"""The eval read API (#278): the thin GET-only FastAPI in front of a source.

The app knows nothing about the filesystem: it asks an injected `SnapshotSource`
for a snapshot and a health state. By default that source is the filesystem one,
configured through `EVAL_ARTIFACT_STORE`. These tests pin the route surface, the
env configuration, the dataset override, the degraded health signal, and the
source-factory seam - including an unavailable source degrading to a safe 503.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from read_api import app as app_module
from read_api import source as source_module


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
                    "evidence_chain": {"hunt_config": "/host/x"},
                    "eval_sha": "eval-1",
                    "stack_fingerprint": "fp-1",
                }
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store = tmp_path / "store"
    store.mkdir()
    _seed_trial(store)
    monkeypatch.setenv("EVAL_ARTIFACT_STORE", str(store))
    monkeypatch.delenv("EVAL_DATASET_ID", raising=False)
    monkeypatch.delenv("EVAL_DATASET_NAME", raising=False)
    return TestClient(app_module.app)


def test_snapshot_returns_dataset_and_results(client: TestClient) -> None:
    res = client.get("/snapshot")

    assert res.status_code == 200
    body = res.json()
    assert body["dataset"] == {"id": "webexploitbench", "name": "WebExploitBench"}
    assert body["summary"] == {
        "targets": 1,
        "trials": 1,
        "identified": 1,
        "partial": 0,
        "missed": 0,
        "degraded": 0,
    }
    assert body["successes"][0]["vuln_id"] == "CVE-1"
    assert body["successes"][0]["target_id"] == "jetlinks-1"
    assert body["targets"] == [
        {
            "target_id": "jetlinks-1",
            "trial_count": 1,
            "identified_count": 1,
            "partial_count": 0,
            "missed_count": 0,
        }
    ]


def test_health_ok_when_store_configured(client: TestClient) -> None:
    res = client.get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["store_configured"] is True


def test_health_degraded_when_store_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVAL_ARTIFACT_STORE", raising=False)
    res = TestClient(app_module.app).get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == "degraded"
    assert res.json()["store_configured"] is False


def test_snapshot_requires_store_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVAL_ARTIFACT_STORE", raising=False)

    res = TestClient(app_module.app).get("/snapshot")

    assert res.status_code == 503


def test_dataset_is_configurable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("EVAL_ARTIFACT_STORE", str(store))
    monkeypatch.setenv("EVAL_DATASET_ID", "custom-set")
    monkeypatch.setenv("EVAL_DATASET_NAME", "Custom Set")

    body = TestClient(app_module.app).get("/snapshot").json()

    assert body["dataset"] == {"id": "custom-set", "name": "Custom Set"}


@pytest.mark.parametrize("path", ["/snapshot", "/health"])
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_read_endpoints_reject_mutation(
    client: TestClient, path: str, method: str
) -> None:
    res = getattr(client, method)(path)
    assert res.status_code == 405


def test_only_get_snapshot_and_health_are_exposed() -> None:
    exposed = {(route.path, tuple(sorted(route.methods))) for route in app_module.app.routes}

    assert exposed == {("/snapshot", ("GET",)), ("/health", ("GET",))}


# --- the source seam -----------------------------------------------------------


class _StubSource:
    """A minimal `SnapshotSource` with no filesystem at all."""

    def __init__(self, snapshot: dict, health: source_module.SourceHealth) -> None:
        self._snapshot = snapshot
        self._health = health

    def snapshot(self) -> dict:
        return self._snapshot

    def health(self) -> source_module.SourceHealth:
        return self._health


def test_create_app_uses_an_injected_source_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The env is deliberately unusable: an injected source must win over it.
    monkeypatch.delenv("EVAL_ARTIFACT_STORE", raising=False)
    snapshot = {
        "dataset": {"id": "d", "name": "D"},
        "summary": {"targets": 0, "trials": 0, "identified": 0, "degraded": 0},
        "targets": [],
        "successes": [],
        "degraded_trials": [],
    }
    health = source_module.SourceHealth(
        ok=True, detail={"store_configured": True, "store_readable": True}
    )
    calls = 0

    def factory() -> _StubSource:
        nonlocal calls
        calls += 1
        return _StubSource(snapshot, health)

    client = TestClient(app_module.create_app(factory))

    assert client.get("/snapshot").json() == snapshot
    assert client.get("/health").json() == {
        "status": "ok",
        "store_configured": True,
        "store_readable": True,
    }
    assert calls == 2  # the factory runs per request, never at construction


def test_unavailable_source_yields_a_safe_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real host path is in the env; it must not leak into the error body.
    monkeypatch.setenv("EVAL_ARTIFACT_STORE", str(tmp_path / "host-only-store"))

    class _Unavailable:
        def snapshot(self) -> dict:
            raise source_module.SnapshotSourceUnavailable(
                "EVAL_ARTIFACT_STORE is not configured"
            )

        def health(self) -> source_module.SourceHealth:
            return source_module.SourceHealth(
                ok=False, detail={"store_configured": False, "store_readable": False}
            )

    client = TestClient(app_module.create_app(_Unavailable))

    res = client.get("/snapshot")

    assert res.status_code == 503
    detail = res.json()["detail"]
    assert str(tmp_path) not in detail
    assert "/" not in detail


def test_app_module_stays_ignorant_of_the_storage_mechanism() -> None:
    # The seam's whole point: no pathlib, YAML, layout, or projection in the app.
    for leaked in ("Path", "build_snapshot", "yaml", "store_path", "dataset"):
        assert not hasattr(app_module, leaked), leaked
