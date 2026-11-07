"""Unit tier: the lease state machine, heartbeat, TTL, and release hooks.

The worker registry, the CLI adapter, the store, the clock, and the heartbeat
runner are fakes. No Steel worker, Docker socket, or real time is needed.
"""
from __future__ import annotations

import json

import pytest

from kali.steel_pool.api import WorkerAPIError
from kali.steel_pool.cli import (
    CaptureError,
    CapturedContext,
    CliError,
    CliSession,
    RestoreError,
    RestoreReport,
)
from kali.steel_pool.lease import (
    EndReport,
    LeaseError,
    LeaseManager,
    PoolExhausted,
)
from kali.steel_pool.pool import PoolReport, Worker
from kali.steel_pool.store import BrowserSessionRecord, SessionStore


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeRegistry:
    def __init__(self, reports: list[PoolReport]) -> None:
        self._reports = reports
        self.refreshes = 0

    def refresh(self) -> PoolReport:
        self.refreshes += 1
        index = min(self.refreshes - 1, len(self._reports) - 1)
        return self._reports[index]


class FakeCli:
    def __init__(self, worker: Worker, session_id: str = "steel-1") -> None:
        self.worker = worker
        self.session_id = session_id
        self.calls: list[tuple] = []
        self.restore_error: Exception | None = None
        self.capture_error: Exception | None = None
        self.stop_error: Exception | None = None
        self.release_error: Exception | None = None
        self.exec_errors: set[str] = set()
        self.start_hook = None
        self.restore_hook = None
        self.captured = CapturedContext(
            context={"cookies": [{"name": "sid", "value": "new"}]}, source="api"
        )
        self.restore_report = RestoreReport(0, 0, 0, ())

    def start(self, name: str) -> CliSession:
        self.calls.append(("start", name))
        if self.start_hook is not None:
            self.start_hook()
        return CliSession(name=name, session_id=self.session_id)

    def restore(self, session: CliSession, record: BrowserSessionRecord) -> RestoreReport:
        self.calls.append(("restore", session.name, record))
        if self.restore_hook is not None:
            self.restore_hook()
        if self.restore_error is not None:
            raise self.restore_error
        return self.restore_report

    def exec(self, session: CliSession, args) -> dict:
        self.calls.append(("exec", session.name, list(args)))
        joined = " ".join(args)
        if joined in self.exec_errors:
            raise CliError("the command transport failed")
        if joined == "get url":
            return {"success": True, "data": "https://app.test/"}
        return {"success": True, "data": {}}

    def capture(self, session, previous=None) -> CapturedContext:
        self.calls.append(("capture", session.name, previous))
        if self.capture_error is not None:
            raise self.capture_error
        return self.captured

    def stop(self, session: CliSession) -> dict:
        self.calls.append(("stop", session.name))
        if self.stop_error is not None:
            raise self.stop_error
        return {"success": True}

    def release(self, session: CliSession) -> bool:
        self.calls.append(("release", session.name))
        if self.release_error is not None:
            raise self.release_error
        return True

    def verbs(self) -> list[str]:
        return [call[0] for call in self.calls]


class ManualRunner:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeProxy:
    def __init__(self, worker: Worker) -> None:
        self.worker = worker
        self.started = False
        self.stopped = False
        self.start_error: Exception | None = None

    def start(self) -> None:
        self.started = True
        if self.start_error is not None:
            raise self.start_error

    def stop(self) -> None:
        self.stopped = True


def _worker(container_id: str = "c1", port: int = 3110) -> Worker:
    return Worker(
        container_id=container_id,
        container_name=f"steel-{container_id}",
        container_ip=f"172.20.0.{int(container_id[-1], 16) + 2}",
        public_port=port,
    )


def _report(
    healthy: tuple[Worker, ...] = (),
    unhealthy: tuple[Worker, ...] = (),
) -> PoolReport:
    return PoolReport(
        workers=healthy + unhealthy,
        healthy=healthy,
        unhealthy=unhealthy,
        warning=None,
    )


