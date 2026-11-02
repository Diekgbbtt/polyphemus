"""Seam under test: the append-only ledger and the finalize path.

Spec: `docs/design/steel-crawl-spec.md` sections 10.4 and 12; seam 10 of
`docs/design/steel-crawl-implementation-plan.md` section 3.

The ledger survives a killed process; finalize runs on success and on every
failure; a failed flush keeps the ledger and cursor; a partial run is never
reported complete; the HTTP flush and graph ingestion both run; and the coverage
report is separate from the manifest.
"""
from __future__ import annotations

import json

from polymerhus.recon.crawl.steel.capture.history import (
    HttpArtifact,
    RequestRecord,
)
from polymerhus.recon.crawl.steel.ledger import RunLedger, finalize
from polymerhus.recon.crawl.steel.manifest import RunBlock, build_manifest


def run(stop_reason: str = "frontier_empty") -> RunBlock:
    return RunBlock(
        crawl_run_id="run-1",
        session_name="session-1",
        account="admin",
        started_at="2026-11-02T10:00:00Z",
        stop_reason=stop_reason,
        scope=["example.test"],
        auth={"classification": "authenticated"},
    )


def artifact() -> HttpArtifact:
    return HttpArtifact(
        artifact_id="http_1",
        project_id="proj-1",
        request=RequestRecord(method="GET", url="https://example.test/"),
    )


def test_the_ledger_is_append_only_and_survives_a_kill(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = RunLedger(path)
    ledger.append_artifact(artifact(), {"sha256:abc": b"body"})
    ledger.append_manifest(build_manifest(run=run()))

    reopened = RunLedger(path)

    assert [item[0].artifact_id for item in reopened.artifacts()] == ["http_1"]
    assert reopened.artifacts()[0][1] == {"sha256:abc": b"body"}
    assert len(reopened.manifests()) == 1
    assert reopened.cursor() == 0
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["kind"] for line in lines] == ["artifact", "manifest"]


def test_finalize_runs_on_success_and_marks_the_run_complete(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    manifest = build_manifest(run=run())
    calls: list[str] = []

    result = finalize(
        ledger=ledger,
        manifest=manifest,
        stop_reason="frontier_empty",
        finished_at="2026-11-02T10:10:00Z",
        flush_fn=lambda artifacts: calls.append("flush") or {"cursor": 1},
        ingest_fn=lambda value: calls.append("ingest") or {"ok": True},
        close_fn=lambda: calls.append("close"),
    )

    assert calls[0] == "close"
    assert set(calls[1:]) == {"flush", "ingest"}
    assert result.status == "complete"
    assert result.partial is False
    assert result.manifest.run.finished_at == "2026-11-02T10:10:00Z"
    assert result.manifest.run.partial is False
    assert ledger.cursor() == 1
    assert ledger.manifests()[-1].run.partial is False


def test_finalize_marks_a_deadline_run_partial(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    manifest = build_manifest(run=run("session_deadline"))

    result = finalize(
        ledger=ledger,
        manifest=manifest,
        stop_reason="session_deadline",
        finished_at="2026-11-02T10:10:00Z",
        flush_fn=lambda artifacts: {"cursor": 0},
        ingest_fn=lambda value: {"ok": True},
    )

    assert result.status == "partial"
    assert result.manifest.run.partial is True
    assert result.manifest.run.stop_reason == "session_deadline"


def test_a_failed_flush_keeps_the_ledger_and_the_cursor(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    ledger.append_artifact(artifact(), {"sha256:abc": b"body"})
    manifest = build_manifest(run=run("frontier_empty"))

    def fail(artifacts):
        raise ConnectionError("edge is down")

    result = finalize(
        ledger=ledger,
        manifest=manifest,
        stop_reason="frontier_empty",
        finished_at="2026-11-02T10:10:00Z",
        flush_fn=fail,
        ingest_fn=lambda value: {"ok": True},
    )

    assert result.status == "partial"
    assert result.errors == ("http_history_flush_failed: edge is down",)
    assert ledger.cursor() == 0
    assert [item[0].artifact_id for item in ledger.artifacts()] == ["http_1"]
    assert any(
        error["code"] == "http_history_flush_failed" for error in ledger.errors()
    )
    assert any(
        error.code == "http_history_flush_failed" for error in result.manifest.errors
    )


def test_a_failed_ingest_marks_the_run_partial_but_the_flush_still_runs(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    manifest = build_manifest(run=run("frontier_empty"))
    calls: list[str] = []

    def fail(value):
        calls.append("ingest")
        raise RuntimeError("graph is down")

    result = finalize(
        ledger=ledger,
        manifest=manifest,
        stop_reason="frontier_empty",
        finished_at="2026-11-02T10:10:00Z",
        flush_fn=lambda artifacts: calls.append("flush") or {"cursor": 1},
        ingest_fn=fail,
    )

    assert set(calls) == {"flush", "ingest"}
    assert result.status == "partial"
    assert result.errors == ("graph_ingest_failed: graph is down",)
    assert ledger.cursor() == 1


def test_finalize_runs_on_a_fatal_error_and_keeps_the_coverage_report(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    manifest = build_manifest(run=run("session_missing"))

    result = finalize(
        ledger=ledger,
        manifest=manifest,
        stop_reason="session_missing",
        finished_at="2026-11-02T10:10:00Z",
        flush_fn=lambda artifacts: {"cursor": 0},
        ingest_fn=lambda value: {"ok": True},
        coverage={"visited": ["/"], "unreached": ["/admin"]},
    )

    assert result.status == "partial"
    assert result.coverage == {"visited": ["/"], "unreached": ["/admin"]}
    assert "coverage" not in result.manifest.model_dump()
