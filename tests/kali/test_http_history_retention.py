"""Retention, purge and blob garbage collection."""
from __future__ import annotations

import json

from kali.http_history.models import CaptureContext, HttpArtifact, RequestRecord, ResponseRecord
from kali.http_history.store import HttpHistoryStore


def _record(store: HttpHistoryStore, artifact_id: str, *, created_at: float, body: bytes) -> str:
    import hashlib

    ref = f"sha256:{hashlib.sha256(body).hexdigest()}"
    store.record(
        HttpArtifact(
            artifact_id=artifact_id,
            project_id=store.project_id,
            capture_context=CaptureContext(),
            request=RequestRecord(method="GET", url="https://t/", body_ref=ref, body_size=len(body)),
            response=ResponseRecord(status=200),
            created_at=created_at,
        ),
        bodies={ref: body},
    )
    return ref


def test_purge_older_than_removes_only_old_rows(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _record(store, "http_01J0000000000000000000000A", created_at=100.0, body=b"old")
    _record(store, "http_01J0000000000000000000000B", created_at=10_000.0, body=b"new")
    removed = store.purge_older_than(retention_s=100, now=10_100.0)
    assert removed == 1
    assert store.get_raw("http_01J0000000000000000000000A") is None
    assert store.get_raw("http_01J0000000000000000000000B") is not None
    assert store.status()["artifact_count"] == 1


def test_purge_older_than_garbage_collects_unreferenced_blobs(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    ref = _record(store, "http_01J0000000000000000000000A", created_at=100.0, body=b"old")
    store.purge_older_than(retention_s=1, now=10_000.0)
    assert store.get_body(ref) is None
    assert store.status()["body_count"] == 0


def test_project_purge_removes_rows_and_blobs(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _record(store, "http_01J0000000000000000000000A", created_at=1.0, body=b"a")
    result = store.purge()
    assert result["artifacts_removed"] == 1
    assert store.status()["artifact_count"] == 0
    assert store.status()["body_count"] == 0


def test_project_byte_cap_evicts_oldest_first(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _record(store, "http_01J0000000000000000000000A", created_at=1.0, body=b"x" * 100)
    _record(store, "http_01J0000000000000000000000B", created_at=2.0, body=b"y" * 100)
    removed = store.enforce_project_max_bytes(150)
    assert removed == 1
    assert store.get_raw("http_01J0000000000000000000000A") is None
    assert store.get_raw("http_01J0000000000000000000000B") is not None


def test_deletions_record_their_reason(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _record(store, "http_01J0000000000000000000000A", created_at=1.0, body=b"a")
    store.purge_older_than(retention_s=0, now=10.0)
    audit = json.loads(store.last_purge())
    assert audit["reason"] == "retention"
    assert audit["artifacts_removed"] == 1
