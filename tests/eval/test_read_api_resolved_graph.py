"""Resolved L0/L1 graph resolution across schema v1 and v2 (unified workspace).

The resolved graph prefers the immutable schema-v2 capture a Trial wrote beside
its manifest, and otherwise queries the configured agent for the matching
instance's *current* project graph, clearly labelled as not captured. A
network seam is injected so no test opens a socket.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from orchestrator import project_artifacts as artifact_catalog
from orchestrator import project_graph as artifact_graph
from orchestrator import store as artifact_store
from orchestrator.files import FileStore
from read_api import resolved_graph as resolved
from read_api.resolved import TrialContext

TARGET = "comfyui-1"
RUN = "run-a"
TRIAL = "t1"
PROJECT_ID = "c0641257-a1a9-4e13-acee-6effa28311f5"
INSTANCE = "eval-server-1"
CAPTURED_AT = "2024-01-01T00:00:00+00:00"
COPIED_AT = "2024-01-01T00:00:00+00:00"


def _graph_payload(project_id: str = PROJECT_ID, *, nodes: int = 2, links: int = 1) -> dict:
    return {
        "project_id": project_id,
        "nodes": [
            {"id": f"n{i}", "name": f"n{i}", "type": "L1Service", "properties": {}}
            for i in range(nodes)
        ],
        "links": [
            {"source": "n0", "target": "n1", "type": "CONNECTS"} for _ in range(links)
        ],
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


class FakeGraphClient:
    """The injected network seam: records calls, returns or raises on demand."""

    def __init__(self, payload: object = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[str] = []

    def get_graph(self, project_id: str) -> object:
        self.calls.append(project_id)
        if self.error is not None:
            raise self.error
        return self.payload


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


def _write_v2_trial(store: Path, payload: dict) -> Path:
    trial_dir = store / TARGET / RUN / TRIAL
    trial_dir.mkdir(parents=True)
    files = FileStore()
    artifacts = artifact_catalog.collect_project_artifacts(
        trial_dir, PROJECT_ID, files=files
    )
    capture = artifact_graph.capture_project_graph(
        payload,
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
        graph_node_count=capture.node_count,
        graph_link_count=capture.link_count,
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


# --- captured precedence --------------------------------------------------------


def test_captured_v2_graph_wins_without_querying_the_agent(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v2_trial(store, _graph_payload())
    client = FakeGraphClient(_graph_payload(nodes=9, links=9))

    result = resolved.resolve_graph(store, _context(), client=client)
    assert result.status == "available"
    assert result.source == resolved.TRIAL_SNAPSHOT
    assert result.captured_at == CAPTURED_AT
    assert len(result.graph["nodes"]) == 2
    assert result.fallback_reason is None
    assert client.calls == []


def test_resolved_captured_body_has_no_host_path(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v2_trial(store, _graph_payload())
    body = resolved.graph_response(resolved.resolve_graph(store, _context(), client=None))
    assert body["status"] == "available"
    assert body["source"] == "trial_snapshot"
    assert body["project_id"] == PROJECT_ID
    assert body["captured_at"] == CAPTURED_AT
    assert str(tmp_path) not in json.dumps(body)


# --- current-graph fallback -----------------------------------------------------


def test_v1_matching_instance_queries_current_graph(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    client = FakeGraphClient(_graph_payload())

    result = resolved.resolve_graph(store, _context(), client=client)
    assert result.status == "available"
    assert result.source == resolved.PROJECT_STORAGE
    assert result.fallback_reason == "project_graph_unavailable"
    assert result.captured_at is None
    assert client.calls == [PROJECT_ID]


def test_two_trials_sharing_a_project_share_current_graph(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    client = FakeGraphClient(_graph_payload())
    first = resolved.resolve_graph(store, _context(), client=client)
    second = resolved.resolve_graph(store, _context(), client=client)
    assert first.source == second.source == resolved.PROJECT_STORAGE
    assert first.graph == second.graph
    assert client.calls == [PROJECT_ID, PROJECT_ID]


@pytest.mark.parametrize(
    "context",
    [
        _context(instance_id="other", eligible=False),
        _context(project_id=None, eligible=False),
    ],
)
def test_ineligible_context_never_queries_the_agent(
    tmp_path: Path, context: TrialContext
) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    client = FakeGraphClient(_graph_payload())
    result = resolved.resolve_graph(store, context, client=client)
    assert result.status == "unavailable"
    assert result.source == resolved.PROJECT_STORAGE
    assert client.calls == []


def test_agent_404_is_reported_as_not_found(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    client = FakeGraphClient(error=resolved.ProjectGraphClientError(resolved.REASON_NOT_FOUND))
    result = resolved.resolve_graph(store, _context(), client=client)
    assert result.status == "unavailable"
    assert result.reason == resolved.REASON_NOT_FOUND
    assert result.graph is None


def test_timeout_is_reported_as_a_timeout(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    client = FakeGraphClient(error=resolved.ProjectGraphClientError(resolved.REASON_TIMEOUT))
    result = resolved.resolve_graph(store, _context(), client=client)
    assert result.status == "unavailable"
    assert result.reason == resolved.REASON_TIMEOUT


def test_empty_graph_is_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    client = FakeGraphClient(_graph_payload(nodes=0, links=0))
    result = resolved.resolve_graph(store, _context(), client=client)
    assert result.status == "unavailable"
    assert result.reason == "project_graph_empty"
    assert result.graph is None


def test_non_mapping_body_is_invalid(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    client = FakeGraphClient(["not", "a", "mapping"])
    result = resolved.resolve_graph(store, _context(), client=client)
    assert result.status == "unavailable"
    assert result.reason == "project_graph_invalid"


def test_invalid_graph_shape_is_invalid(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    client = FakeGraphClient({"project_id": PROJECT_ID, "nodes": "no", "links": []})
    result = resolved.resolve_graph(store, _context(), client=client)
    assert result.status == "unavailable"
    assert result.reason == "project_graph_invalid"


def test_missing_client_is_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    result = resolved.resolve_graph(store, _context(), client=None)
    assert result.status == "unavailable"
    assert result.reason == "project_graph_unavailable"


# --- corrupt captured graph -----------------------------------------------------


def test_corrupt_capture_falls_back_with_stable_reason(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _write_v2_trial(store, _graph_payload())
    graph_file = trial_dir / artifact_graph.PROJECT_GRAPH_FILENAME
    graph_file.write_bytes(b'{"project_id": "tampered", "nodes": [], "links": []}\n')
    client = FakeGraphClient(_graph_payload(nodes=3, links=2))

    result = resolved.resolve_graph(store, _context(), client=client)
    assert result.source == resolved.PROJECT_STORAGE
    assert result.fallback_reason == "project_graph_digest_mismatch"
    assert len(result.graph["nodes"]) == 3
    assert client.calls == [PROJECT_ID]


# --- graph read timeout and distinguishable errors ------------------------------


class _FakeResponse:
    """A minimal `urlopen` response: a context manager with a bounded read."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, count: int = -1) -> bytes:
        return self._body if count < 0 else self._body[:count]


