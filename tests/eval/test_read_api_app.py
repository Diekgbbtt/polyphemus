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


@pytest.mark.parametrize(
    "path",
    [
        "/snapshot",
        "/health",
        "/trials/jetlinks-1/run-a/t1/project-graph",
        "/trials/jetlinks-1/run-a/t1/artifacts",
        "/trials/jetlinks-1/run-a/t1/artifacts/" + "0" * 64,
        "/trials/jetlinks-1/run-a/t1/artifacts/" + "0" * 64 + "/content",
    ],
)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_read_endpoints_reject_mutation(
    client: TestClient, path: str, method: str
) -> None:
    res = getattr(client, method)(path)
    assert res.status_code == 405


def test_only_get_routes_are_exposed() -> None:
    exposed = {(route.path, tuple(sorted(route.methods))) for route in app_module.app.routes}

    assert exposed == {
        ("/snapshot", ("GET",)),
        ("/health", ("GET",)),
        ("/trials/{target_id}/{target_run_id}/{trial_id}/project-graph", ("GET",)),
        ("/trials/{target_id}/{target_run_id}/{trial_id}/artifacts", ("GET",)),
        (
            "/trials/{target_id}/{target_run_id}/{trial_id}/artifacts/{artifact_id}",
            ("GET",),
        ),
        (
            "/trials/{target_id}/{target_run_id}/{trial_id}/artifacts/{artifact_id}/content",
            ("GET",),
        ),
        (
            "/trials/{target_id}/{target_run_id}/{trial_id}/resolved-graph",
            ("GET",),
        ),
        (
            "/trials/{target_id}/{target_run_id}/{trial_id}/resolved-artifacts",
            ("GET",),
        ),
        (
            "/trials/{target_id}/{target_run_id}/{trial_id}/resolved-artifacts/{artifact_id}",
            ("GET",),
        ),
        (
            "/trials/{target_id}/{target_run_id}/{trial_id}/resolved-artifacts/{artifact_id}/content",
            ("GET",),
        ),
    }


def test_shared_read_api_never_exposes_ground_truth() -> None:
    # The operator reference has its own service on its own network; the shared
    # read API the agent can reach must never grow a route to it.
    paths = {route.path for route in app_module.app.routes}

    assert not [path for path in paths if "ground-truth" in path]


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


# --- resolved endpoints (unified workspace) ------------------------------------


PROJECT_ID = "c0641257-a1a9-4e13-acee-6effa28311f5"
INSTANCE = "eval-server-1"
RELATIVE = "hunting/orchestration/hunt_configs/produced/prod.yaml"


class _StubGraphClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def get_graph(self, project_id: str) -> dict:
        return self.payload


@pytest.fixture
def resolved_client(tmp_path: Path) -> TestClient:
    store = tmp_path / "store"
    trial_dir = store / "comfyui-1" / "run-a" / "t1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "trial_id": "t1",
                "target_id": "comfyui-1",
                "target_run_id": "run-a",
                "instance_id": INSTANCE,
                "project_id": PROJECT_ID,
                "eval_sha": "eval-1",
                "stack_fingerprint": "fp-1",
            }
        ),
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    artifact = raw / PROJECT_ID / RELATIVE
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"kind: hunt-config\n")
    graph = {
        "project_id": PROJECT_ID,
        "nodes": [{"id": "n1", "name": "a", "type": "L1Service", "properties": {}}],
        "links": [],
    }
    source_obj = source_module.ArtifactStoreSnapshotSource(
        store,
        project_data_root=raw,
        instance_id=INSTANCE,
        graph_client_factory=lambda: _StubGraphClient(graph),
    )
    return TestClient(app_module.create_app(lambda: source_obj))


def _resolved_base(trial: str = "t1") -> str:
    return f"/trials/comfyui-1/run-a/{trial}"


def _first_entry(inventory: dict) -> dict:
    stack = list(inventory["groups"])
    while stack:
        node = stack.pop(0)
        if node["entries"]:
            return node["entries"][0]
        stack.extend(node["children"])
    raise AssertionError("no inventory entries")


def test_resolved_graph_route_returns_current_graph(resolved_client: TestClient) -> None:
    res = resolved_client.get(f"{_resolved_base()}/resolved-graph")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "available"
    assert body["source"] == "project_storage"
    assert body["project_id"] == PROJECT_ID
    assert body["graph"]["nodes"][0]["id"] == "n1"
    assert "/tmp" not in res.text and "/srv" not in res.text and "/opt" not in res.text


def test_resolved_artifacts_route_lists_and_streams(resolved_client: TestClient) -> None:
    inventory = resolved_client.get(f"{_resolved_base()}/resolved-artifacts").json()
    assert inventory["status"] == "available"
    assert inventory["source"] == "project_storage"
    entry = _first_entry(inventory)

    detail = resolved_client.get(
        f"{_resolved_base()}/resolved-artifacts/{entry['artifact_id']}"
    )
    assert detail.status_code == 200
    assert detail.json()["entry"]["relative_path"] == RELATIVE
    url = detail.json()["content_url"]
    assert url.startswith(f"{_resolved_base()}/resolved-artifacts/")
    assert "expected_sha256=" in url

    content = resolved_client.get(url)
    assert content.status_code == 200
    assert content.content == b"kind: hunt-config\n"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["content-length"] == str(len(b"kind: hunt-config\n"))


def test_resolved_content_requires_the_expected_digest(
    resolved_client: TestClient,
) -> None:
    inventory = resolved_client.get(f"{_resolved_base()}/resolved-artifacts").json()
    entry = _first_entry(inventory)
    base = f"{_resolved_base()}/resolved-artifacts/{entry['artifact_id']}/content"

    assert resolved_client.get(base).status_code == 422
    wrong = resolved_client.get(f"{base}?expected_sha256=deadbeef")
    assert wrong.status_code == 409
    assert wrong.json()["detail"] == "artifact_digest_mismatch"


@pytest.mark.parametrize(
    "path",
    [
        "/resolved-graph",
        "/resolved-artifacts",
        "/resolved-artifacts/" + "0" * 64,
        "/resolved-artifacts/" + "0" * 64 + "/content",
    ],
)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_resolved_artifact_routes_reject_mutation(
    resolved_client: TestClient, path: str, method: str
) -> None:
    base = f"{_resolved_base()}"
    assert getattr(resolved_client, method)(base + path).status_code == 405


def test_resolved_unknown_trial_is_a_path_free_404(resolved_client: TestClient) -> None:
    res = resolved_client.get(f"{_resolved_base('missing')}/resolved-graph")

    assert res.status_code == 404
    assert res.json()["detail"] == "trial_not_found"
