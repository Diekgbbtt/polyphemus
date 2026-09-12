"""Per-project SQLite store: immutable artifacts, content-addressed bodies."""
from __future__ import annotations

import sqlite3

import pytest

from kali.http_history.models import (
    CaptureContext,
    HttpArtifact,
    RequestRecord,
    ResponseRecord,
)
from kali.http_history.store import ArtifactImmutableError, HttpHistoryStore


def _artifact(artifact_id: str = "http_01J0000000000000000000000A", body: bytes = b"hello") -> HttpArtifact:
    import hashlib

    digest = hashlib.sha256(body).hexdigest()
    return HttpArtifact(
        artifact_id=artifact_id,
        project_id="proj-1",
        capture_context=CaptureContext(exec_id="e1", session_id="s1"),
        request=RequestRecord(
            method="POST",
            url="https://target.example/login",
            headers=[["content-type", "text/plain"]],
            body_ref=f"sha256:{digest}",
            body_size=len(body),
        ),
        response=ResponseRecord(status=200, reason="OK"),
        created_at=1000.0,
    )


def _bodies(artifact: HttpArtifact) -> dict[str, bytes]:
    return {artifact.request.body_ref: b"hello"}


def test_record_then_get_raw_roundtrips(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact = _artifact()
    store.record(artifact, bodies={artifact.request.body_ref: b"hello"})
    assert store.get_raw(artifact.artifact_id) == artifact


def test_body_is_content_addressed_on_disk(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact = _artifact()
    store.record(artifact, bodies={artifact.request.body_ref: b"hello"})
    blob = tmp_path / "proj-1" / "http-history" / "bodies" / (
        artifact.request.body_ref.split(":", 1)[1] + ".blob"
    )
    assert blob.read_bytes() == b"hello"
    assert store.get_body(artifact.request.body_ref) == b"hello"


def test_recording_an_existing_artifact_id_is_rejected(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact = _artifact()
    store.record(artifact, bodies=_bodies(artifact))
    with pytest.raises(ArtifactImmutableError):
        store.record(artifact, bodies=_bodies(artifact))


def test_record_is_invisible_until_bodies_are_durable(tmp_path, monkeypatch):
    """A crash between body write and record insert must leave no artifact."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact = _artifact()

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "_insert_record", boom)
    with pytest.raises(RuntimeError):
        store.record(artifact, bodies={artifact.request.body_ref: b"hello"})
    assert store.get_raw(artifact.artifact_id) is None
    # The body blob is durable and deduplicated, but nothing references it.
    assert store.get_body(artifact.request.body_ref) == b"hello"


def test_rejects_invalid_project_id(tmp_path):
    for bad in ("../escape", "a/b", "", " spaces ", "x" * 129):
        with pytest.raises(ValueError):
            HttpHistoryStore(tmp_path, bad)


def test_sqlite_uses_wal(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_projects_are_isolated_on_disk(tmp_path):
    artifact = _artifact()
    HttpHistoryStore(tmp_path, "proj-1").record(artifact, bodies=_bodies(artifact))
    other = HttpHistoryStore(tmp_path, "proj-2")
    assert other.get_raw("http_01J0000000000000000000000A") is None


def test_store_status_reports_paths_and_counts(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact = _artifact()
    store.record(artifact, bodies=_bodies(artifact))
    status = store.status()
    assert status["ok"] is True
    assert status["artifact_count"] == 1
    assert status["schema_version"] == "http-artifact/v1"
