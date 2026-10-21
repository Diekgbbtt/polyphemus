"""Contract tier: the whole hunting pipeline observable through the run
bootstrap coroutine with injected fakes (tracker #173, ADR #169 Q2a/Q3/Q11/
Q12/Q15/Q16, spec #169 - AC1 through AC5).

The fakes model the existing test conventions (`test_hunting_runtime.py`
seam fakes, `test_hunting_surfer_tick.py`'s control-plane stubs,
`test_runtime_manager.py`'s real-runtime fixture): a `_FakeControl` that
RUNS the dispatched sessions as tasks on the test loop (so no live runtime
is needed for the pipeline flow), a `_FakePg` whose `hunting_runs` rows feed
the ONE-live-run-per-project guard, and configurable hunt/pod session fakes.
No live LLM, no live DB, no live process.

Covers, per AC:

- AC1: bootstrapping schedules the modeller pass AND the run-scoped
  surfer as sessions (their Q13-extension session ids land in the control
  plane); the ONE-live-run-per-project guard refuses a second concurrent
  launch and lets a run's own pinned row through.
- AC2: a produced loop file dispatches ONE hunter session (gate-bounded:
  N loops fan out, the shared dispatch gate caps concurrent hunters); a
  produced ratified spec dispatches ONE pod session through the SAME mover.
  T4b (#387): the loop file is the ONLY hunter dispatch input - the retired
  config family is not read, not dispatched and not work.
- AC3: the hunt session enters an idle loop after its graph ends; a delivered
  PodExport is consumed and recorded by the stub (a freeform note on the
  hunter memory), nothing more.
- AC4: the run lands `complete` ONLY on quiesce - it must NOT complete while
  a session is still live or produced dirs are non-empty; stop cancels every
  session by id and leaves the registry empty with `stopped` persisted.
- AC5: all of the above through the bootstrap coroutine.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    hunter_session_id,
    pod_session_id,
    threat_modeller_session_id,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.surfer import surfer_session_id
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import UnitOutcome

from tests.hunting_fixtures import intake_unit, loop_row, produce_model

UNIT = "Service:slug:a"
# The sanitised on-disk unit directory (the store's derived symbol) and the
# per-loop dispatch identity the produced loop file IS (S2 8.4, S3 8.9). The
# hunter memory key IS that loop dispatch id - never a config key.
UNIT_NAME = "Service-slug-a"
DISPATCH_ID = f"{UNIT_NAME}__loop-1"
RUN = "wiring-run-1"
PROJECT = "wiring-proj-1"
SPEC_FILE = "sqli_blind"

SERVICE_A = UNIT


async def _noop_pass(project_id, run_id, unit_id, tools, **kwargs):
    """These tests are about the SURFER/mover pipeline, not the modeller: the
    pass models nothing (a degraded unit, no loop files), so only the
    PRE-PRODUCED loop file drives dispatch."""
    return UnitOutcome(unit_id=unit_id, status="degraded")


def _preproduce(models, *, loops=None, unit=UNIT, run_id=RUN):
    """Pre-produce one COMPLETED valid model directly into the run's threat
    model store - the dispatch input the modeller would write (T4b #387: the
    loop file replaced the retired config family). `loops` overrides the single
    default `high` loop (the fan-out fixture)."""
    return produce_model(
        models, project_id=PROJECT, unit_id=unit, run_id=run_id,
        loops=[loop_row()] if loops is None else loops)


class _FakePg:
    """The fake pg accessors: mint a deterministic hunting_run_id, record every
    status write in order, let the guard preseed a live run, and fail on
    demand (the seam's fail-open paths)."""

    def __init__(self, *, fail_create=False, fail_status=False,
                 seeded_running: tuple[str, ...] = ()):
        self.fail_create = fail_create
        self.fail_status = fail_status
        self.statuses: list[tuple[str, str]] = []
        self.stats_writes: list[tuple[str, str, dict | None]] = []
        self.seed = list(seeded_running)
        self.records: dict[str, dict] = {}
        self.next_id = RUN

    def create_hunting_run(self, project_id: str) -> str:
        if self.fail_create:
            raise OSError("pg down (fixture)")
        self.statuses.append(("running", self.next_id))
        return self.next_id

    def set_hunting_run_status(self, hunting_run_id: str, status: str, *,
                               stats: dict | None = None) -> None:
        if self.fail_status:
            raise OSError("pg down (fixture)")
        self.statuses.append((hunting_run_id, status))
        self.stats_writes.append((hunting_run_id, status, stats))

    def set_hunting_run_stats(self, hunting_run_id: str, stats: dict) -> None:
        self.records.setdefault(hunting_run_id, {}).update(stats or {})

    def get_hunting_run(self, hunting_run_id: str) -> dict | None:
        if hunting_run_id not in self.records:
            return None
        return {"hunting_run_id": hunting_run_id,
                "stats": dict(self.records[hunting_run_id])}

    def list_hunting_runs(self, project_id: str) -> list[dict]:
        state: dict[str, dict] = {
            sid: {"hunting_run_id": sid, "status": "running"}
            for sid in self.seed
        }
        for first, second in self.statuses:
            if first == "running":
                state[second] = {"hunting_run_id": second, "status": "running"}
            else:
                state[first] = {"hunting_run_id": first, "status": second}
        return list(state.values())


class _FakeControl:
    """The session-capable control-plane fake: RUNS every dispatched/started
    session as a task on the current loop (so the whole pipeline is observable
    through the bootstrap with no live runtime), mirrors the real manager's
    registry through the live-task set, and can refuse/close sessions. The
    optional `gate` is handed out to the run's session builders (Q15)."""

    def __init__(self, refuse: set[str] | None = None, *, gate=None):
        self._refuse = set(refuse or ())
        self._gate = gate
        self._tasks: dict[str, asyncio.Task] = {}
        self.started: list[str] = []

    def live_session_ids(self):
        return {sid for sid, task in self._tasks.items() if not task.done()}

    def live(self, run_id: str):
        from polymerhus.attack.hunting.surfer import is_run_session_id
        return {sid for sid in self.live_session_ids() if is_run_session_id(sid, run_id)}

    def start_session(self, session_id, coro):
        self.started.append(session_id)
        if session_id in self._refuse or coro is None:
            if coro is not None:
                try:
                    coro.close()
                except Exception:
                    pass
            return None
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks[session_id] = task
        return task

    def dispatch(self, session_id, coro):
        return self.start_session(session_id, coro) is not None

    def cancel_session(self, session_id):
        task = self._tasks.get(session_id)
        if task is not None and not task.done():
            task.cancel()

    def gate(self):
        return self._gate


@pytest.fixture
def stores(tmp_path):
    return (
        ThreatModelStore(tmp_path / "models"),
        HunterMemoryStore(tmp_path / "hunter"),
        PodMemoryStore(root_dir=tmp_path / "pod"),
    )


async def _wait_until(pred, timeout=5):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"condition not met within {timeout}s")


