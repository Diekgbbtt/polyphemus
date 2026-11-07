"""Seam under test: the crawl job lifecycle with fake session, capture, and run.

Spec: `docs/design/steel-crawl-spec.md` sections 2.1, 10.4, 12, and 13; seam 10
of `docs/design/steel-crawl-implementation-plan.md` section 3.

The job attaches to a pre-authenticated session (never starts one), runs the
oracle once, starts the passive capture, emits page and action records, and
finalizes on success and on every failure. It never logs the connect URL,
cookies, storage values, or credentials.
"""
from __future__ import annotations

import logging
from typing import Any

from polymerhus.recon.crawl.steel.auth import (
    AuthPreconditionFailed,
    AuthVerdict,
)
from polymerhus.recon.crawl.steel.enumerate import (
    ChangeSemantics,
    Element,
    ElementType,
)
from polymerhus.recon.crawl.steel.frontier import (
    ActionVisit,
    ExecutionResult,
    FailedVisit,
    FrontierResult,
    PageVisit,
    StaleVisit,
)
from polymerhus.recon.crawl.steel.job import CrawlJob
from polymerhus.recon.crawl.steel.ledger import RunLedger
from polymerhus.recon.crawl.steel.manifest import RunBlock, build_manifest
from polymerhus.recon.crawl.steel.session import (
    BrowserUnavailable,
    RestoreFailed,
    SessionMissing,
    SteelEnd,
)
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance, StaleElement


class FakeSession:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.attached: str | None = None
        self.start_calls = 0
        self.stopped = False
        self.stop_error: Exception | None = None
        self.end_report = SteelEnd(
            ended=True, saved=True, stopped=True, captured=True
        )

    def attach(self, name: str) -> Any:
        if self.failure is not None:
            raise self.failure
        self.attached = name
        return object()

    def start(self, *args: Any) -> None:
        self.start_calls += 1

    def stop(self) -> SteelEnd:
        self.stopped = True
        if self.stop_error is not None:
            raise self.stop_error
        return self.end_report


class FakeSidecar:
    def __init__(self) -> None:
        self.attached = False
        self.closed = False

    def attach(self) -> None:
        self.attached = True

    def close(self) -> None:
        self.closed = True


def make_root() -> PageInstance:
    state = BrowserState()
    return state.open_page(
        page_visit_id="page_1",
        url="https://example.test/",
        final_url="https://example.test/",
        title="Home",
        depth=0,
        discovery_source="seed",
        snapshot=(),
    )


def make_element() -> Element:
    return Element(
        element_id="e1",
        fingerprint="fp1",
        element_type=ElementType.BUTTON,
        name="Go",
        selector="@e1",
        impact="local_state",
        capture="dom",
        change=ChangeSemantics(impact="local_state", capture="dom"),
    )


def make_job(
    *,
    session: FakeSession | None = None,
    sidecar: FakeSidecar | None = None,
    root: PageInstance | None = None,
    frontier: FrontierResult | None = None,
    auth: Any | None = None,
    deadline: Any | None = None,
    records: dict[str, list[Any]] | None = None,
    on_manifest: Any | None = None,
):
    session = session or FakeSession()
    sidecar = sidecar or FakeSidecar()
    root = root or make_root()
    element = make_element()
    frontier = frontier or FrontierResult(
        stop_reason="frontier_empty",
        page_visits=(PageVisit(page=root),),
        action_visits=(
            ActionVisit(
                page=root, element=element, result=ExecutionResult(navigated=False)
            ),
        ),
    )
    records = records if records is not None else {"pages": [], "actions": []}
    run_calls: list[Any] = []

    def run_fn(value: PageInstance) -> FrontierResult:
        run_calls.append(value)
        return frontier

    def auth_fn(value: PageInstance) -> AuthVerdict:
        if auth is not None:
            return auth(value)
        return AuthVerdict(
            classification="authenticated",
            probe_url="/api/auth",
            probe_source="overview.auth_probe.url",
        )

    job = CrawlJob(
        run_id="run-1",
        session_name="session-1",
        project_id="proj-1",
        account="admin",
        session=session,
        sidecar=sidecar,
        ledger=RunLedger("/private/var/folders/gs/p9fl4f1s1yqfl8801x50nhjc0000gn/T/opencode/job-ledger.jsonl"),
        prepare_fn=lambda: root,
        auth_fn=auth_fn,
        run_fn=run_fn,
        manifest_fn=lambda result, stop_reason: (
            on_manifest() if on_manifest is not None else None
        )
        or build_manifest(
            run=RunBlock(
                crawl_run_id="run-1",
                session_name="session-1",
                started_at="2026-11-02T10:00:00Z",
                stop_reason=stop_reason,
            )
        ),
        flush_fn=lambda artifacts: {"cursor": 1},
        ingest_fn=lambda manifest: {"ok": True},
        record_page=records["pages"].append,
        record_action=records["actions"].append,
        coverage={"unreached": ["/admin"]},
        deadline=deadline or (lambda: False),
    )
    return job, session, sidecar, run_calls, records


def test_the_job_runs_the_lifecycle_and_emits_page_and_action_records():
    job, session, sidecar, run_calls, records = make_job()

    result = job.run()

    assert session.attached == "session-1"
    assert session.start_calls == 0
    assert session.stopped is True
    assert sidecar.attached is True
    assert sidecar.closed is True
    assert len(run_calls) == 1
    assert result.status == "complete"
    assert result.stop_reason == "frontier_empty"
    assert result.partial is False
    assert len(records["pages"]) == 1
    page = records["pages"][0]
    assert page.page_visit_id == "page_1"
    assert page.url == "https://example.test/"
    assert page.title == "Home"
    assert page.parent_id is None
    assert page.discovery_source == "seed"
    assert len(records["actions"]) == 1
    action = records["actions"][0]
    assert action.page_id == "page_1"
    assert action.element_id == "e1"
    assert action.element_type == "BUTTON"
    assert action.outcome == "ok"
    assert result.manifest.run.partial is False
    assert result.finalize.coverage == {"unreached": ["/admin"]}