class Harness:
    def __init__(
        self,
        tmp_path,
        *,
        reports: list[PoolReport] | None = None,
        pool_wait_s: float = 0.0,
    ) -> None:
        self.clock = FakeClock()
        self.registry = FakeRegistry(reports or [_report((_worker(),))])
        self.store = SessionStore(tmp_path / "sessions")
        self.clis: dict[str, FakeCli] = {}
        self.created: list[FakeCli] = []
        self.cli_overrides: dict[str, dict] = {}
        self.runners: list[ManualRunner] = []
        self.proxies: list[FakeProxy] = []
        self.proxy_start_error: Exception | None = None
        self.events: list[tuple[str, dict]] = []
        self.manager = LeaseManager(
            self.registry,
            self.store,
            self._cli_factory,
            pool_wait_s=pool_wait_s,
            clock=self.clock,
            sleep=self.clock.sleep,
            emit=self._emit,
            runner_factory=self._runner_factory,
            proxy_factory=self._proxy_factory,
        )

    def _proxy_factory(self, worker: Worker) -> FakeProxy:
        proxy = FakeProxy(worker)
        proxy.start_error = self.proxy_start_error
        self.proxies.append(proxy)
        return proxy

    def _cli_factory(self, worker: Worker) -> FakeCli:
        cli = FakeCli(worker, session_id=f"steel-{len(self.created) + 1}")
        for name, value in self.cli_overrides.pop(worker.container_id, {}).items():
            setattr(cli, name, value)
        self.created.append(cli)
        self.clis[worker.container_id] = cli
        return cli

    def _runner_factory(self, manager, lease) -> ManualRunner:
        runner = ManualRunner()
        self.runners.append(runner)
        return runner

    def _emit(self, event: str, **fields) -> None:
        self.events.append((event, fields))

    def cli(self, container_id: str = "c1") -> FakeCli:
        return self.clis[container_id]

    def lease(self, mcp_session_id: str = "mcp-1"):
        return self.manager._leases[mcp_session_id]


@pytest.fixture
def harness(tmp_path):
    return Harness(tmp_path)


def test_start_mounts_on_a_free_worker(harness):
    view = harness.manager.start("mcp-1", "hunt")

    assert view.name == "hunt"
    assert view.steel_session_id == "steel-1"
    assert view.warnings == ()
    assert harness.manager.active_count() == 1
    assert harness.runners[0].started is True
    assert harness.cli().verbs() == ["start", "restore"]


def test_start_returns_the_existing_lease(harness):
    first = harness.manager.start("mcp-1", "hunt")
    second = harness.manager.start("mcp-1", "hunt")

    assert second == first
    assert harness.cli().verbs() == ["start", "restore"]
    assert len(harness.runners) == 1


def test_start_rejects_a_second_mount_of_the_same_name(harness):
    harness.manager.start("mcp-1", "hunt")

    with pytest.raises(LeaseError):
        harness.manager.start("mcp-2", "hunt")

    assert harness.manager.active_count() == 1


def test_start_restores_the_stored_record(harness):
    saved = harness.store.save(
        BrowserSessionRecord(
            name="hunt", cookies=[{"name": "sid", "value": "old"}]
        )
    )

    harness.manager.start("mcp-1", "hunt")

    restore_call = [call for call in harness.cli().calls if call[0] == "restore"]
    assert restore_call[0][2].cookies == saved.cookies


def test_start_with_a_url_navigates(harness):
    harness.manager.start("mcp-1", "hunt", "https://app.test/login")

    assert ("exec", "hunt", ["navigate", "https://app.test/login"]) in (
        harness.cli().calls
    )


def test_start_reports_restore_warnings(harness):
    harness.cli_overrides["c1"] = {
        "restore_report": RestoreReport(
            1, 1, 1, ("1 cookie attribute set is not restorable through the CLI",)
        )
    }

    view = harness.manager.start("mcp-1", "hunt")

    assert view.warnings == (
        "1 cookie attribute set is not restorable through the CLI",
    )


def test_start_failure_stops_and_frees_the_worker(harness):
    harness.cli_overrides["c1"] = {"restore_error": RestoreError("bad state")}

    with pytest.raises(RestoreError):
        harness.manager.start("mcp-1", "hunt")

    assert "stop" in harness.cli().verbs()
    harness.manager.start("mcp-1", "hunt")
    assert harness.manager.active_count() == 1


def test_start_failure_releases_when_stop_fails(harness):
    harness.cli_overrides["c1"] = {
        "restore_error": RestoreError("bad state"),
        "stop_error": CliError("stop failed"),
    }

    with pytest.raises(RestoreError):
        harness.manager.start("mcp-1", "hunt")

    assert "release" in harness.cli().verbs()
    harness.manager.start("mcp-1", "hunt")
    assert harness.manager.active_count() == 1