# --- AC1: the bootstrap schedules the modeller pass + the surfer; one
# live hunting run per project is enforced. ----------------------------------

def test_bootstrap_schedules_orchestrator_and_surfer_sessions(stores, monkeypatch):
    """Bootstrapping a run schedules the modeller pass under its ADR Q13 session
    id and the run-scoped surfer under its Q13-extension id, then drives them to
    a `complete` quiesce (a pre-produced loop file -> a fake hunt session
    concluding with no specs)."""
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    models, hunter, pod = stores
    control = _FakeControl()
    _preproduce(models)

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=_noop_hunts,
        pod_builder=_noop_pods,
        tick_interval=0.001,
    ))
    assert hid == RUN
    assert threat_modeller_session_id(RUN) in control.started
    assert surfer_session_id(RUN) in control.started
    assert fake.statuses == [("running", RUN), (RUN, "complete")]
    assert control.live(RUN) == set()


def _noop_hunts(*, run_id, project_id, hunter_store, **kw):
    async def dispatch(payload):
        hunt_key = payload.get("dispatch_id")
        if hunt_key:
            hunter_store.finalize_specs(project_id, hunt_key, run_id=run_id)
        return None
    return dispatch, None


async def _noop_pods(spec, **kw):
    return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
            "evidence": {"trail": []}, "clean": True, "iterations": 0}


