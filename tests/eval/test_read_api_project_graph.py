"""The manifest-backed historical project-graph read API (real eval artifacts).

The route serves the immutable `project-graph.json` a Trial captured, selected
only through its full identity and the run manifest. It must never proxy the
operational project API, never accept a client filesystem path, and never leak
an absolute host path in an error.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from read_api import app as app_module
from read_api import project_graph as graph_reader
from read_api import source as source_module

TARGET = "jetlinks-1"
RUN = "run-a"
TRIAL = "t1"
PROJECT_ID = "proj-jetlinks-1"
CAPTURED_AT = "2024-01-01T00:00:00+00:00"


def _payload(project_id: str = PROJECT_ID) -> dict:
    return {
        "project_id": project_id,
        "nodes": [
            {"id": "n2", "name": "b", "type": "Endpoint", "properties": {"z": 1}},
            {"id": "n1", "name": "a", "type": "L1Service", "properties": {}},
        ],
        "links": [
            {"source": "n2", "target": "n1", "type": "CONNECTS"},
            {"source": "n1", "target": "n2", "type": "USES"},
        ],
    }


def _sections(project_id: str = PROJECT_ID, digest: str = "graph-digest") -> dict:
    return {
        "project_snapshot": {
            "status": "available",
            "project_id": project_id,
            "captured_at": CAPTURED_AT,
            "snapshot_sha256": "snapshot-fp",
        },
        "project_artifacts": {
            "status": "available",
            "project_id": project_id,
            "captured_at": CAPTURED_AT,
            "snapshot_sha256": "snapshot-fp",
            "entries": [],
        },
        "project_graph": {
            "status": "available",
            "project_id": project_id,
            "captured_at": CAPTURED_AT,
            "sha256": digest,
            "node_count": 2,
            "link_count": 2,
        },
    }


def _seed(
    store: Path,
    *,
    target: str = TARGET,
    run: str = RUN,
    trial: str = TRIAL,
    project_id: str = PROJECT_ID,
    graph_bytes: bytes | None = None,
    digest: str | None = None,
    schema_version: int = 2,
    sections: dict | None = None,
) -> Path:
    trial_dir = store / target / run / trial
    trial_dir.mkdir(parents=True, exist_ok=True)
    if graph_bytes is None:
        graph_bytes = json.dumps(_payload(project_id)).encode("utf-8")
    (trial_dir / "project-graph.json").write_bytes(graph_bytes)
    if sections is None:
        sections = _sections(project_id, digest or hashlib.sha256(graph_bytes).hexdigest())
    manifest = {
        "schema_version": schema_version,
        "trial_id": trial,
        "target_id": target,
        "target_run_id": run,
        "instance_id": "inst-1",
        "project_id": project_id,
        "start_phase": "recon",
        "terminal": "complete",
        "phases": [],
        "eval_sha": "eval-1",
        "stack_fingerprint": "fp-1",
        "copied_at": CAPTURED_AT,
    }
    manifest.update(sections)
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return trial_dir


def _client(store: Path) -> TestClient:
    return TestClient(
        app_module.create_app(lambda: source_module.ArtifactStoreSnapshotSource(store))
    )


# --- the source adapter ---------------------------------------------------------


def test_get_project_graph_returns_graphdata_and_capture_metadata(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed(store)
    adapter = source_module.ArtifactStoreSnapshotSource(store)

    result = adapter.get_project_graph(TARGET, RUN, TRIAL)

    assert set(result) == {"status", "captured_at", "sha256", "graph"}
    assert result["status"] == "available"
    assert result["captured_at"] == CAPTURED_AT
    graph_data = json.dumps(_payload()).encode("utf-8")
    assert result["sha256"] == hashlib.sha256(graph_data).hexdigest()
    # The returned graph is the normalized GraphData shape (nodes sorted by id).
    assert result["graph"]["project_id"] == PROJECT_ID
    assert [node["id"] for node in result["graph"]["nodes"]] == ["n1", "n2"]
    assert [(link["source"], link["target"]) for link in result["graph"]["links"]] == [
        ("n1", "n2"),
        ("n2", "n1"),
    ]


def test_unconfigured_source_refuses_the_graph_without_a_path() -> None:
    adapter = source_module.ArtifactStoreSnapshotSource(None)

    with pytest.raises(source_module.SnapshotSourceUnavailable) as caught:
        adapter.get_project_graph(TARGET, RUN, TRIAL)

    assert "/" not in str(caught.value)


# --- the route ------------------------------------------------------------------


def test_project_graph_route_uses_full_trial_identity(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed(store, run="run-a", project_id="proj-a")
    _seed(store, run="run-b", project_id="proj-b")
    client = _client(store)

    first = client.get(f"/trials/{TARGET}/run-a/{TRIAL}/project-graph")
    second = client.get(f"/trials/{TARGET}/run-b/{TRIAL}/project-graph")

    assert first.status_code == 200
    assert first.json()["graph"]["project_id"] == "proj-a"
    assert second.status_code == 200
    assert second.json()["graph"]["project_id"] == "proj-b"
    # The same trial id under a different run is a different Trial.
    assert client.get(f"/trials/{TARGET}/run-c/{TRIAL}/project-graph").status_code == 404


def test_project_graph_route_never_calls_or_mentions_live_api(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed(store)
    client = _client(store)

    res = client.get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 200
    assert "projects/" not in json.dumps(res.json())
    # The reader never imports the operational project API client.
    assert not hasattr(graph_reader, "api")
    module_source = inspect.getsource(graph_reader)
    assert "orchestrator.api" not in module_source
    assert "projects/" not in module_source


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_project_graph_route_rejects_mutation(tmp_path: Path, method: str) -> None:
    store = tmp_path / "store"
    _seed(store)

    res = getattr(_client(store), method)(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 405


# --- compatibility and integrity -------------------------------------------------


def test_schema_v1_trial_is_project_graph_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed(store, schema_version=1, sections={})

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_unavailable"
    assert str(tmp_path) not in res.text


def test_schema_v2_unavailable_sections_are_project_graph_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    sections = _sections()
    sections["project_graph"]["status"] = "unavailable"
    _seed(store, sections=sections)

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_unavailable"
    assert str(tmp_path) not in res.text


def test_unknown_trial_is_404(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed(store)

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/missing/project-graph")

    assert res.status_code == 404
    assert str(tmp_path) not in res.text


def test_missing_manifest_is_project_graph_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _seed(store)
    (trial_dir / "run-manifest.yaml").unlink()

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_unavailable"
    assert str(tmp_path) not in res.text


def test_missing_graph_file_is_project_graph_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _seed(store)
    (trial_dir / "project-graph.json").unlink()

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_unavailable"
    assert str(tmp_path) not in res.text


def test_malformed_manifest_is_project_graph_invalid(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _seed(store)
    (trial_dir / "run-manifest.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_invalid"
    assert str(tmp_path) not in res.text


def test_malformed_json_is_project_graph_invalid(tmp_path: Path) -> None:
    store = tmp_path / "store"
    bad = b"{not json"
    _seed(store, graph_bytes=bad, digest=hashlib.sha256(bad).hexdigest())

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_invalid"
    assert str(tmp_path) not in res.text


def test_invalid_graphdata_is_project_graph_invalid(tmp_path: Path) -> None:
    store = tmp_path / "store"
    broken = json.dumps(
        {"project_id": PROJECT_ID, "nodes": [{"name": "no-id", "type": "X", "properties": {}}], "links": []}
    ).encode("utf-8")
    _seed(store, graph_bytes=broken, digest=hashlib.sha256(broken).hexdigest())

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_invalid"
    assert str(tmp_path) not in res.text


def test_project_id_mismatch_is_project_graph_invalid(tmp_path: Path) -> None:
    store = tmp_path / "store"
    mismatched = json.dumps(_payload("someone-else")).encode("utf-8")
    _seed(store, graph_bytes=mismatched, digest=hashlib.sha256(mismatched).hexdigest())

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_invalid"
    assert str(tmp_path) not in res.text


def test_digest_mismatch_is_project_graph_digest_mismatch(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed(store, digest="0" * 64)

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_digest_mismatch"
    assert str(tmp_path) not in res.text


def test_symlink_replacement_is_project_graph_invalid(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _seed(store)
    outside = tmp_path / "outside.json"
    outside.write_bytes(json.dumps(_payload()).encode("utf-8"))
    graph_path = trial_dir / "project-graph.json"
    graph_path.unlink()
    graph_path.symlink_to(outside)

    res = _client(store).get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")

    assert res.status_code == 409
    assert res.json()["detail"] == "project_graph_invalid"
    assert str(tmp_path) not in res.text


@pytest.mark.parametrize(
    "parts",
    [
        ("..", RUN, TRIAL),
        (".", RUN, TRIAL),
        ("a/b", RUN, TRIAL),
        ("a\\b", RUN, TRIAL),
        (TARGET, "..", TRIAL),
        (TARGET, RUN, ".."),
        ("", RUN, TRIAL),
        (TARGET, RUN, "nul\x00id"),
    ],
)
def test_path_like_identifiers_are_trial_not_found(tmp_path: Path, parts) -> None:
    store = tmp_path / "store"
    _seed(store)
    adapter = source_module.ArtifactStoreSnapshotSource(store)

    with pytest.raises(graph_reader.HistoricalProjectGraphError) as caught:
        adapter.get_project_graph(*parts)

    assert caught.value.status_code == 404
    assert caught.value.code == "trial_not_found"
    assert str(tmp_path) not in str(caught.value)


def test_error_bodies_never_expose_absolute_paths(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _seed(store)
    client = _client(store)

    for identifier in ("missing", "..", "a\\b"):
        res = client.get(f"/trials/{TARGET}/{RUN}/{identifier}/project-graph")
        assert str(tmp_path) not in res.text
        assert "/" not in res.json().get("detail", "")