def test_start_failure_quarantines_when_stop_and_release_fail(harness):
    harness.cli_overrides["c1"] = {
        "restore_error": RestoreError("bad state"),
        "stop_error": CliError("stop failed"),
        "release_error": WorkerAPIError("release failed"),
    }

    with pytest.raises(RestoreError):
        harness.manager.start("mcp-1", "hunt")

    with pytest.raises(PoolExhausted):
        harness.manager.start("mcp-2", "other")


def test_pool_exhausted_after_the_bounded_wait(tmp_path):
    harness = Harness(
        tmp_path,
        reports=[_report(())],
        pool_wait_s=5.0,
    )

    with pytest.raises(PoolExhausted):
        harness.manager.start("mcp-1", "hunt")

    assert harness.clock.now == pytest.approx(5.0)
    assert harness.registry.refreshes >= 2


def test_a_pool_start_can_retry_after_exhaustion(tmp_path):
    harness = Harness(tmp_path, reports=[_report(())], pool_wait_s=0.0)

    with pytest.raises(PoolExhausted):
        harness.manager.start("mcp-1", "hunt")

    harness.registry._reports = [_report((_worker(),))]
    view = harness.manager.start("mcp-1", "hunt")

    assert view.name == "hunt"
    assert harness.manager.active_count() == 1


def test_start_uses_the_next_free_worker(tmp_path):
    harness = Harness(
        tmp_path,
        reports=[_report((_worker("c1", 3110), _worker("c2", 3111)))],
    )

    harness.manager.start("mcp-1", "one")
    harness.manager.start("mcp-2", "two")

    assert harness.clis["c1"].verbs() == ["start", "restore"]
    assert harness.clis["c2"].verbs() == ["start", "restore"]
    with pytest.raises(PoolExhausted):
        harness.manager.start("mcp-3", "three")


