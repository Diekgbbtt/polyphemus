"""The production capture -> materialize -> HTTP acceptance flow.

A realistic temporary data root is run through the real materializer, then read
through the real FastAPI app: the `/snapshot` summary, the historical graph,
the artifact inventory, one semantic detail, and the streamed raw bytes must
all agree on the project identity and digests.

The second fixture captures no graph: the core verdict stays readable while the
historical graph and the artifact inventory are both unavailable.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from orchestrator import files as artifact_files
from orchestrator import project_graph as artifact_graph
from orchestrator import store as artifact_store
from read_api import app as app_module
from read_api import source as source_module

EVAL_SHA = "eval-sha-1"
FP = "fp-1"
PROJECT_ID = "pid"
TARGET = "jetlinks-1"
RUN = "runner-1"
TRIAL = "trial-1"
CAPTURED_AT = "2024-05-05T00:00:00+00:00"

_SOURCES = {
    "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml": b"hunt_id: H-1\nunit_id: U-1\n",
    "pid/hunting/hunter/test-specs/fault-a/produced/spec.yaml": b"target_identity: {host: app}\n",
    "pid/hunting/test-executor-pod/spec-1/variants/variant.yaml": b"variant: 1\n",
    "pid/hunting/test-executor-pod/spec-1/experiment-log/order-0.yaml": b"order: 0\n",
    "pid/hunting/test-executor-pod/spec-1/export.yaml": b"verdict: identified\n",
    "pid/skills/authn/SKILL.md": b"# Authn skill\n",
    "pid/skills/authn/references/notes.md": b"# Notes\n",
    "pid/skills/authn/scripts/run.sh": b"echo run\n",
    "pid/skills/authn/assets/logo.bin": b"\x89PNG\r\n\x1a\n\x00\x01",
}


def _write(root: Path, relative: str, data: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _graph_payload() -> dict:
    return {
        "project_id": PROJECT_ID,
        "nodes": [
            {"id": "n2", "name": "endpoint", "type": "Endpoint", "properties": {"z": 1}},
            {"id": "n1", "name": "service", "type": "L1Service", "properties": {}},
        ],
        "links": [{"source": "n2", "target": "n1", "type": "CONNECTS"}],
    }


def _build(tmp_path: Path, *, with_graph: bool) -> tuple[Path, Path]:
    """Materialize one real Trial; return `(store_dir, published_trial_dir)`."""
    data_root = tmp_path / "instances" / "arm-a" / "data"
    for relative, data in _SOURCES.items():
        _write(data_root, relative, data)

    trial_dir = tmp_path / "runs" / TARGET / TRIAL
    trial_dir.mkdir(parents=True)
    verdicts = [
        {
            "vuln_id": "CVE-1",
            "identified": "identified",
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
    ]
    (trial_dir / "verdicts.yaml").write_text(
        yaml.safe_dump(verdicts, sort_keys=False), encoding="utf-8"
    )

    record = {
        "trial_id": TRIAL,
        "instance_id": "arm-a",
        "target_id": TARGET,
        "target_run_id": RUN,
        "project_id": PROJECT_ID,
        "start_phase": "recon",
        "terminal": "complete",
        "phases": [],
        "eval_sha": EVAL_SHA,
        "stack_fingerprint": FP,
    }
    if with_graph:
        capture = artifact_graph.capture_project_graph(
            _graph_payload(),
            project_id=PROJECT_ID,
            captured_at=CAPTURED_AT,
            destination=trial_dir / artifact_graph.PROJECT_GRAPH_FILENAME,
            files=artifact_files.FileStore(),
        )
        record["project_graph"] = {
            "status": "available",
            "captured_at": CAPTURED_AT,
            "sha256": capture.sha256,
            "node_count": 2,
            "link_count": 1,
            "failure": None,
        }
    (trial_dir / "trial.yaml").write_text(
        yaml.safe_dump(record, sort_keys=False), encoding="utf-8"
    )

    store_dir = tmp_path / "store"
    published = artifact_store.materialize(
        trial_dir,
        store=store_dir,
        data_root=data_root,
        files=artifact_files.FileStore(),
    )
    return store_dir, published


def _client(store_dir: Path) -> TestClient:
    return TestClient(
        app_module.create_app(
            lambda: source_module.ArtifactStoreSnapshotSource(store_dir)
        )
    )


def _trial(snapshot: dict) -> dict:
    return next(
        trial
        for trial in snapshot["trials"]
        if trial["target_id"] == TARGET
        and trial["target_run_id"] == RUN
        and trial["trial_id"] == TRIAL
    )


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


# --- the available flow ---------------------------------------------------------


def test_available_flow_agrees_on_identity_and_digests(tmp_path: Path) -> None:
    store_dir, published = _build(tmp_path, with_graph=True)
    client = _client(store_dir)

    snapshot = client.get("/snapshot")
    assert snapshot.status_code == 200
    assert str(tmp_path) not in snapshot.text
    trial = _trial(snapshot.json())
    assert trial["availability"] == "complete"
    assert trial["artifact_summary"] == {"status": "available", "hunting": 5, "skills": 4}
    assert trial["project_graph_summary"] == {
        "status": "available",
        "nodes": 2,
        "links": 1,
        "captured_at": CAPTURED_AT,
    }
    # `/snapshot` stays lightweight: no inventory entries or graph bodies.
    blob = json.dumps(snapshot.json())
    assert "relative_path" not in blob
    assert "artifact_id" not in blob

    manifest = yaml.safe_load(
        (published / "run-manifest.yaml").read_text(encoding="utf-8")
    )

    graph = client.get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")
    assert graph.status_code == 200
    graph_body = graph.json()
    assert graph_body["status"] == "available"
    assert graph_body["sha256"] == manifest["project_graph"]["sha256"]
    assert graph_body["graph"]["project_id"] == PROJECT_ID
    assert [node["id"] for node in graph_body["graph"]["nodes"]] == ["n1", "n2"]

    inventory = client.get(f"/trials/{TARGET}/{RUN}/{TRIAL}/artifacts")
    assert inventory.status_code == 200
    inventory_body = inventory.json()
    assert inventory_body["project_id"] == PROJECT_ID
    entries = [
        entry
        for group in _walk(inventory_body["groups"])
        if isinstance(group, dict) and "entries" in group
        for entry in group["entries"]
    ]
    assert len(entries) == 9
    hunting = next(entry for entry in entries if entry["kind"] == "hunt_config")
    skills = next(entry for entry in entries if entry["kind"] == "skill_procedure")
    binary = next(entry for entry in entries if entry["kind"] == "skill_asset")

    detail = client.get(
        f"/trials/{TARGET}/{RUN}/{TRIAL}/artifacts/{hunting['artifact_id']}"
    )
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["entry"]["artifact_id"] == hunting["artifact_id"]
    assert detail_body["entry"]["sha256"] == hunting["sha256"]
    assert detail_body["preview"]["parsed"] == {
        "hunt_id": "H-1",
        "unit_id": "U-1",
    }

    content = client.get(
        f"/trials/{TARGET}/{RUN}/{TRIAL}/artifacts/{hunting['artifact_id']}/content"
    )
    assert content.status_code == 200
    source_bytes = _SOURCES[
        "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml"
    ]
    assert content.content == source_bytes
    assert hashlib.sha256(content.content).hexdigest() == hunting["sha256"]
    assert content.headers["content-length"] == str(hunting["size_bytes"])
    # Safe text/YAML is inline; binary/active content is an attachment.
    assert content.headers["content-disposition"].startswith("inline")

    # A project-authored skill and a binary asset resolve through the same store.
    skill_detail = client.get(
        f"/trials/{TARGET}/{RUN}/{TRIAL}/artifacts/{skills['artifact_id']}"
    )
    assert skill_detail.status_code == 200
    assert skill_detail.json()["entry"]["representation"] == "markdown"

    binary_detail = client.get(
        f"/trials/{TARGET}/{RUN}/{TRIAL}/artifacts/{binary['artifact_id']}"
    )
    assert binary_detail.status_code == 200
    assert binary_detail.json()["preview"]["text"] is None
    binary_content = client.get(
        f"/trials/{TARGET}/{RUN}/{TRIAL}/artifacts/{binary['artifact_id']}/content"
    )
    assert binary_content.content == _SOURCES["pid/skills/authn/assets/logo.bin"]
    assert "attachment" in binary_content.headers["content-disposition"]


# --- the unavailable flow -------------------------------------------------------


def test_unavailable_flow_keeps_the_core_verdict(tmp_path: Path) -> None:
    store_dir, published = _build(tmp_path, with_graph=False)
    client = _client(store_dir)

    snapshot = client.get("/snapshot")
    assert snapshot.status_code == 200
    assert str(tmp_path) not in snapshot.text
    trial = _trial(snapshot.json())
    # The core eval published and stayed readable.
    assert trial["availability"] == "complete"
    assert [v["vuln_id"] for v in trial["verdicts"]] == ["CVE-1"]
    # The auxiliary snapshot is unavailable, consistently for both surfaces.
    assert trial["artifact_summary"]["status"] == "project_snapshot_unavailable"
    assert trial["project_graph_summary"]["status"] == "project_snapshot_unavailable"
    assert not (published / "project-graph.json").exists()

    graph = client.get(f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph")
    assert graph.status_code == 409
    assert graph.json()["detail"] == "project_graph_unavailable"
    assert str(tmp_path) not in graph.text

    inventory = client.get(f"/trials/{TARGET}/{RUN}/{TRIAL}/artifacts")
    assert inventory.status_code == 409
    assert inventory.json()["detail"] == "project_snapshot_unavailable"
    assert str(tmp_path) not in inventory.text


def test_fixture_responses_carry_no_absolute_paths(tmp_path: Path) -> None:
    store_dir, _ = _build(tmp_path, with_graph=True)
    client = _client(store_dir)

    for path in (
        "/snapshot",
        f"/trials/{TARGET}/{RUN}/{TRIAL}/project-graph",
        f"/trials/{TARGET}/{RUN}/{TRIAL}/artifacts",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert str(tmp_path) not in response.text
