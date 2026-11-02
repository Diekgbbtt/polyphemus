"""Seam under test: the bounded session-loss boundary.

Spec: `docs/design/steel-crawl-spec.md` sections 2.1 (A9, A10), 4.3, 4.4, and
12; seam 1 of `docs/design/steel-crawl-implementation-plan.md` section 3.

A vanished live session is `session_missing`, a never-live name is
`unknown_session`, a start is refused, and the orchestrator gets one bounded
resurrection request. The crawl never starts or recreates a session itself and
never continues anonymously.
"""
from __future__ import annotations

import pytest

from polymerhus.recon.crawl.steel.job import (
    JobResult,
    run_with_session_boundary,
)
from polymerhus.recon.crawl.steel.ledger import FinalizeResult
from polymerhus.recon.crawl.steel.manifest import RunBlock, build_manifest
from polymerhus.recon.crawl.steel.session import (
    CLI_ERROR_TYPES,
    InvalidCommand,
    SessionMissing,
    SessionTaken,
    SteelSessionClient,
    UnknownSession,
)
from tests.recon.crawl.steel.fixtures import load_cli


def job_result(stop_reason: str, *, partial: bool = True) -> JobResult:
    manifest = build_manifest(
        run=RunBlock(
            crawl_run_id="run-1",
            session_name="session-1",
            started_at="2026-11-02T10:00:00Z",
            stop_reason=stop_reason,
            partial=partial,
        )
    )
    status = "partial" if partial else "complete"
    return JobResult(
        status=status,
        stop_reason=stop_reason,
        manifest=manifest,
        finalize=FinalizeResult(status=status, manifest=manifest),
    )


class FakeJob:
    def __init__(self, result: JobResult) -> None:
        self._result = result
        self.calls = 0

    def run(self) -> JobResult:
        self.calls += 1
        return self._result


def factory_for(jobs):
    state = {"index": 0}

    def factory():
        job = jobs[min(state["index"], len(jobs) - 1)]
        state["index"] += 1
        return job

    return factory, state


def test_one_session_missing_retries_once_then_completes():
    factory, state = factory_for(
        [FakeJob(job_result("session_missing")), FakeJob(job_result("frontier_empty", partial=False))]
    )
    calls = []

    def resurrect() -> bool:
        calls.append(True)
        return True

    result = run_with_session_boundary(factory, resurrect_fn=resurrect)

    assert result.result.status == "complete"
    assert result.result.stop_reason == "frontier_empty"
    assert result.retries == 1
    assert result.resurrection_requested is True
    assert state["index"] == 2
    assert len(calls) == 1


def test_a_second_session_missing_stops_after_one_retry():
    factory, state = factory_for(
        [FakeJob(job_result("session_missing")), FakeJob(job_result("session_missing"))]
    )
    calls = []

    def resurrect() -> bool:
        calls.append(True)
        return True

    result = run_with_session_boundary(factory, resurrect_fn=resurrect)

    assert result.result.status == "partial"
    assert result.result.stop_reason == "session_missing"
    assert result.retries == 1
    assert state["index"] == 2
    assert len(calls) == 1


def test_a_failed_resurrection_returns_the_typed_result():
    factory, state = factory_for([FakeJob(job_result("session_missing"))])

    result = run_with_session_boundary(factory, resurrect_fn=lambda: False)

    assert result.result.stop_reason == "session_missing"
    assert result.result.status == "partial"
    assert result.retries == 1
    assert result.resurrection_requested is True
    assert state["index"] == 1


def test_a_complete_run_does_not_request_a_resurrection():
    factory, state = factory_for([FakeJob(job_result("frontier_empty", partial=False))])
    calls = []

    result = run_with_session_boundary(
        factory, resurrect_fn=lambda: calls.append(True) or True
    )

    assert result.result.status == "complete"
    assert result.retries == 0
    assert result.resurrection_requested is False
    assert state["index"] == 1
    assert calls == []


def engine(*envelopes):
    queue = list(envelopes)
    calls = []

    def exec_fn(command):
        calls.append(list(command))
        return queue.pop(0)

    return exec_fn, calls


def test_a_name_that_was_never_live_is_unknown_session():
    exec_fn, _ = engine({"success": True, "data": []})
    client = SteelSessionClient(exec_fn=exec_fn)

    with pytest.raises(UnknownSession) as excinfo:
        client.attach("missing")

    assert excinfo.value.code == "unknown_session"


def test_a_live_name_that_vanished_is_session_missing():
    live = load_cli("catalogue").model_dump(mode="json")
    exec_fn, _ = engine(live, {"success": True, "data": []})
    client = SteelSessionClient(exec_fn=exec_fn)
    client.catalogue()

    with pytest.raises(SessionMissing) as excinfo:
        client.attach("crawl-fixture")

    assert excinfo.value.code == "session_missing"


def test_start_is_refused_before_any_command_and_never_starts():
    live = load_cli("catalogue").model_dump(mode="json")
    record = load_cli("session").model_dump(mode="json")
    exec_fn, calls = engine(live, record)
    client = SteelSessionClient(exec_fn=exec_fn)
    client.attach("crawl-fixture")
    before = len(calls)

    with pytest.raises(InvalidCommand) as excinfo:
        client.execute("start")

    assert excinfo.value.code == "invalid_command"
    assert len(calls) == before


def test_session_taken_is_in_the_error_table():
    assert CLI_ERROR_TYPES["session_taken"] is SessionTaken