def test_guard_refuses_a_second_live_run_per_project(stores, monkeypatch):
    """The ONE-live-run-per-project guard (spec US10): with an existing
    `running` hunting run for the project, the bootstrap returns None early -
    nothing scheduled, no status touched."""
    fake = _FakePg(seeded_running=(RUN,))
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    models, hunter, pod = stores
    control = _FakeControl()

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=_noop_hunts,
        pod_builder=_noop_pods,
    ))
    assert hid is None                      # refused
    assert control.started == []            # nothing scheduled
    assert fake.statuses == []              # no row touched


def test_guard_refusal_closes_a_preopened_row_in_band(stores, monkeypatch):
    """T5 orphan resolution: when the API pre-opened the run's row (the
    creation marker) and the bootstrap's own guard still refuses (a concurrent
    launch slipped past the API check), the refusal closes the pre-opened
    `running` row to `failed` in-band - no orphan `running` row is left behind,
    and the at-most-once marker (the row) is honestly terminal."""
    fake = _FakePg(seeded_running=("other-live-run",))
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    models, hunter, pod = stores
    control = _FakeControl()

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        run_id=RUN,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=_noop_hunts,
        pod_builder=_noop_pods,
    ))
    assert hid is None                 # refused
    assert control.started == []       # nothing scheduled
    assert fake.statuses == [(RUN, "failed")]  # the pre-opened row is closed


def test_guard_lets_the_runs_own_pinned_row_through(stores, monkeypatch):
    fake = _FakePg(seeded_running=(RUN,))
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    models, hunter, pod = stores
    control = _FakeControl()
    _preproduce(models)

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        run_id=RUN,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=_noop_hunts,
        pod_builder=_noop_pods,
        tick_interval=0.001,
    ))
    assert hid == RUN
    assert threat_modeller_session_id(RUN) in control.started
    assert fake.statuses == [(RUN, "complete")]


# --- AC2: produced loop files dispatch one hunter per loop (gate-bounded);
# produced specs dispatch pods through the same mover. -----------------------

def test_a_produced_loop_dispatches_one_hunter_and_moves(stores, monkeypatch):
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    _preproduce(models)
    control = _FakeControl()

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=_noop_hunts,
        pod_builder=_noop_pods,
        tick_interval=0.001,
    ))
    # ONE hunter dispatched for the produced loop file, under the Q13 id
    assert hunter_session_id(RUN, DISPATCH_ID) in control.started
    # and the loop file + its model document moved produced -> consumed (the
    # at-least-once marker, S2 8.4)
    assert models.read_produced_loops(PROJECT) == []
    assert models.read_completed_units(PROJECT) == [UNIT]


def test_n_loops_fan_out_but_the_gate_caps_concurrent_hunters(stores, monkeypatch):
    """AC2 gate-bounded fan-out: three produced loop files dispatch three hunter
    sessions, but the shared hunting dispatch gate (width 2, injected) caps
    the number of concurrently running hunt graphs at 2."""
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    _preproduce(models, loops=[loop_row(), loop_row(), loop_row()])
    control = _FakeControl(gate=asyncio.Semaphore(2))
    tracking = {"now": 0, "max": 0, "sees": []}

    def gated_hunts(*, run_id, project_id, hunter_store, **kw):
        async def dispatch(payload):
            tracking["now"] += 1
            tracking["max"] = max(tracking["max"], tracking["now"])
            tracking["sees"].append(payload["dispatch_id"])
            try:
                await asyncio.sleep(0.05)
            finally:
                tracking["now"] -= 1
            hunter_store.finalize_specs(
                project_id, payload["dispatch_id"], run_id=run_id)
            return None
        return dispatch, None

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        gate=control.gate(),
        tick_interval=0.001,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=gated_hunts,
        pod_builder=_noop_pods,
    ))
    assert len(tracking["sees"]) == 3                 # all three loops dispatched
    assert tracking["max"] == 2                       # the gate capped concurrency
    assert models.read_produced_loops(PROJECT) == []  # all three moved