def test_exec_runs_on_the_lease_and_resets_activity(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.clock.now = 100

    payload = harness.manager.exec("mcp-1", ["click", "#go"])

    assert payload == {"success": True, "data": {}}
    assert harness.lease().last_activity == 100
    assert ("exec", "hunt", ["click", "#go"]) in harness.cli().calls


@pytest.mark.parametrize("args", [[], "click", [1]])
def test_exec_rejects_an_invalid_command(harness, args):
    harness.manager.start("mcp-1", "hunt")

    with pytest.raises(ValueError):
        harness.manager.exec("mcp-1", args)


def test_exec_without_a_lease_raises(harness):
    with pytest.raises(LeaseError):
        harness.manager.exec("mcp-1", ["get", "url"])


def test_idle_heartbeat_runs_get_url(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.clock.now = 120

    harness.manager.tick()

    assert ("exec", "hunt", ["get", "url"]) in harness.cli().calls
    assert harness.lease().last_heartbeat == 120
    assert harness.lease().last_activity == 0


def test_heartbeat_does_not_run_while_active(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.clock.now = 100
    harness.manager.exec("mcp-1", ["get", "url"])
    harness.clock.now = 150

    harness.manager.tick()

    assert harness.lease().last_heartbeat == 0


def test_a_command_resets_the_idle_clock(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.clock.now = 100
    harness.manager.exec("mcp-1", ["get", "url"])

    harness.clock.now = 200
    harness.manager.tick()
    assert harness.lease().last_heartbeat == 0

    harness.clock.now = 220
    harness.manager.tick()
    assert harness.lease().last_heartbeat == 220


def test_ttl_ends_the_lease_when_the_heartbeat_stops(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.clock.now = 600

    harness.manager.tick()

    assert harness.manager.active_count() == 0
    assert harness.runners[0].stopped is True
    assert harness.store.load("hunt") is not None
    released = [fields for event, fields in harness.events if event == "lease.released"]
    assert released[-1]["reason"] == "ttl"


def test_a_heartbeat_keeps_the_lease_alive(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.clock.now = 120
    harness.manager.tick()
    harness.clock.now = 600

    harness.manager.tick()

    assert harness.manager.active_count() == 1


def test_a_failed_heartbeat_does_not_release_before_ttl(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.cli().exec_errors.add("get url")
    harness.clock.now = 120

    harness.manager.tick()

    assert harness.manager.active_count() == 1
    assert harness.lease().heartbeat_failures == 1

    harness.clock.now = 600
    harness.manager.tick()
    assert harness.manager.active_count() == 0


def test_end_captures_saves_stops_and_releases(harness):
    harness.manager.start("mcp-1", "hunt")

    report = harness.manager.end("mcp-1")

    assert report == EndReport(
        ended=True,
        reason="explicit",
        captured=True,
        saved=True,
        stopped=True,
        released=None,
        warnings=(),
    )
    saved = harness.store.load("hunt")
    assert saved is not None
    assert saved.cookies == [{"name": "sid", "value": "new"}]
    assert harness.runners[0].stopped is True
    assert harness.manager.active_count() == 0


def test_end_falls_back_to_release_when_stop_fails(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.cli().stop_error = CliError("stop failed")

    report = harness.manager.end("mcp-1")

    assert report.stopped is False
    assert report.released is True
    harness.manager.start("mcp-2", "other")
    assert harness.manager.active_count() == 1


def test_end_quarantines_when_stop_and_release_fail(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.cli().stop_error = CliError("stop failed")
    harness.cli().release_error = WorkerAPIError("release failed")

    report = harness.manager.end("mcp-1")

    assert report.stopped is False
    assert report.released is None
    with pytest.raises(PoolExhausted):
        harness.manager.start("mcp-2", "other")


def test_end_saves_nothing_when_capture_fails(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.cli().capture_error = CaptureError("no context")

    report = harness.manager.end("mcp-1")

    assert report.captured is False
    assert report.saved is False
    assert report.stopped is True
    assert report.warnings
    assert harness.manager.end("mcp-1").ended is False


def test_end_is_idempotent(harness):
    harness.manager.start("mcp-1", "hunt")

    assert harness.manager.end("mcp-1").ended is True
    assert harness.manager.end("mcp-1").ended is False


def test_end_with_no_lease_is_a_noop(harness):
    assert harness.manager.end("mcp-1").ended is False


def test_close_mcp_session_ends_the_lease(harness):
    harness.manager.start("mcp-1", "hunt")

    report = harness.manager.close_mcp_session("mcp-1")

    assert report.ended is True
    assert report.reason == "mcp_close"
    assert harness.manager.active_count() == 0


def test_shutdown_ends_every_lease_and_closes_the_manager(tmp_path):
    harness = Harness(
        tmp_path,
        reports=[_report((_worker("c1", 3110), _worker("c2", 3111)))],
    )
    harness.manager.start("mcp-1", "one")
    harness.manager.start("mcp-2", "two")

    reports = harness.manager.shutdown()

    assert [report.ended for report in reports] == [True, True]
    assert harness.manager.active_count() == 0
    with pytest.raises(LeaseError):
        harness.manager.start("mcp-3", "three")


def test_end_preserves_previous_evidence_on_a_cli_capture(harness):
    previous = harness.store.save(
        BrowserSessionRecord(
            name="hunt",
            local_storage={
                "https://old.test": {"old": "1"},
                "https://app.test": {"old": "2"},
            },
            session_storage={"https://app.test": {"flow": "f"}},
            indexed_db={"app.test": [{"name": "db"}]},
        )
    )
    harness.manager.start("mcp-1", "hunt")
    harness.cli().captured = CapturedContext(
        context={
            "cookies": [],
            "localStorage": {"https://app.test": {"new": "3"}},
        },
        source="cli",
    )

    harness.manager.end("mcp-1")

    saved = harness.store.load("hunt")
    assert saved is not None
    assert saved.local_storage == {
        "https://old.test": {"old": "1"},
        "https://app.test": {"new": "3"},
    }
    assert saved.session_storage == previous.session_storage
    assert saved.indexed_db == previous.indexed_db
    assert saved.created_at == previous.created_at


def test_the_lease_view_does_not_carry_the_worker_url(harness):
    view = harness.manager.start("mcp-1", "hunt")

    assert "http://" not in repr(view)
    assert "3110" not in repr(view)


def test_start_starts_the_proxy_before_the_cli_and_reports_the_cdp_endpoint(
    harness,
):
    view = harness.manager.start("mcp-1", "hunt")

    assert harness.proxies[0].started is True
    assert harness.proxies[0].stopped is False
    assert view.cdp_url == "ws://172.20.0.3:3000/"
    assert view.cdp_host == "localhost:3000"


def test_start_reports_the_restore_counts(harness):
    harness.cli_overrides["c1"] = {
        "restore_report": RestoreReport(2, 1, 3, ())
    }

    view = harness.manager.start("mcp-1", "hunt")

    assert view.restored is not None
    assert view.restored.cookies_set == 2
    assert view.restored.origins_visited == 1
    assert view.restored.storage_keys_set == 3


def test_end_stops_the_proxy(harness):
    harness.manager.start("mcp-1", "hunt")

    harness.manager.end("mcp-1")

    assert harness.proxies[0].stopped is True


def test_a_failed_start_stops_the_proxy(harness):
    harness.cli_overrides["c1"] = {"restore_error": RestoreError("bad state")}

    with pytest.raises(RestoreError):
        harness.manager.start("mcp-1", "hunt")

    assert harness.proxies[0].stopped is True


def test_a_proxy_start_failure_frees_the_worker(harness):
    harness.proxy_start_error = RuntimeError("port is taken")

    with pytest.raises(RuntimeError):
        harness.manager.start("mcp-1", "hunt")

    assert harness.manager.active_count() == 0
    harness.proxy_start_error = None
    harness.manager.start("mcp-1", "hunt")
    assert harness.manager.active_count() == 1


def test_shutdown_stops_every_proxy(tmp_path):
    harness = Harness(
        tmp_path,
        reports=[_report((_worker("c1", 3110), _worker("c2", 3111)))],
    )
    harness.manager.start("mcp-1", "one")
    harness.manager.start("mcp-2", "two")

    harness.manager.shutdown()

    assert [proxy.stopped for proxy in harness.proxies] == [True, True]


def test_start_rejects_an_invalid_name(harness):
    with pytest.raises(Exception):
        harness.manager.start("mcp-1", "../escape")


def test_manager_rejects_invalid_timing(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    registry = FakeRegistry([_report((_worker(),))])

    with pytest.raises(ValueError):
        LeaseManager(registry, store, lambda worker: FakeCli(worker), heartbeat_s=0)
    with pytest.raises(ValueError):
        LeaseManager(registry, store, lambda worker: FakeCli(worker), ttl_s=-1)
    with pytest.raises(ValueError):
        LeaseManager(registry, store, lambda worker: FakeCli(worker), pool_wait_s=-1)


def test_a_second_worker_stays_free_when_the_first_start_fails(tmp_path):
    harness = Harness(
        tmp_path,
        reports=[_report((_worker("c1", 3110), _worker("c2", 3111)))],
    )
    harness.cli_overrides["c1"] = {
        "restore_error": RestoreError("bad state")
    }

    with pytest.raises(RestoreError):
        harness.manager.start("mcp-1", "hunt")

    harness.manager.start("mcp-2", "other")
    assert harness.created[0].worker.container_id == "c1"
    assert harness.created[0].verbs() == ["start", "restore", "stop"]
    assert harness.created[1].worker.container_id == "c1"
    assert harness.created[1].verbs() == ["start", "restore"]


def test_events_are_json_safe(harness):
    harness.manager.start("mcp-1", "hunt")
    harness.manager.end("mcp-1")

    for event, fields in harness.events:
        json.dumps({"event": event, **fields})


def test_a_start_in_progress_reserves_the_name(harness):
    seen: list[Exception] = []

    def try_duplicate() -> None:
        try:
            harness.manager.start("mcp-2", "hunt")
        except LeaseError as exc:
            seen.append(exc)

    harness.cli_overrides["c1"] = {"restore_hook": try_duplicate}

    harness.manager.start("mcp-1", "hunt")

    assert seen and isinstance(seen[0], LeaseError)
    assert harness.manager.active_count() == 1


def test_a_start_in_progress_reserves_the_mcp_session(harness):
    seen: list[Exception] = []

    def try_second_start() -> None:
        try:
            harness.manager.start("mcp-1", "other")
        except LeaseError as exc:
            seen.append(exc)

    harness.cli_overrides["c1"] = {"restore_hook": try_second_start}

    harness.manager.start("mcp-1", "hunt")

    assert seen and isinstance(seen[0], LeaseError)
    assert harness.manager.active_count() == 1


def test_a_shutdown_during_mount_stops_the_cli(harness):
    def shutdown_now() -> None:
        harness.manager.shutdown()

    harness.cli_overrides["c1"] = {"start_hook": shutdown_now}

    with pytest.raises(LeaseError):
        harness.manager.start("mcp-1", "hunt")

    cli = harness.created[0]
    assert "stop" in cli.verbs()
    assert harness.manager.active_count() == 0

