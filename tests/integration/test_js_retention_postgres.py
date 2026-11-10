import hashlib
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from polymerhus.app import config as config_module
from polymerhus.app.clients import pg


def _dsn() -> str:
    value = os.environ.get("JS_RETENTION_TEST_DSN", "").strip()
    if not value:
        pytest.skip("JS_RETENTION_TEST_DSN is not configured")
    return value


def _cleanup(dsn: str, project_id: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM js_evidence_links WHERE project_id = %s",
            (project_id,),
        )
        cur.execute(
            "DELETE FROM js_artifacts WHERE project_id = %s",
            (project_id,),
        )


def test_real_postgres_quota_concurrency_and_context_scope(monkeypatch):
    dsn = _dsn()
    monkeypatch.setattr(config_module.config, "POSTGRES_DSN", dsn)
    pg.ensure_js_retention_schema()
    pg.ensure_js_retention_schema()
    project_id = "jsret-" + uuid.uuid4().hex
    first_hash = hashlib.sha256(b"first").hexdigest()
    second_hash = hashlib.sha256(b"second").hexdigest()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(
                lambda item: pg.reserve_js_artifact(
                    project_id=project_id,
                    sha256=item[0],
                    size_bytes=6,
                    archive_ref=f"recon/js-artifacts/blobs/{item[0]}.blob",
                    quota_bytes=10,
                ),
                [(first_hash, 6), (second_hash, 6)],
            ))
        assert sorted(item["status"] for item in outcomes) == [
            "quota_exceeded",
            "reserved",
        ]

        winner = next(
            (first_hash, second_hash)[index]
            for index, item in enumerate(outcomes)
            if item["status"] == "reserved"
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            same_hash = list(pool.map(
                lambda _: pg.reserve_js_artifact(
                    project_id=project_id,
                    sha256=winner,
                    size_bytes=6,
                    archive_ref=f"recon/js-artifacts/blobs/{winner}.blob",
                    quota_bytes=10,
                ),
                range(2),
            ))
        assert same_hash[0]["status"] in {"already_reserved", "reserved"}

        assert pg.confirm_js_artifact(
            project_id=project_id,
            sha256=winner,
            size_bytes=6,
        )["state"] == "retained"
        assert pg.fail_js_artifact(
            project_id=project_id,
            sha256=winner,
            size_bytes=6,
            archive_ref=f"recon/js-artifacts/blobs/{winner}.blob",
            reason="late_failure",
        )["state"] == "retained"

        for context_ref, behavior_id in (
            ("alice", "behavior_alice"),
            ("bob", "behavior_bob"),
        ):
            pg.upsert_js_evidence_link(link={
                "link_id": "link_" + uuid.uuid4().hex,
                "project_id": project_id,
                "sha256": winner,
                "run_id": "run_test",
                "origin": "cited_read",
                "auth_context_ref": context_ref,
                "lead_id": "lead_test",
                "selector_type": "source",
                "selector_id": "source_test",
                "read_id": "read_" + context_ref,
                "start_byte": 0,
                "end_byte": 6,
                "behavior_id": behavior_id,
                "behavior_revision": 1,
                "rationale": "deterministic retention integration test",
                "status": "retained",
                "failure_reason": None,
            })

        alice = pg.js_retention_snapshot(
            project_id=project_id,
            run_id="run_test",
            auth_context_ref="alice",
            behavior_id="behavior_alice",
            behavior_revision=1,
        )
        bob = pg.js_retention_snapshot(
            project_id=project_id,
            run_id="run_test",
            auth_context_ref="bob",
            behavior_id="behavior_bob",
            behavior_revision=1,
        )
        cross = pg.js_retention_snapshot(
            project_id=project_id,
            run_id="run_test",
            auth_context_ref="alice",
            behavior_id="behavior_bob",
            behavior_revision=1,
        )
        cross_run = pg.js_retention_snapshot(
            project_id=project_id,
            run_id="other_run",
            auth_context_ref="alice",
            behavior_id="behavior_alice",
            behavior_revision=1,
        )
        assert alice["retained_count"] == bob["retained_count"] == 1
        assert cross["links"] == []
        assert cross_run["links"] == []

        pg.mark_js_artifact_unavailable(
            project_id=project_id,
            sha256=winner,
            reason="test_blob_removed",
        )
        unavailable = pg.js_retention_snapshot(
            project_id=project_id,
            run_id="run_test",
            auth_context_ref="alice",
            behavior_id="behavior_alice",
            behavior_revision=1,
        )
        assert unavailable["retained_count"] == 0
        assert unavailable["gap_count"] == 1
        assert (
            unavailable["links"][0]["artifact_failure_reason"]
            == "test_blob_removed"
        )
    finally:
        _cleanup(dsn, project_id)


def test_real_postgres_project_lock_respects_remaining_deadline(
    monkeypatch,
):
    dsn = _dsn()
    monkeypatch.setattr(config_module.config, "POSTGRES_DSN", dsn)
    pg.ensure_js_retention_schema()
    project_id = "jsret-lock-" + uuid.uuid4().hex
    digest = hashlib.sha256(b"lock-test").hexdigest()
    blocker = psycopg.connect(dsn)
    try:
        with blocker.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (project_id,),
            )
        started = time.monotonic()
        with pytest.raises((
            psycopg.errors.LockNotAvailable,
            psycopg.errors.QueryCanceled,
        )):
            pg.reserve_js_artifact(
                project_id=project_id,
                sha256=digest,
                size_bytes=9,
                archive_ref=(
                    f"recon/js-artifacts/blobs/{digest}.blob"
                ),
                quota_bytes=1024,
                timeout_ms=100,
            )
        assert time.monotonic() - started < 1.0
    finally:
        blocker.rollback()
        blocker.close()
        _cleanup(dsn, project_id)
