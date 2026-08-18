"""#110: the hunting module runtime entry points - the start/stop lifecycle, the
tear-down flush hook, the fixed store root, and the scheduling marshalling
harness. No live PG / live LLM / live Neo4j: the pg accessors and the
orchestration seams are faked, exactly the seam contract (seam 3) the tests
assert against."""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    DispatchResult,
    OrchestratorTools,
    ReadOnlyGraphView,
    Witness,
    run_orchestration,
)
from polymerhus.attack.hunting.hunt_store import HUNT_STORE_ROOT, HuntStore

SERVICE_A = "Service:slug:a"
FAULT_X = "fault-x"


def _candidate(unit_id: str = SERVICE_A, fault_class: str = FAULT_X) -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id,
        fault_class=fault_class,
        applies_witnesses=Witness(deterministic="witness", llm="witness"),
        match_verdict="applies",
    )


def _tools(store) -> OrchestratorTools:
    return OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView("rt-project", read_fn=lambda cy, p: []),
    )


class _FakePg:
    """The fake pg accessors: mint a deterministic hunting_run_id, record every
    status write in order, and fail on demand (the seam's fail-open paths)."""

    def __init__(self, *, fail_create: bool = False, fail_status: bool = False):
        self.fail_create = fail_create
        self.fail_status = fail_status
        self.statuses: list[tuple[str, str]] = []
        self.next_id = "rt-hunt-0001"

    def create_hunting_run(self, project_id: str) -> str:
        if self.fail_create:
            raise OSError("pg down (fixture)")
        self.statuses.append(("running", self.next_id))
        return self.next_id

    def set_hunting_run_status(self, hunting_run_id: str, status: str) -> None:
        if self.fail_status:
            raise OSError("pg down (fixture)")
        self.statuses.append((hunting_run_id, status))


def test_start_hunting_persists_running_then_complete(tmp_path, monkeypatch):
    """The entry point opens the run `running`, runs an orchestration pass
    (here: one candidate, the fixture dispatch), and lands `complete`."""
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)

    def dispatch(config, routed=()):
        return DispatchResult(
            spec_ref="spec-1", pod_result_ref="pod-1",
            hypothesis_verdict="successful", feedback="ok",
        )

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_candidate()], tools=_tools(HuntStore(tmp_path)),
        dispatch_fn=dispatch,
    ))

    assert hid == "rt-hunt-0001"
    assert fake.statuses == [("running", "rt-hunt-0001"), ("rt-hunt-0001", "complete")]


def test_default_tools_ground_on_the_fixed_store_root():
    """With no tools injected the entry point builds the seam defaults: the
    HuntStore at the FIXED seam root and the read-only graph view."""
    assert HUNT_STORE_ROOT.name == "hunts"
    assert HUNT_STORE_ROOT.parent.name == "data"
    store = HuntStore()
    assert store._root == HUNT_STORE_ROOT


def test_failing_orchestration_still_lands_a_terminal_status(monkeypatch):
    """Fail-open: an orchestration pass that raises degrades to `failed` - the
    entry point never raises through the control plane."""
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)

    async def boom(*args, **kwargs):
        raise RuntimeError("orchestration blew up (fixture)")

    monkeypatch.setattr("polymerhus.attack.hunting.hunt_orchestrator.arun_orchestration", boom)

    hid = asyncio.run(hunting_runtime.start_hunting("rt-project", candidates=[_candidate()]))
    assert hid == "rt-hunt-0001"
    assert fake.statuses == [("running", "rt-hunt-0001"), ("rt-hunt-0001", "failed")]


def test_start_hunting_fail_open_when_pg_is_unavailable(monkeypatch, caplog):
    """Fail-open: with the PG row AND the status write unavailable the run still
    proceeds (a generated id keys the trail) and nothing raises."""
    fake = _FakePg(fail_create=True, fail_status=True)
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)

    async def recording(*args, **kwargs):
        return None

    monkeypatch.setattr("polymerhus.attack.hunting.hunt_orchestrator.arun_orchestration", recording)

    hid = asyncio.run(hunting_runtime.start_hunting("rt-project", candidates=[_candidate()]))
    assert hid  # an id still keyed the run despite the PG outage
    assert fake.statuses == []


