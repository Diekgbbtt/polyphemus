"""Seam under test: the live run context and the pod's production wiring.

The browser is never started here. The tests pin the pool URL, the stable
session name, the 1800-second budget, and the removal of the action cap.
"""
from __future__ import annotations

import pytest

from polymerhus.recon.crawl import crawl_pod
from polymerhus.recon.crawl.steel.live import (
    MAX_DURATION_S_DEFAULT,
    LiveCrawlError,
    LiveRunContext,
    LiveRunResult,
    crawl_seed_urls,
    run_live_crawl,
)
from polymerhus.recon.crawl.steel.manifest import RunBlock, build_manifest


def test_the_crawl_budget_is_eighteen_hundred_seconds():
    assert MAX_DURATION_S_DEFAULT == 1800
    context = LiveRunContext(
        project_id="proj-1",
        run_id="run-1",
        session_name="steel-proj-1",
        target_url="https://app.test/",
        scope=["app.test"],
        data_root="/tmp",
    )

    assert context.max_duration_s == 1800
    assert not hasattr(context, "max_actions")
    assert context.browser_mcp_url == ""


def test_the_auth_probe_is_the_first_seed_and_the_public_root_follows():
    """The admin console is a known entry, not a link on the public root."""
    assert crawl_seed_urls(
        "https://app.test/", "/index.php/admin/Index/index.html"
    ) == (
        "https://app.test/index.php/admin/Index/index.html",
        "https://app.test/",
    )


def test_a_missing_or_same_root_probe_does_not_duplicate_the_seed():
    assert crawl_seed_urls("https://app.test/", None) == ("https://app.test/",)
    assert crawl_seed_urls("https://app.test/", "https://app.test/") == (
        "https://app.test/",
    )


def test_run_live_crawl_requires_the_browser_mcp_url(tmp_path):
    context = LiveRunContext(
        project_id="proj-1",
        run_id="run-1",
        session_name="steel-proj-1",
        target_url="https://app.test/",
        scope=["app.test"],
        data_root=tmp_path,
    )

    with pytest.raises(LiveCrawlError, match="KALI_BROWSER_MCP_URL"):
        run_live_crawl(context)


def test_the_pod_passes_the_pool_url_stable_name_and_budget(monkeypatch):
    captured: list[LiveRunContext] = []

    def fake_run(context: LiveRunContext) -> LiveRunResult:
        captured.append(context)
        manifest = build_manifest(
            run=RunBlock(
                crawl_run_id=context.run_id,
                session_name=context.session_name,
                started_at="2026-11-07T10:00:00Z",
                stop_reason="frontier_empty",
            )
        )
        from pathlib import Path

        run_dir = Path("/tmp")
        return LiveRunResult(
            job=None,  # type: ignore[arg-type]
            manifest=manifest,
            run_dir=run_dir,
            ledger_path=run_dir / "ledger.jsonl",
            manifest_path=run_dir / "manifest.json",
            summary_path=run_dir / "summary.json",
            flow_count=0,
            artifact_count=0,
            duration_s=0.0,
        )

    monkeypatch.setattr(
        "polymerhus.recon.crawl.steel.live.run_live_crawl", fake_run
    )
    monkeypatch.setenv("KALI_BROWSER_MCP_URL", "http://kali:8003/mcp")
    monkeypatch.setenv("STEEL_CRAWL_MAX_DURATION_S", "1800")
    monkeypatch.delenv("STEEL_CRAWL_CLI", raising=False)
    monkeypatch.delenv("STEEL_CRAWL_MAX_ACTIONS", raising=False)

    manifest = crawl_pod.live_run_crawl_fn(
        "https://app.test/",
        scope=["app.test"],
        extra={
            "project_id": "proj-1",
            "run_id": "run-1",
            "auth_account": "alice-first_authn_bootstrap",
            "browser_context_ref": "steel-auth-proj-1-alice",
        },
    )

    context = captured[0]
    assert manifest["schema_version"] == "steel-crawl/v2"
    assert context.browser_mcp_url == "http://kali:8003/mcp"
    assert context.session_name == (
        "steel-proj-1-alice-first_authn_bootstrap-crawl-run-1"
    )
    assert context.browser_context_ref == "steel-auth-proj-1-alice"
    assert context.max_duration_s == 1800
    assert not hasattr(context, "max_actions")
    assert not hasattr(context, "cli_prefix")


def test_the_pod_derives_the_ephemeral_session_name(monkeypatch):
    captured: list[LiveRunContext] = []

    def fake_run(context: LiveRunContext) -> LiveRunResult:
        captured.append(context)
        manifest = build_manifest(
            run=RunBlock(
                crawl_run_id=context.run_id,
                session_name=context.session_name,
                started_at="2026-11-07T10:00:00Z",
                stop_reason="frontier_empty",
            )
        )
        return LiveRunResult(
            job=None,  # type: ignore[arg-type]
            manifest=manifest,
            run_dir=__import__("pathlib").Path("/tmp"),
            ledger_path=__import__("pathlib").Path("/tmp/ledger.jsonl"),
            manifest_path=__import__("pathlib").Path("/tmp/manifest.json"),
            summary_path=__import__("pathlib").Path("/tmp/summary.json"),
            flow_count=0,
            artifact_count=0,
            duration_s=0.0,
        )

    monkeypatch.setattr(
        "polymerhus.recon.crawl.steel.live.run_live_crawl", fake_run
    )
    monkeypatch.setenv("KALI_BROWSER_MCP_URL", "http://kali:8003/mcp")

    crawl_pod.live_run_crawl_fn(
        "https://app.test/",
        scope=["app.test"],
        extra={
            "project_id": "proj-1",
            "run_id": "run-1",
            "steel_session": "steel-operator-pinned",
        },
    )

    assert captured[0].session_name == "steel-proj-1-crawl-run-1"
