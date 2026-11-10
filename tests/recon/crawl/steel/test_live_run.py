"""Seam under test: the live run context and the pod's production wiring.

The browser is never started here. The tests pin the pool URL, the stable
session name, the 1800-second budget, and the removal of the action cap.
"""
from __future__ import annotations

import threading

import pytest

from polymerhus.recon.crawl import crawl_pod
from types import SimpleNamespace

from polymerhus.recon.crawl.steel.live import (
    MAX_DURATION_S_DEFAULT,
    LiveCrawlError,
    LiveRunContext,
    LiveRunResult,
    crawl_session_probe,
    crawl_session_probe_with_source,
    crawl_session_root,
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


def test_the_loaded_session_supplies_the_root_and_the_probe():
    context = LiveRunContext(
        project_id="proj-1",
        run_id="run-1",
        session_name="steel-proj-1",
        target_url="https://app.test/",
        scope=["app.test"],
        data_root="/tmp",
        root_url="https://app.test/declared",
        auth_probe="https://app.test/declared-probe",
    )
    loaded = SimpleNamespace(
        root_url="https://app.test/loaded",
        auth_probe="https://app.test/loaded-probe",
    )

    assert crawl_session_root(context, loaded) == "https://app.test/loaded"
    assert crawl_session_probe(context, loaded) == (
        "https://app.test/loaded-probe"
    )


def test_the_probe_source_names_the_actual_source():
    context = LiveRunContext(
        project_id="proj-1",
        run_id="run-1",
        session_name="steel-proj-1",
        target_url="https://app.test/",
        scope=["app.test"],
        data_root="/tmp",
        root_url="https://app.test/declared",
        auth_probe="https://app.test/declared-probe",
    )
    loaded = SimpleNamespace(
        root_url="https://app.test/loaded",
        auth_probe="https://app.test/loaded-probe",
    )
    assert crawl_session_probe_with_source(context, loaded) == (
        "https://app.test/loaded-probe",
        "session.auth_probe",
    )
    loaded_no_probe = SimpleNamespace(root_url="https://app.test/loaded")
    assert crawl_session_probe_with_source(context, loaded_no_probe) == (
        "https://app.test/declared-probe",
        "account.auth_probe",
    )
    assert crawl_session_probe_with_source(
        LiveRunContext(
            project_id="proj-1",
            run_id="run-1",
            session_name="steel-proj-1",
            target_url="https://app.test/",
            scope=["app.test"],
            data_root="/tmp",
            root_url="https://app.test/member",
        )
    ) == ("https://app.test/member", "session.root_url")


def test_the_session_probe_falls_back_to_the_root_and_anonymous_has_none():
    member = LiveRunContext(
        project_id="proj-1",
        run_id="run-1",
        session_name="steel-proj-1",
        target_url="https://app.test/",
        scope=["app.test"],
        data_root="/tmp",
        root_url="https://app.test/member",
    )
    anonymous = LiveRunContext(
        project_id="proj-1",
        run_id="run-1",
        session_name="steel-proj-1",
        target_url="https://app.test/",
        scope=["app.test"],
        data_root="/tmp",
        root_url="https://app.test/",
        anonymous=True,
    )

    assert crawl_session_probe(member) == "https://app.test/member"
    assert crawl_session_probe(anonymous) is None


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

    batch = crawl_pod.live_run_crawl_fn(
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
    assert batch["manifests"][0]["schema_version"] == "steel-crawl/v2"
    assert context.browser_mcp_url == "http://kali:8003/mcp"
    assert "crawl-baseline" in context.session_name
    assert "alice-first_authn_bootstrap" in context.session_name
    assert context.browser_context_ref == "steel-auth-proj-1-alice"
    assert context.max_duration_s == 1800
    assert not hasattr(context, "max_actions")
    assert not hasattr(context, "cli_prefix")


def test_the_pod_runs_one_lifecycle_per_auth_session(monkeypatch):
    captured: list[LiveRunContext] = []
    lock = threading.Lock()

    def fake_run(context: LiveRunContext) -> LiveRunResult:
        with lock:
            captured.append(context)
        manifest = build_manifest(
            run=RunBlock(
                crawl_run_id=context.run_id,
                session_name=context.session_name,
                account=context.account,
                role=context.role,
                root_url=context.root_url,
                auth_probe=context.auth_probe,
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
    monkeypatch.setenv("STEEL_CRAWL_MAX_WORKERS", "2")

    batch = crawl_pod.live_run_crawl_fn(
        "https://app.test/",
        scope=["app.test"],
        extra={
            "project_id": "proj-1",
            "run_id": "run-1",
            "auth_sessions": [
                {
                    "account": "admin",
                    "role": "admin",
                    "root_url": "https://app.test/admin",
                    "auth_probe": "https://app.test/admin",
                    "login_url": "/login",
                    "browser_context_ref": "steel-auth-proj-1-admin",
                },
                {
                    "account": "member",
                    "role": "member",
                    "root_url": "https://app.test/member",
                    "auth_probe": "https://app.test/member",
                    "login_url": "/login",
                    "browser_context_ref": "steel-auth-proj-1-member",
                },
            ],
        },
    )

    assert len(batch["manifests"]) == 2
    assert batch["sessions"] == [
        {"account": "admin", "role": "admin", "error": None},
        {"account": "member", "role": "member", "error": None},
    ]
    by_account = {context.account: context for context in captured}
    assert set(by_account) == {"admin", "member"}
    assert by_account["admin"].root_url == "https://app.test/admin"
    assert by_account["admin"].auth_probe == "https://app.test/admin"
    assert by_account["admin"].browser_context_ref == (
        "steel-auth-proj-1-admin"
    )
    assert by_account["member"].root_url == "https://app.test/member"
    assert by_account["member"].auth_probe == "https://app.test/member"
    assert by_account["admin"].anonymous is False
    assert len({context.session_name for context in captured}) == 2


def test_the_pod_does_not_add_an_anonymous_session_when_accounts_exist(
    monkeypatch,
):
    called: list[LiveRunContext] = []

    def fake_run(context: LiveRunContext) -> LiveRunResult:
        called.append(context)
        raise AssertionError("no lifecycle may run without a usable session")

    monkeypatch.setattr(
        "polymerhus.recon.crawl.steel.live.run_live_crawl", fake_run
    )
    monkeypatch.setenv("KALI_BROWSER_MCP_URL", "http://kali:8003/mcp")

    batch = crawl_pod.live_run_crawl_fn(
        "https://app.test/",
        scope=["app.test"],
        extra={
            "project_id": "proj-1",
            "run_id": "run-1",
            "auth_sessions": [],
            "auth_accounts_present": True,
        },
    )

    assert batch == {"manifests": [], "sessions": []}
    assert called == []


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

    assert captured[0].session_name == (
        "steel-proj-1-crawl-baseline-run-1-anonymous"
    )