def test_an_auth_failure_is_partial_and_never_traverses():
    def auth(value):
        raise AuthPreconditionFailed(
            AuthVerdict(
                classification="unauthenticated",
                probe_url="/api/auth",
                probe_source="overview.auth_probe.url",
            )
        )

    job, session, sidecar, run_calls, records = make_job(auth=auth)

    result = job.run()

    assert run_calls == []
    assert sidecar.attached is True
    assert sidecar.closed is True
    assert session.stopped is True
    assert result.status == "partial"
    assert result.stop_reason == "auth_precondition_failed"
    assert result.error is not None
    assert records["pages"] == []
    assert records["actions"] == []


def test_a_deadline_stops_before_the_traversal():
    job, session, sidecar, run_calls, records = make_job(
        deadline=lambda: True
    )

    result = job.run()

    assert run_calls == []
    assert sidecar.attached is False
    assert session.stopped is True
    assert result.status == "partial"
    assert result.stop_reason == "session_deadline"


def test_a_missing_session_is_a_typed_stop_and_never_traverses():
    job, session, sidecar, run_calls, records = make_job(
        session=FakeSession(failure=SessionMissing("the session is gone"))
    )

    result = job.run()

    assert run_calls == []
    assert sidecar.attached is False
    assert session.stopped is False
    assert result.status == "partial"
    assert result.stop_reason == "session_missing"
    assert "the session is gone" in (result.error or "")


def test_a_browser_unavailable_mount_is_a_typed_partial_stop():
    job, session, sidecar, run_calls, records = make_job(
        session=FakeSession(failure=BrowserUnavailable("the pool is down"))
    )

    result = job.run()

    assert result.status == "partial"
    assert result.stop_reason == "browser_unavailable"
    assert any(
        error.code == "browser_unavailable" and error.stage == "mount"
        for error in result.manifest.errors
    )


def test_a_restore_failure_is_a_typed_partial_stop():
    job, session, sidecar, run_calls, records = make_job(
        session=FakeSession(failure=RestoreFailed("bad state"))
    )

    result = job.run()

    assert result.status == "partial"
    assert result.stop_reason == "restore_failed"
    assert any(
        error.code == "restore_failed" and error.stage == "mount"
        for error in result.manifest.errors
    )


def test_a_stale_action_is_recorded_with_its_error():
    root = make_root()
    element = make_element()
    error = StaleElement(root, root.document_generation, root.document_generation + 1)
    frontier = FrontierResult(
        stop_reason="frontier_empty",
        page_visits=(PageVisit(page=root),),
        stale=(StaleVisit(page=root, element=element, error=error),),
    )
    job, session, sidecar, run_calls, records = make_job(
        root=root, frontier=frontier
    )

    result = job.run()

    assert len(records["actions"]) == 1
    record = records["actions"][0]
    assert record.outcome == "error"
    assert record.error == "stale_element"
    assert result.status == "complete"


def test_a_failed_action_is_recorded_with_its_error():
    root = make_root()
    element = make_element()
    frontier = FrontierResult(
        stop_reason="error",
        page_visits=(PageVisit(page=root),),
        failed=(
            FailedVisit(
                page=root,
                element=element,
                error="command_failed: the browser did not answer",
            ),
        ),
        error="command_failed: the browser did not answer",
    )
    job, session, sidecar, run_calls, records = make_job(
        root=root, frontier=frontier
    )

    result = job.run()

    assert result.stop_reason == "error"
    assert len(records["actions"]) == 1
    record = records["actions"][0]
    assert record.outcome == "error"
    assert "command_failed" in (record.error or "")


def test_the_job_log_does_not_leak_the_connect_url_or_credentials(caplog):
    caplog.set_level(logging.INFO)
    job, session, sidecar, run_calls, records = make_job()

    job.run()

    assert "wss://" not in caplog.text
    assert "cookie" not in caplog.text.lower()
    assert "password" not in caplog.text.lower()
    assert "connectUrl" not in caplog.text


def test_the_session_is_ended_before_the_manifest_is_built():
    seen: dict[str, bool] = {}

    job, session, sidecar, run_calls, records = make_job(
        on_manifest=lambda: seen.update(
            stopped=session.stopped, closed=sidecar.closed
        )
    )

    job.run()

    assert seen == {"stopped": True, "closed": True}


def test_a_saved_false_end_marks_the_run_partial():
    job, session, sidecar, run_calls, records = make_job()
    session.end_report = SteelEnd(
        ended=True,
        saved=False,
        stopped=True,
        captured=False,
        state_managed=True,
    )

    result = job.run()

    assert result.status == "partial"
    assert result.manifest.run.partial is True
    assert result.partial is True


def test_a_stop_failure_marks_the_run_partial_and_records_the_error():
    job, session, sidecar, run_calls, records = make_job()
    session.stop_error = RuntimeError("the stop failed")

    result = job.run()

    assert result.status == "partial"
    assert result.manifest.run.partial is True
    assert any(
        error.code == "session_close_failed" for error in result.manifest.errors
    )
    assert "the stop failed" in result.manifest.errors[-1].message


def test_the_end_report_rides_the_result():
    job, session, sidecar, run_calls, records = make_job()

    result = job.run()

    assert result.end is session.end_report