def _write_ratified_spec(hunter, *, consume_me: str = "") -> None:
    """One produced `ratified` spec under the loop dispatch id (S3 8.7): the
    pod family's dispatch gate."""
    hunter.write_specs(
        PROJECT, DISPATCH_ID,
        [{"status": "ratified", "fault_keyword": "sqli",
          "strategy_keyword": "blind", "consume_me": consume_me}],
    )


def test_ratified_spec_dispatches_one_pod_through_the_same_mover(stores, monkeypatch):
    """AC2: a hunt session writes a `ratified` spec (the terminal gate for the
    spec family); the SAME mover that dispatched the hunter dispatches ONE pod
    session under the ADR Q13 pod id, and the spec moves produced -> consumed."""
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    _preproduce(models)
    control = _FakeControl()
    pod_calls: list[tuple[str, str]] = []

    def spec_hunts(*, run_id, project_id, hunter_store, **kw):
        async def dispatch(payload):
            _write_ratified_spec(hunter_store)
            hunter_store.finalize_specs(
                project_id, payload["dispatch_id"], run_id=run_id)
            return None
        return dispatch, None

    async def spec_pods(spec, *, run_id, project_id, memory_store, spec_id):
        pod_calls.append((spec_id, str(spec.get("consume_me", ""))))
        return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
                "evidence": {"trail": []}, "clean": True, "iterations": 1}

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        tick_interval=0.001,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=spec_hunts,
        pod_builder=spec_pods,
    ))
    assert pod_calls == [(SPEC_FILE, "")]                  # the derived spec id crossed the handoff
    assert pod_session_id(RUN, DISPATCH_ID, SPEC_FILE) in control.started
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == []   # moved to consumed
    assert len(hunter.read_specs(PROJECT, DISPATCH_ID, sides=("consumed",))) == 1