def test_pinned_run_id_keys_the_run(tmp_path, monkeypatch):
    """A caller-pinned run_id keys the status writes (the store trail uses it)."""
    fake = _FakePg()
    fake.create_hunting_run = lambda project_id: fake.next_id  # recording running in create
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)

    def dispatch(config, routed=()):
        return DispatchResult(
            spec_ref="spec-1", pod_result_ref="pod-1",
            hypothesis_verdict="successful", feedback="ok",
        )

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", run_id="pinned-run", candidates=[_candidate()],
        tools=_tools(HuntStore(tmp_path)), dispatch_fn=dispatch,
    ))
    assert hid == "pinned-run"


def test_stop_hunting_persists_stopped(monkeypatch):
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)

    asyncio.run(hunting_runtime.stop_hunting("rt-hunt-0001"))
    assert fake.statuses == [("rt-hunt-0001", "stopped")]


def test_stop_hunting_cancels_a_running_run(monkeypatch):
    """The phase-1 hard stop: stop_hunting cancels the running task (registered
    on the module runtime), and the run lands `stopped` - the task's own
    cancellation never re-stamps a status over the stop."""
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)

    async def slow(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr("polymerhus.attack.hunting.hunt_orchestrator.arun_orchestration", slow)

    from polymerhus.app.runtime import RuntimeManager

    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    try:
        # mirror launch_hunting: the row opens (running) BEFORE the schedule
        hunting_run_id = fake.create_hunting_run("rt-project")
        rm.schedule(
            "hunting",
            hunting_runtime.start_hunting("rt-project", run_id=hunting_run_id),
            name=hunting_run_id,
        )
        asyncio.run(hunting_runtime.stop_hunting(hunting_run_id))
        assert fake.statuses == [("running", hunting_run_id), (hunting_run_id, "stopped")]
    finally:
        rm.shutdown()


# --- the tear-down flush hook (seam 3.1) ---------------------------------------

def test_flush_hunting_checkpointer_is_a_safe_noop():
    """With no PG the hook is a no-op - it never raises (fail-open)."""
    hunting_runtime.flush_hunting_checkpointer()


def test_flush_hunting_checkpointer_calls_a_flusher_when_present(monkeypatch):
    calls: list[str] = []

    class _Saver:
        def __init__(self):
            self.flusher = lambda: calls.append("flushed")  # noqa: E731

    monkeypatch.setattr(
        "polymerhus.app.llm.checkpoints.get_session_checkpointer",
        lambda: _Saver(),
    )
    hunting_runtime.flush_hunting_checkpointer()
    assert calls == ["flushed"]


# --- the scheduling marshalling harness (seam 2.2) ------------------------------

def test_schedule_hunting_requires_an_active_runtime():
    """Since #122 there is no in-process fallback: the harness must fail closed
    (the launch endpoint's `hunting_control_plane_available()` 503s first)."""
    async def job():
        return "done"

    with pytest.raises(RuntimeError, match="control-plane runtime is not active"):
        hunting_runtime.schedule_hunting(job(), name="hunting:test")


def test_schedule_hunting_routes_through_the_runtime_when_active():
    """With `polymerhus.app.runtime` active the harness schedules the coroutine
    onto the hunting module's registry and its result comes back."""
    from polymerhus.app.runtime import RuntimeManager

    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    ran: list[str] = []
    try:
        async def job():
            ran.append("ran")
            return "done"

        fut = hunting_runtime.schedule_hunting(job(), name="rt-hunt-0002")
        assert fut.result(timeout=5) == "done"
        assert ran == ["ran"]
    finally:
        rm.shutdown()


def test_cancel_hunting_is_a_safe_no_op_with_no_active_run():
    """Cancelling with no active runtime is fail-open: a warning, no raise
    (stop_hunting's teardown must never blow up before the control plane
    lands)."""
    hunting_runtime.cancel_hunting("rt-hunt-none")


# the run_orchestration sync lane still works through the module boundaries
def test_explicit_root_store_trail_is_written(tmp_path):
    store = HuntStore(tmp_path)
    report = run_orchestration(
        "rt-project", "run-rt", [_candidate()], _tools(store),
        dispatch_fn=lambda config, routed=(): DispatchResult(
            spec_ref="s", pod_result_ref="p", hypothesis_verdict="successful",
            feedback="ok",
        ),
    )
    assert report.hunts_dispatched == 1
    assert len(store.list_records("run-rt", "hunt")) == 1