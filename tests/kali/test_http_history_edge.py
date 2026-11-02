"""Seam under test: the HTTP-history ingest edge over its real HTTP surface.

Spec: `docs/design/steel-crawl-spec.md` section 10.2.

The edge is a separate process, authenticated by a bearer token, bounded to 100
artifacts or 8 MiB, and idempotent through `record_if_absent`. The unit test
starts the real threaded server on a loopback port and uses a fake store; one
test exercises the real store's idempotency.
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from kali.http_history.edge import create_edge_server
from kali.http_history.models import HttpArtifact
from kali.http_history.store import ArtifactImmutableError, HttpHistoryStore

TOKEN = "edge-token"


class FakeStore:
    """A store that records calls and returns a scripted duplicate outcome."""

    def __init__(self, duplicates: set[str] | None = None) -> None:
        self.duplicates = duplicates or set()
        self.calls: list[tuple[HttpArtifact, dict[str, bytes] | None]] = []

    def record_if_absent(
        self, artifact: HttpArtifact, bodies: dict[str, bytes] | None = None
    ) -> bool:
        self.calls.append((artifact, bodies))
        return artifact.artifact_id not in self.duplicates


@pytest.fixture
def edge() -> Iterator[tuple[Any, FakeStore]]:
    store = FakeStore(duplicates={"http_dup"})
    server = create_edge_server(
        lambda project_id: store,
        TOKEN,
        "127.0.0.1",
        0,
        max_artifacts=2,
        max_bytes=4096,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def url(server: Any) -> str:
    return f"http://127.0.0.1:{server.server_port}/v1/ingest"


def payload(*artifact_ids: str) -> dict[str, Any]:
    return {
        "project_id": "proj-1",
        "run_id": "run-1",
        "artifacts": [
            {"artifact_id": artifact_id, "project_id": "proj-1"}
            for artifact_id in artifact_ids
        ],
        "bodies": [],
    }


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_the_edge_counts_created_and_duplicates(edge):
    server, store = edge

    response = httpx.post(
        url(server), json=payload("http_1", "http_dup"), headers=auth()
    )

    assert response.status_code == 200
    assert response.json() == {
        "created": 1,
        "duplicates": 1,
        "rejected": 0,
        "errors": [],
    }
    assert [call[0].artifact_id for call in store.calls] == ["http_1", "http_dup"]


def test_the_edge_requires_the_bearer_token(edge):
    server, _ = edge

    response = httpx.post(url(server), json=payload("http_1"))

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_the_edge_rejects_too_many_artifacts(edge):
    server, _ = edge

    response = httpx.post(
        url(server), json=payload("http_1", "http_2", "http_3"), headers=auth()
    )

    assert response.status_code == 413
    assert response.json() == {"error": "too_many_artifacts"}


def test_the_edge_rejects_an_oversized_payload(edge):
    server, _ = edge
    body = json.dumps(payload("http_1")).encode("utf-8")
    body = body + b" " * (4096 - len(body) + 1)

    response = httpx.post(
        url(server),
        content=body,
        headers={**auth(), "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"error": "batch_too_large"}


def test_the_edge_rejects_a_malformed_artifact_without_failing_the_batch(edge):
    server, store = edge
    body = {
        "project_id": "proj-1",
        "run_id": "run-1",
        "artifacts": [{"bad": True}, {"artifact_id": "http_1", "project_id": "proj-1"}],
        "bodies": [],
    }

    response = httpx.post(url(server), json=body, headers=auth())

    assert response.status_code == 200
    assert response.json()["created"] == 1
    assert response.json()["rejected"] == 1
    assert response.json()["errors"]
    assert [call[0].artifact_id for call in store.calls] == ["http_1"]


def test_the_edge_decodes_the_base64_bodies(edge):
    server, store = edge
    body_bytes = b'{"ok":true}'
    digest = hashlib.sha256(body_bytes).hexdigest()
    body = payload("http_1")
    body["bodies"] = [
        {
            "sha256": digest,
            "encoding": "base64",
            "data": base64.b64encode(body_bytes).decode("ascii"),
        }
    ]

    response = httpx.post(url(server), json=body, headers=auth())

    assert response.status_code == 200
    assert store.calls[0][1] == {f"sha256:{digest}": body_bytes}


def test_the_real_store_record_if_absent_is_idempotent(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact = HttpArtifact(artifact_id="http_1", project_id="proj-1")

    assert store.record_if_absent(artifact) is True
    assert store.record_if_absent(artifact) is False
    with pytest.raises(ArtifactImmutableError):
        store.record(artifact)