def test_pod_provider_failure_interrupts_the_run(stores, monkeypatch):
    """#312/#329: a provider failure in a dispatched POD session is
    infrastructure - the run pauses (`interrupted` with the provider cause), it
    never quiesces `complete` silently. Completes #329's pod propagation to the
    run terminal (the propagation was inert while the scheduled session's raise
    landed in an unawaited future)."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    _preproduce(models)

    def spec_hunts(*, run_id, project_id, hunter_store, **kw):
        async def dispatch(payload):
            _write_ratified_spec(hunter_store)
            hunter_store.finalize_specs(
                project_id, payload["dispatch_id"], run_id=run_id)
            return None
        return dispatch, None

    async def throttled_pods(spec, *, run_id, project_id, memory_store, spec_id):
        raise ProviderUnavailableError(
            "Go usage limit exceeded", status_code=429, quota_exhausted=True)

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=_FakeControl(),
        tick_interval=0.001,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=spec_hunts,
        pod_builder=throttled_pods,
    ))
    _, status, stats = fake.stats_writes[-1]
    assert status == "interrupted"
    assert stats["provider_status"] == 429
    assert stats["quota_exhausted"] is True


def test_a_loop_file_from_another_run_never_dispatches_or_blocks_quiesce(
        stores, monkeypatch):
    """S2 8.3/8.4: the dispatch read is RUN-scoped. A produced loop file of
    ANOTHER run is not this run's work: it is neither dispatched nor moved,
    and it does not hold the quiesce (the run lands `complete`). T4b (#387)
    replaced the retired config status-gate test with this loop analogue: a
    produced item that cannot dispatch is never "pending work"."""
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)

    _preproduce(models, run_id="another-run")
    control = _FakeControl()
    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        tick_interval=0.001,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=_noop_hunts,
        pod_builder=_noop_pods,
    ))
    assert not any(":hunt:" in sid for sid in control.started)
    assert not any(":hunt:" in sid for sid in control.live(RUN))
    assert [entry["loop_id"] for entry in
            models.read_produced_loops(PROJECT)[0]["loops"]] == ["loop-1"]
    assert fake.statuses == [("running", RUN), (RUN, "complete")]


# --- AC3: the idle loop consumes and records a delivered PodExport ----------

def _write_spec(hunter, *, hunt_key=DISPATCH_ID, status: str = "ratified"):
    return hunter.write_specs(
        PROJECT, hunt_key,
        [{"status": status, "fault_keyword": "sqli", "strategy_keyword": "blind"}])


def test_idle_loop_consumes_and_records_a_delivered_pod_export(stores, monkeypatch):
    """AC3: after the hunt graph ends, the session idles on its inbox; a
    delivered PodExport is CONSUMED AND RECORDED (a freeform note on the
    hunter memory, stamped verdict-stub) and NOTHING more happens - no
    re-evaluation, no further dispatch."""
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    _preproduce(models)
    control = _FakeControl()
    export = {"verdict": "successful", "terminal_reason": "symptom-confirmed",
              "evidence": {"trail": []}, "clean": True, "iterations": 1,
              "marker": "the-export"}

    def spec_hunts(*, run_id, project_id, hunter_store, **kw):
        async def dispatch(payload):
            _write_ratified_spec(hunter_store)
            hunter_store.finalize_specs(
                project_id, payload["dispatch_id"], run_id=run_id)
            return None
        return dispatch, None

    async def export_pods(spec, **kw):
        export["consumed_at"] = "now"
        return export

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        tick_interval=0.001,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=spec_hunts,
        pod_builder=export_pods,
    ))
    notes = hunter.read_notes(PROJECT)
    assert len(notes) == 1
    record = notes[0]
    assert record["kind"] == "freeform"
    assert record["provenance"].get("verdict_stub") is True
    assert record["provenance"].get("source") == pod_session_id(RUN, DISPATCH_ID, SPEC_FILE)
    assert "the-export" in record["body"]           # the export payload was recorded
    # the DURABLE parent-keyed record is keyed by the parent's loop dispatch id
    # (S3 8.9) - the spec's own folder key
    assert record["hunt_key"] == DISPATCH_ID
    # the record is keyed <config_key>:pod-export:<spec_id> with action update:
    # the note key carries NO `:`-session-id path, and the pod session id is
    # recoverable ONLY from provenance["source"] (#199)
    assert record["note_name"] == f"pod-export:{SPEC_FILE}"
    assert record["key"] == f"{DISPATCH_ID}:pod-export:{SPEC_FILE}"
    assert "hunting:" not in record["key"]
    assert pod_session_id(RUN, DISPATCH_ID, SPEC_FILE) not in record["key"]
    # NOTHING more: the spec was consumed only by the mover (no re-dispatch),
    # and the hunter produced no further records/specs.
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == []
    assert len(hunter.read_specs(PROJECT, DISPATCH_ID, sides=("consumed",))) == 1


# --- identity-based refactor: the cross-run pod-dispatch wedge regression ------

def test_cross_run_ratified_spec_dispatches_a_pod_without_a_parent(stores,
                                                                    monkeypatch):
    """The pod-dispatch WEDGE regression (identity-based refactor, 2026-08-25):

    A produced `ratified` spec whose parent config was consumed by an EARLIER
    run (so NO live parent hunter inbox exists in THIS run) must still dispatch
    a pod - the dispatch is gated on the spec's OWN persisted status, never on
    a chain-adjacent parent's liveness. AND the move lands (produced->consumed)
    AND the durable parent-keyed export record exists keyed by the parent's
    canonical DISPATCH_ID, so the run can reach quiesce (never wedged).

    The produced spec is written DIRECTLY into the hunter store (no hunter
    dispatch this run - no produced loop file) - exactly the cross-run shape that
    previously returned `None` from `_spec_dispatch` (missing parent inbox) and
    hung the run."""
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)

    # A produced `ratified` spec with NO live parent hunter inbox at all - the
    # parent hunt was consumed by an earlier run, no hunter dispatches.
    _write_spec(hunter, hunt_key=DISPATCH_ID, status="ratified")
    pod_calls: list[str] = []

    async def record_pods(spec, **kw):
        pod_calls.append(kw["spec_id"])
        return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
                "evidence": {"trail": []}, "clean": True, "iterations": 1}

    control = _FakeControl()
    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[],
        modeller_pass_fn=_noop_pass,
        control=control,
        tick_interval=0.001,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=_noop_hunts,
        pod_builder=record_pods,
    ))
    # the pod ran, and the spec moved produced -> consumed (the marker)
    assert pod_calls == [SPEC_FILE]
    assert pod_session_id(RUN, DISPATCH_ID, SPEC_FILE) in control.started
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == []
    assert len(hunter.read_specs(PROJECT, DISPATCH_ID, sides=("consumed",))) == 1
    # the DURABLE parent-keyed export record exists keyed by the canonical
    # DISPATCH_ID (no live parent; the durable note is the only record)
    notes = hunter.read_notes(PROJECT)
    assert len(notes) == 1
    assert notes[0]["hunt_key"] == DISPATCH_ID
    assert notes[0]["provenance"].get("verdict_stub") is True
    assert notes[0]["provenance"].get("source") == pod_session_id(
        RUN, DISPATCH_ID, SPEC_FILE)
    assert "symptom-confirmed" in notes[0]["body"]
    # the record is keyed <config_key>:pod-export:<spec_id>: the note key
    # carries NO `:`-session-id path, the session id lives only in provenance
    assert notes[0]["note_name"] == f"pod-export:{SPEC_FILE}"
    assert notes[0]["key"] == f"{DISPATCH_ID}:pod-export:{SPEC_FILE}"
    assert "hunting:" not in notes[0]["key"]
    # the run reached quiesce - a produced `ratified` spec can never wedge it
    assert fake.statuses == [("running", RUN), (RUN, "complete")]
    assert control.live(RUN) == set()


# --- AC4: terminal only on quiesce; stop cancels every session. ---------------

def test_run_does_not_complete_while_a_session_is_live(stores, monkeypatch):
    """The run lands `complete` ONLY on quiesce: with a pod session still
    live (blocked mid-run), no terminal status is stamped; once the pod
    settles, the run completes."""
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    _preproduce(models)
    control = _FakeControl()
    release = asyncio.Event()

    def spec_hunts(*, run_id, project_id, hunter_store, **kw):
        async def dispatch(payload):
            _write_ratified_spec(hunter_store)
            hunter_store.finalize_specs(
                project_id, payload["dispatch_id"], run_id=run_id)
            return None
        return dispatch, None

    async def blocked_pod(spec, **kw):
        await release.wait()
        return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
                "evidence": {"trail": []}, "clean": True, "iterations": 1}

    async def _body():
        task = asyncio.get_running_loop().create_task(hunting_runtime.start_hunting(
            PROJECT,
            intake_units=[intake_unit(UNIT)],
            modeller_pass_fn=_noop_pass,
            control=control,
            tick_interval=0.001,
            threat_store=models,
            hunter_store=hunter,
            pod_store=pod,
            hunter_builder=spec_hunts,
            pod_builder=blocked_pod,
        ))
        await _wait_until(lambda: any(
            ":pod:" in sid for sid in control.live(RUN)))
        await asyncio.sleep(0.05)
        # A live pod session: the run MUST NOT be complete yet.
        assert ("running", RUN) in fake.statuses
        assert not any(status == "complete" for _, status in fake.statuses)
        assert any(":pod:" in sid for sid in control.live(RUN))
        release.set()
        await task
        assert fake.statuses == [("running", RUN), (RUN, "complete")]
        assert control.live(RUN) == set()

    asyncio.run(_body())


def test_run_does_not_complete_while_produced_is_non_empty(stores, monkeypatch):
    """Quiesce also requires the produced dirs drained: with an admitted but
    not-yet-produced pipeline (a produced loop file the surfer cannot dispatch
    because the control plane refuses the hunter session), nothing completes
    while it sits produced."""
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    _preproduce(models)
    hunt_refuse = hunter_session_id(RUN, DISPATCH_ID)
    control = _FakeControl(refuse={hunt_refuse})

    async def _body():
        task = asyncio.get_running_loop().create_task(hunting_runtime.start_hunting(
            PROJECT,
            intake_units=[intake_unit(UNIT)],
            modeller_pass_fn=_noop_pass,
            control=control,
            tick_interval=0.001,
            threat_store=models,
            hunter_store=hunter,
            pod_store=pod,
            hunter_builder=_noop_hunts,
            pod_builder=_noop_pods,
        ))
        # The refused dispatch is retried every tick; the loop file stays produced.
        await _wait_until(lambda: bool(models.read_produced_loops(PROJECT)))
        await asyncio.sleep(0.05)
        assert not any(status == "complete" for _, status in fake.statuses)
        assert len(models.read_produced_loops(PROJECT)[0]["loops"]) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_body())


def test_stop_cancels_every_session_and_leaves_the_registry_empty(stores, monkeypatch):
    """AC4 stop: stop cancels EVERY session of the run by session id (the
    orchestrator, the surfer, a blocked hunter, a blocked pod) through the real
    shared control plane, persists `stopped`, and leaves the registry empty."""
    from polymerhus.app.runtime import RuntimeManager

    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    _preproduce(models)

    def block_hunts(*, run_id, project_id, hunter_store, **kw):
        async def dispatch(payload):
            _write_ratified_spec(hunter_store)
            await asyncio.sleep(30)          # mid-graph forever (until stop)
            return None
        return dispatch, None

    async def block_pods(spec, **kw):
        await asyncio.sleep(30)              # mid-run forever (until stop)
        return {"verdict": "unsuccessful", "terminal_reason": "space-exhausted"}

    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    try:
        hunting_run_id = fake.create_hunting_run(PROJECT)
        rm.schedule(
            "hunting",
            hunting_runtime.start_hunting(
                PROJECT,
                run_id=hunting_run_id,
                intake_units=[intake_unit(UNIT)],
                modeller_pass_fn=_noop_pass,
                threat_store=models,
                hunter_store=hunter,
                pod_store=pod,
                hunter_builder=block_hunts,
                pod_builder=block_pods,
                tick_interval=0.01,
            ),
            name=hunting_run_id,
        )
        # both the hunter AND the pod sessions are live mid-run
        asyncio.run(_wait_until_async(
            lambda: any(":hunt:" in sid for sid in rm.run_ids("hunting"))
            and any(":pod:" in sid for sid in rm.run_ids("hunting"))
        ))
        assert not any(status == "complete" for _, status in fake.statuses)

        asyncio.run(hunting_runtime.stop_hunting(hunting_run_id))
        assert fake.statuses == [("running", hunting_run_id),
                                 (hunting_run_id, "stopped")]
        asyncio.run(_wait_until_async(
            lambda: rm.run_ids("hunting") == []))
        assert rm.run_ids("hunting") == []
    finally:
        rm.shutdown()


async def _wait_until_async(pred, timeout=5):
    await _wait_until(pred, timeout)


# --- the mover's status gate is the same gate the quiesce uses ----------------

def test_undispatchable_statuses_never_block_quiesce(stores, monkeypatch):
    """A hypothesised spec draft must neither dispatch nor hold the quiesce
    open: the run still completes. The retired config family has no status
    gate left on the produced path (T4b #387) - the loop validity predicate
    owns that refusal now."""
    models, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    # Seed the produced draft directly: no loop file exists, so F-026 has no
    # consumed loop to recover and the test isolates the mover's own-status gate.
    hunter.write_specs(
        PROJECT, DISPATCH_ID,
        [{"status": "hypothesised", "fault_keyword": "sqli",
          "strategy_keyword": "blind"}])

    control = _FakeControl()
    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_noop_pass,
        control=control,
        tick_interval=0.001,
        threat_store=models,
        hunter_store=hunter,
        pod_store=pod,
        hunter_builder=_noop_hunts,
        pod_builder=_noop_pods,
    ))
    # the hypothesised draft stayed produced but never blocked completion
    assert fake.statuses == [("running", RUN), (RUN, "complete")]
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == [SPEC_FILE]
    assert not any(":pod:" in sid for sid in control.started)
