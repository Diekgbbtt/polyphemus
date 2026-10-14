"""Per-project SQLite store: immutable artifacts, content-addressed bodies."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from kali.http_history.models import (
    CaptureContext,
    HttpArtifact,
    RequestRecord,
    ResponseRecord,
)
from kali.http_history.store import (
    ArtifactImmutableError,
    CorruptRecordError,
    HttpHistoryStore,
)


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


from tests.kali.test_http_history_search import _seed


def test_attribute_indexes_are_covering(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    sql = {
        row["name"]: (row["sql"] or "")
        for row in store._conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index'"
        )
    }
    assert "artifact_id" in sql["attributes_text_cov"]
    assert "artifact_id" in sql["attributes_numeric_cov"]
    assert "attributes_text" not in sql, "the non-covering index must be dropped"
    assert "attributes_numeric" not in sql


def test_optimize_runs_analyze(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    store.optimize()
    assert store._conn.execute("SELECT count(*) FROM sqlite_stat1").fetchone()[0] > 0


def _fm_artifact(i: int, url: str = "https://target.example/x") -> HttpArtifact:
    return HttpArtifact(
        artifact_id=f"http_01J000000000000000002{i:04d}A",
        project_id="proj-1",
        capture_context=CaptureContext(exec_id="e1", session_id="s1"),
        request=RequestRecord(method="GET", url=url),
        response=ResponseRecord(status=200, reason="OK"),
        created_at=1000.0 + i,
    )


def _insert_raw_row(store: HttpHistoryStore, artifact_id: str, record_json: str) -> None:
    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "INSERT INTO flows (artifact_id, project_id, created_at,"
        " schema_version, record_json) VALUES (?,?,?,?,?)",
        (artifact_id, "proj-1", 500.0, "v1", record_json),
    )
    conn.commit()
    conn.close()


def test_concurrent_readers_and_writer_share_one_connection(tmp_path):
    """FM-C red loop: the MCP server runs tool calls on worker threads against
    one cached store per project. A lock-free read racing a write surfaced
    SQLITE_MISUSE as 'bad parameter or other API misuse' (plus transient
    tuple-index and validation errors) - every read must serialize."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    for i in range(5):
        store.record(_fm_artifact(i), bodies={})
    errors: list[str] = []
    done = threading.Event()

    def writer():
        for i in range(5, 55):
            try:
                store.record(_fm_artifact(i, f"https://target.example/w{i}"), bodies={})
            except Exception as exc:  # noqa: BLE001 - collected, asserted below
                errors.append(f"{type(exc).__name__}: {exc}")
        done.set()

    def reader():
        while not done.is_set():
            try:
                store.text_search("/w", limit=20)
                store.search([], limit=20)
            except Exception as exc:  # noqa: BLE001 - collected, asserted below
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(store.search([], limit=100).artifacts) == 55


def test_search_skips_unreadable_rows_fail_open(tmp_path):
    """FM-C: one corrupt stored row never kills the page - the search
    continues with the rest, and an all-corrupt page is empty."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    store.record(_fm_artifact(1), bodies={})
    store.record(_fm_artifact(2), bodies={})
    _insert_raw_row(store, "http_CORRUPT", "")
    page = store.search([], limit=50)
    assert [a.artifact_id for a in page.artifacts] == [
        _fm_artifact(1).artifact_id,
        _fm_artifact(2).artifact_id,
    ]
    text_page = store.text_search("target", limit=50)
    assert len(text_page.artifacts) == 2


def test_get_raw_unreadable_row_raises_corrupt_record(tmp_path):
    """FM-C: the single-record read reports an unreadable record as corrupt,
    never as missing."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    _insert_raw_row(store, "http_CORRUPT", "")
    with pytest.raises(CorruptRecordError):
        store.get_raw("http_CORRUPT")
    assert store.get_raw("http_MISSING") is None


def test_gc_blobs_defers_when_a_row_is_unreadable(tmp_path):
    """FM-C fail-safe: an unreadable row still counts as a potential
    referrer, so blob deletion is skipped rather than risk bytes a corrupt
    record may reference."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact = _artifact(body=b"hello")
    store.record(artifact, _bodies(artifact))
    _insert_raw_row(store, "http_CORRUPT", "")
    assert store._gc_blobs() == 0
    blob = next(store.bodies_dir.glob("*.blob"))
    assert blob.exists()