def _opener(response: object = None, error: Exception | None = None):
    seen: dict[str, object] = {}

    def open_(request: object, timeout: object = None):
        seen["timeout"] = timeout
        if error is not None:
            raise error
        return response

    return open_, seen


def test_graph_timeout_defaults_and_clamps_invalid_values() -> None:
    parse = resolved.resolve_graph_timeout

    assert resolved.DEFAULT_TIMEOUT_SECONDS == 20.0
    assert parse(None) == 20.0
    assert parse("") == 20.0
    assert parse("1") == 1.0
    assert parse("30") == 30.0
    assert parse("7.5") == 7.5
    for bad in ("0", "-5", "31", "1e9", "nan", "inf", "-inf", "abc", "  "):
        assert parse(bad) == 20.0, bad


def test_http_client_honors_the_configured_timeout_and_reads_a_slow_response() -> None:
    opener, seen = _opener(_FakeResponse(json.dumps(_graph_payload()).encode()))
    client = resolved.HttpProjectGraphClient(
        "http://agent:8080", timeout=20.0, opener=opener
    )

    payload = client.get_graph(PROJECT_ID)

    assert payload["project_id"] == PROJECT_ID
    assert seen["timeout"] == 20.0
    assert client.timeout == 20.0


def test_http_client_maps_timeout_404_5xx_transport_and_invalid() -> None:
    def reason_for(**kwargs: object) -> str:
        opener, _ = _opener(**kwargs)
        client = resolved.HttpProjectGraphClient("http://agent:8080", opener=opener)
        with pytest.raises(resolved.ProjectGraphClientError) as excinfo:
            client.get_graph(PROJECT_ID)
        return excinfo.value.reason

    from urllib.error import HTTPError, URLError

    assert reason_for(error=TimeoutError("timed out")) == resolved.REASON_TIMEOUT
    assert reason_for(error=URLError(TimeoutError("timed out"))) == resolved.REASON_TIMEOUT
    assert reason_for(error=URLError("connection refused")) == resolved.REASON_TRANSPORT
    assert (
        reason_for(error=HTTPError("http://agent:8080/x", 404, "not found", {}, None))
        == resolved.REASON_NOT_FOUND
    )
    assert (
        reason_for(error=HTTPError("http://agent:8080/x", 503, "unavailable", {}, None))
        == resolved.REASON_HTTP_ERROR
    )
    assert reason_for(response=_FakeResponse(b"{not json")) == resolved.REASON_INVALID
    assert reason_for(response=_FakeResponse(b"[1, 2, 3]")) == resolved.REASON_INVALID


def test_http_client_rejects_an_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolved, "MAX_GRAPH_BYTES", 8)
    opener, _ = _opener(_FakeResponse(b"x" * 9))
    client = resolved.HttpProjectGraphClient("http://agent:8080", opener=opener)

    with pytest.raises(resolved.ProjectGraphClientError) as excinfo:
        client.get_graph(PROJECT_ID)

    assert excinfo.value.reason == resolved.REASON_INVALID


@pytest.mark.parametrize(
    "code",
    [
        "REASON_TIMEOUT",
        "REASON_NOT_FOUND",
        "REASON_HTTP_ERROR",
        "REASON_TRANSPORT",
        "REASON_INVALID",
    ],
)
def test_resolver_preserves_each_client_error_code(
    tmp_path: Path, code: str
) -> None:
    store = tmp_path / "store"
    _write_v1_trial(store)
    reason = getattr(resolved, code)
    client = FakeGraphClient(error=resolved.ProjectGraphClientError(reason))

    result = resolved.resolve_graph(store, _context(), client=client)

    assert result.status == "unavailable"
    assert result.reason == reason
    payload = resolved.graph_response(result)
    assert payload["reason"] == reason
    # No host path or raw exception text ever reaches the body.
    assert "/" not in reason
    assert str(tmp_path) not in repr(payload)
