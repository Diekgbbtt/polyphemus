"""The one-pod session orchestrator: bounded concurrency and join-all."""
from __future__ import annotations

import threading
import time

from polymerhus.recon.crawl.sessions import (
    CrawlSession,
    SessionResult,
    anonymous_session,
    run_crawl_sessions,
)


def _session(account: str, role: str | None = None) -> CrawlSession:
    return CrawlSession(
        account=account,
        role=role,
        root_url=f"http://app.test/{role or account}",
        auth_probe=f"http://app.test/{role or account}",
        login_url=None,
        browser_context_ref=f"steel-auth-p1-{account}",
    )


def test_run_crawl_sessions_runs_every_session_and_preserves_order():
    sessions = [_session("admin", "admin"), _session("member", "member")]

    results = run_crawl_sessions(
        sessions,
        run_one=lambda session: {"account": session.account},
        max_workers=2,
    )

    assert [result.session.account for result in results] == ["admin", "member"]
    assert [result.manifest for result in results] == [
        {"account": "admin"},
        {"account": "member"},
    ]
    assert all(result.error is None for result in results)


def test_run_crawl_sessions_bounds_concurrency_to_the_pool_size():
    sessions = [_session(f"user-{index}") for index in range(6)]
    lock = threading.Lock()
    state = {"active": 0, "maximum": 0, "seen": []}

    def run_one(session: CrawlSession):
        with lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            state["seen"].append(session.account)
        time.sleep(0.02)
        with lock:
            state["active"] -= 1
        return {"account": session.account}

    results = run_crawl_sessions(sessions, run_one=run_one, max_workers=2)

    assert len(results) == 6
    assert state["maximum"] == 2
    assert sorted(state["seen"]) == [f"user-{index}" for index in range(6)]


def test_one_failed_session_does_not_discard_the_other_manifests():
    sessions = [_session("broken"), _session("healthy")]

    def run_one(session: CrawlSession):
        if session.account == "broken":
            raise RuntimeError("auth_precondition_failed")
        return {"account": session.account, "endpoints": [{"url": "/ok"}]}

    results = run_crawl_sessions(sessions, run_one=run_one, max_workers=2)

    assert results[0].session.account == "broken"
    assert results[0].manifest is None
    assert results[0].error == "auth_precondition_failed"
    assert results[1].session.account == "healthy"
    assert results[1].manifest == {
        "account": "healthy",
        "endpoints": [{"url": "/ok"}],
    }
    assert results[1].error is None


def test_run_crawl_sessions_with_no_sessions_is_empty():
    assert run_crawl_sessions([], run_one=lambda session: {}, max_workers=2) == []


def test_anonymous_session_starts_at_the_target_root():
    session = anonymous_session("http://app.test:8080/base")

    assert session == CrawlSession(
        account=None,
        role=None,
        root_url="http://app.test:8080/",
        auth_probe=None,
        login_url=None,
        browser_context_ref=None,
        anonymous=True,
    )


def test_crawl_session_from_descriptor_keeps_absolutes_and_defaults():
    session = CrawlSession.from_descriptor(
        {
            "account": "alice",
            "role": "admin",
            "root_url": "http://app.test/admin",
            "auth_probe": "http://app.test/admin",
            "login_url": "/login",
            "browser_context_ref": "steel-auth-p1-alice",
        },
        target="http://app.test/",
    )

    assert session.account == "alice"
    assert session.role == "admin"
    assert session.root_url == "http://app.test/admin"
    assert session.auth_probe == "http://app.test/admin"
    assert session.login_url == "/login"
    assert session.browser_context_ref == "steel-auth-p1-alice"
    assert session.anonymous is False


def test_session_result_is_a_value_object():
    session = _session("alice")
    result = SessionResult(session=session, manifest={"ok": True})

    assert result.session is session
    assert result.manifest == {"ok": True}
    assert result.error is None
