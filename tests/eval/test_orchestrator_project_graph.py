"""The deterministic final-project-graph capture (real eval project artifacts, Task 2).

`project-graph.json` is the historical L0/L1 graph a Trial captured before its
instance could be torn down. These tests pin the `GraphData` contract check,
the deterministic normalization (node/link ordering, canonical JSON bytes), and
the content digest, all without leaking response content or host paths.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orchestrator.files import FileStore
from orchestrator.project_graph import (
    PROJECT_GRAPH_FILENAME,
    ProjectGraphCapture,
    ProjectGraphError,
    capture_project_graph,
    normalize_project_graph,
)

PROJECT_ID = "pid"


def _valid_graph() -> dict:
    """A valid `GraphData` payload with deliberately shuffled order and extras."""
    return {
        "project_id": PROJECT_ID,
        "nodes": [
            {
                "id": "n2",
                "name": "Endpoint b",
                "type": "Endpoint",
                "properties": {"z": 1, "a": 2},
                "extra": "kept",
            },
            {
                "id": "n1",
                "name": "Service a",
                "type": "L1Service",
                "properties": {"b": [2, 1], "a": {"y": 1, "x": 2}},
            },
        ],
        "links": [
            {"source": "n2", "target": "n1", "type": "CONNECTS", "properties": {"k": 1}},
            {"source": "n1", "target": "n2", "type": "USES"},
            {"source": "n1", "target": "n1", "type": "USES"},
        ],
        "extra_top": {"kept": True},
    }


def test_normalizes_graph_order_and_canonical_digest(tmp_path: Path) -> None:
    normalized = normalize_project_graph(_valid_graph(), project_id=PROJECT_ID)

    assert [node["id"] for node in normalized["nodes"]] == ["n1", "n2"]
    assert [
        (link["source"], link["target"], link["type"]) for link in normalized["links"]
    ] == [
        ("n1", "n1", "USES"),
        ("n1", "n2", "USES"),
        ("n2", "n1", "CONNECTS"),
    ]
    # Extra fields returned by the API survive normalization.
    assert normalized["extra_top"] == {"kept": True}
    assert normalized["nodes"][1]["extra"] == "kept"
    assert normalized["links"][2]["properties"] == {"k": 1}
    assert normalized["project_id"] == PROJECT_ID

    destination = tmp_path / "runs" / PROJECT_GRAPH_FILENAME
    capture = capture_project_graph(
        _valid_graph(),
        project_id=PROJECT_ID,
        captured_at="2026-10-03T00:00:00Z",
        destination=destination,
        files=FileStore(),
    )

    data = destination.read_bytes()
    expected_text = json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    assert data.decode("utf-8") == expected_text + "\n"
    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    assert isinstance(capture, ProjectGraphCapture)
    assert capture.status == "available"
    assert capture.captured_at == "2026-10-03T00:00:00Z"
    assert capture.failure is None
    assert capture.node_count == 2
    assert capture.link_count == 3
    assert capture.sha256 == hashlib.sha256(data).hexdigest()
    assert capture.to_dict() == {
        "status": "available",
        "captured_at": "2026-10-03T00:00:00Z",
        "sha256": hashlib.sha256(data).hexdigest(),
        "node_count": 2,
        "link_count": 3,
        "failure": None,
    }

    # Identical content in a different order hashes to the same bytes.
    shuffled = _valid_graph()
    shuffled["nodes"].reverse()
    shuffled["links"].reverse()
    other = tmp_path / "runs" / "other" / PROJECT_GRAPH_FILENAME
    other_capture = capture_project_graph(
        shuffled,
        project_id=PROJECT_ID,
        captured_at="2026-10-03T00:00:00Z",
        destination=other,
        files=FileStore(),
    )
    assert other.read_bytes() == data
    assert other_capture.sha256 == capture.sha256


def test_rejects_graph_for_another_project() -> None:
    canary = "CANARY-OTHER-PROJECT"
    with pytest.raises(ProjectGraphError) as excinfo:
        normalize_project_graph(
            {"project_id": canary, "nodes": [], "links": []}, project_id=PROJECT_ID
        )
    assert canary not in str(excinfo.value)

    with pytest.raises(ProjectGraphError) as excinfo:
        normalize_project_graph({"nodes": [], "links": []}, project_id=PROJECT_ID)
    assert "project_id" in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"project_id": PROJECT_ID, "nodes": None, "links": []},
        {"project_id": PROJECT_ID, "nodes": {"id": "n1"}, "links": []},
        {"project_id": PROJECT_ID, "nodes": [], "links": None},
        {"project_id": PROJECT_ID, "nodes": [], "links": {"source": "a"}},
        {"project_id": PROJECT_ID, "nodes": ["CANARY-NODE"], "links": []},
        {
            "project_id": PROJECT_ID,
            "nodes": [{"name": "n", "type": "Endpoint", "properties": {}}],
            "links": [],
        },
        {
            "project_id": PROJECT_ID,
            "nodes": [{"id": 1, "name": "n", "type": "Endpoint", "properties": {}}],
            "links": [],
        },
        {
            "project_id": PROJECT_ID,
            "nodes": [{"id": "n", "type": "Endpoint", "properties": {}}],
            "links": [],
        },
        {
            "project_id": PROJECT_ID,
            "nodes": [{"id": "n", "name": "n", "type": 3, "properties": {}}],
            "links": [],
        },
        {
            "project_id": PROJECT_ID,
            "nodes": [{"id": "n", "name": "n", "type": "Endpoint"}],
            "links": [],
        },
        {
            "project_id": PROJECT_ID,
            "nodes": [{"id": "n", "name": "n", "type": "Endpoint", "properties": []}],
            "links": [],
        },
        {"project_id": PROJECT_ID, "nodes": [], "links": ["CANARY-LINK"]},
        {
            "project_id": PROJECT_ID,
            "nodes": [],
            "links": [{"target": "b", "type": "USES"}],
        },
        {
            "project_id": PROJECT_ID,
            "nodes": [],
            "links": [{"source": 1, "target": "b", "type": "USES"}],
        },
        {
            "project_id": PROJECT_ID,
            "nodes": [],
            "links": [{"source": "a", "target": "b"}],
        },
        {
            "project_id": PROJECT_ID,
            "nodes": [],
            "links": [{"source": "a", "target": "b", "type": None}],
        },
    ],
)
def test_rejects_malformed_nodes_and_links(payload: dict) -> None:
    with pytest.raises(ProjectGraphError) as excinfo:
        normalize_project_graph(payload, project_id=PROJECT_ID)
    assert "CANARY" not in str(excinfo.value)
