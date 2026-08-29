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

- AC1: bootstrapping schedules the orchestrator pass AND the run-scoped
  surfer as sessions (their Q13-extension session ids land in the control
  plane); the ONE-live-run-per-project guard refuses a second concurrent
  launch and lets a run's own pinned row through.
- AC2: a produced ratified config dispatches ONE hunter session (gate-bounded:
  N configs fan out, the shared dispatch gate caps concurrent hunters); a
  produced specified spec dispatches ONE pod session through the SAME mover.
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
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    DispatchResult,
    EnvisionedDirection,
    GateDecision,
    NoteDecision,
    NoteRecord,
    OrchestratorTools,
    RatifyDecision,
    ReadOnlyGraphView,
    Witness,
    revival_key,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    hunter_session_id,
    orchestrator_session_id,
    pod_session_id,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.surfer import surfer_session_id

UNIT = "Service:slug:a"
# The production fault class IS a CWE id (the `_`-joined fault_key folder is
# only parseable when the middle segment matches `CWE-\d+`, G4) - a fake
# "fault-x" class would make the production `_`-joined form unrepresentable.
FAULT = "CWE-352"
CLASS = "CSRF"
# The PRODUCTION fault_key folder form (G4/ADR Q13): `_`-joined
# `<unit_id>_<CWE_ID>_<vulnerability_class>`, the config file-name stem the
# hunter writes as its test-specs folder. The `::`-joined semantic config_key
# is a DIFFERENT string - and the whole identity-based-refactor regression
# exists to prove the mover joins the two sides on the canonical config_key
# (this fixture previously used the `::` form, which masked the pod-dispatch
# miss).
FAULT_KEY = f"{UNIT}_{FAULT}_{CLASS}"
CONFIG_KEY = f"{UNIT}::{FAULT}::{CLASS}"
RUN = "wiring-run-1"
PROJECT = "wiring-proj-1"
SPEC_FILE = "sqli_blind"

SERVICE_A = UNIT


def _candidate() -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=UNIT,
        fault_class=FAULT,
        applies_witnesses=Witness(deterministic="witness", llm="witness"),
        match_verdict="applies",
    )


def _tools(store) -> OrchestratorTools:
    return OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView(PROJECT, read_fn=lambda cy, p: []),
    )


def _single_class_seams():
    """The fixture phase seams: one candidate, ONE elicited CSRF class, the
    draft ratified, one note written - the minimal pipeline driver."""
    def hypothesise(inp):
        return GateDecision(directions=[EnvisionedDirection(
            unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
            rationale="r", research_direction="rd",
            vulnerability_classes=[CLASS]) for c in inp.candidates])

    def ratify(inp):
        configs = []
        for draft in inp.configs:
            amended = draft.model_copy(deep=True)
            amended.status = "ratified"
            configs.append(amended)
        return RatifyDecision(configs=configs)

    def note(inp):
        return NoteDecision(notes=[NoteRecord(
            key=revival_key(inp.pair.unit_id, inp.pair.fault_class),
            note="fixture note")])

    return hypothesise, ratify, note


def _fanout_seams(classes=("CSRF", "IDOR", "XSS")):
    """The fan-out fixture: ONE candidate eliciting THREE distinct classes, so
    the mint fans out one config per class (AC2's N-config fan-out)."""
    def hypothesise(inp):
        return GateDecision(directions=[EnvisionedDirection(
            unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
            rationale="r", research_direction="rd",
            vulnerability_classes=list(classes)) for c in inp.candidates])

    def ratify(inp):
        return RatifyDecision(configs=[
            draft.model_copy(deep=True).model_copy(update={"status": "ratified"})
            for draft in inp.configs
        ])

    def note(inp):
        return NoteDecision(notes=[NoteRecord(
            key=revival_key(inp.pair.unit_id, inp.pair.fault_class),
            note="fan-out note")])

    return hypothesise, ratify, note


class _FakePg:
    """The fake pg accessors: mint a deterministic hunting_run_id, record every
    status write in order, let the guard preseed a live run, and fail on
    demand (the seam's fail-open paths)."""

    def __init__(self, *, fail_create=False, fail_status=False,
                 seeded_running: tuple[str, ...] = ()):
        self.fail_create = fail_create
        self.fail_status = fail_status
        self.statuses: list[tuple[str, str]] = []
        self.seed = list(seeded_running)
        self.next_id = RUN

    def create_hunting_run(self, project_id: str) -> str:
        if self.fail_create:
            raise OSError("pg down (fixture)")
        self.statuses.append(("running", self.next_id))
        return self.next_id

    def set_hunting_run_status(self, hunting_run_id: str, status: str) -> None:
        if self.fail_status:
            raise OSError("pg down (fixture)")
        self.statuses.append((hunting_run_id, status))

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
        HuntStore(tmp_path / "hunts"),
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


# --- AC1: the bootstrap schedules the orchestrator pass + the surfer; one
# live hunting run per project is enforced. ----------------------------------

def test_bootstrap_schedules_orchestrator_and_surfer_sessions(stores, monkeypatch):
    """Bootstrapping a run schedules the orchestrator pass under its ADR Q13
    session id and the run-scoped surfer under its Q13-extension id, then
    drives them to a `complete` quiesce (a ratified config -> a fake hunt
    session concluding with no specs)."""
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    hunt, hunter, pod = stores
    control = _FakeControl()
    h, r, n = _single_class_seams()

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[_candidate()], tools=_tools(hunt),
        hypothesise_fn=h, ratify_fn=r, note_fn=n,
        control=control,
        hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=_noop_hunts, pod_builder=_noop_pods,
        tick_interval=0.001,
    ))
    assert hid == RUN
    assert orchestrator_session_id(RUN) in control.started
    assert surfer_session_id(RUN) in control.started
    assert fake.statuses == [("running", RUN), (RUN, "complete")]
    assert control.live(RUN) == set()


def _noop_hunts(*, run_id, project_id, hunt_store, hunter_store, **kw):
    async def dispatch(config):
        return DispatchResult(hypothesis_verdict=None, feedback="concluded (fixture)")
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
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    hunt, hunter, pod = stores
    control = _FakeControl()

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[_candidate()], tools=_tools(hunt),
        control=control, hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=_noop_hunts, pod_builder=_noop_pods,
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
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    hunt, hunter, pod = stores
    control = _FakeControl()

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN, candidates=[_candidate()], tools=_tools(hunt),
        control=control, hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=_noop_hunts, pod_builder=_noop_pods,
    ))
    assert hid is None                 # refused
    assert control.started == []       # nothing scheduled
    assert fake.statuses == [(RUN, "failed")]  # the pre-opened row is closed


def test_guard_lets_the_runs_own_pinned_row_through(stores, monkeypatch):
    fake = _FakePg(seeded_running=(RUN,))
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    hunt, hunter, pod = stores
    control = _FakeControl()
    h, r, n = _single_class_seams()

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN, candidates=[_candidate()], tools=_tools(hunt),
        hypothesise_fn=h, ratify_fn=r, note_fn=n,
        control=control, hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=_noop_hunts, pod_builder=_noop_pods, tick_interval=0.001,
    ))
    assert hid == RUN
    assert orchestrator_session_id(RUN) in control.started
    assert fake.statuses == [(RUN, "complete")]


# --- AC2: produced configs dispatch one hunter per config (gate-bounded);
# produced specs dispatch pods through the same mover. -----------------------

def test_ratified_config_dispatches_one_hunter_and_moves(stores, monkeypatch):
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    h, r, n = _single_class_seams()
    control = _FakeControl()

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[_candidate()], tools=_tools(hunt),
        hypothesise_fn=h, ratify_fn=r, note_fn=n,
        control=control, hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=_noop_hunts, pod_builder=_noop_pods, tick_interval=0.001,
    ))
    # ONE hunter dispatched for the produced ratified config, under the Q13 id
    assert hunter_session_id(RUN, f"{UNIT}_{FAULT}_{CLASS}") in control.started
    # and the config moved produced -> consumed (the at-least-once marker)
    assert hunt.read_produced_configs(PROJECT) == []
    assert len(hunt.read_configs(PROJECT)) == 1


def test_n_configs_fan_out_but_the_gate_caps_concurrent_hunters(stores, monkeypatch):
    """AC2 gate-bounded fan-out: three ratified configs dispatch three hunter
    sessions, but the shared hunting dispatch gate (width 2, injected) caps
    the number of concurrently running hunt graphs at 2."""
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    h, r, n = _fanout_seams()
    control = _FakeControl(gate=asyncio.Semaphore(2))
    tracking = {"now": 0, "max": 0, "sees": []}

    def gated_hunts(*, run_id, project_id, hunt_store, hunter_store, **kw):
        async def dispatch(config):
            tracking["now"] += 1
            tracking["max"] = max(tracking["max"], tracking["now"])
            tracking["sees"].append(config.hunt_id)
            try:
                await asyncio.sleep(0.05)
            finally:
                tracking["now"] -= 1
            return DispatchResult(hypothesis_verdict=None, feedback="concluded (fixture)")
        return dispatch, None

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[_candidate()], tools=_tools(hunt),
        hypothesise_fn=h, ratify_fn=r, note_fn=n,
        control=control, gate=control.gate(), tick_interval=0.001,
        hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=gated_hunts, pod_builder=_noop_pods,
    ))
    assert len(tracking["sees"]) == 3                 # all three configs dispatched
    assert tracking["max"] == 2                       # the gate capped concurrency
    assert hunt.read_produced_configs(PROJECT) == []  # all three moved


def test_specified_spec_dispatches_one_pod_through_the_same_mover(stores, monkeypatch):
    """AC2: a hunt session writes a `specified` spec (the ratify gate for the
    spec family); the SAME mover that dispatched the hunter dispatches ONE pod
    session under the ADR Q13 pod id, and the spec moves produced -> consumed."""
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    h, r, n = _single_class_seams()
    control = _FakeControl()
    pod_calls: list[tuple[str, str]] = []

    def spec_hunts(*, run_id, project_id, hunt_store, hunter_store, **kw):
        async def dispatch(config):
            hunter_store.write_spec(
                project_id, FAULT_KEY,
                fault_keyword="sqli", strategy_keyword="blind",
                spec={
                    "status": "specified", "spec_id": SPEC_FILE,
                    "fault_key": FAULT_KEY,
                    "fault": {"fault_id": "f1", "mechanism": "m",
                              "supports": [], "conflicts": [], "test": "t",
                              "status": "specified"},
                    "strategy": "blind", "spec_ref": "sr", "experiment_ref": "",
                },
                mode="create", side="produced",
            )
            return DispatchResult(hypothesis_verdict=None, feedback="concluded")
        return dispatch, None

    async def spec_pods(spec, *, run_id, project_id, memory_store, spec_id):
        pod_calls.append((spec_id, str(spec.get("consume_me", ""))))
        return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
                "evidence": {"trail": []}, "clean": True, "iterations": 1}

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[_candidate()], tools=_tools(hunt),
        hypothesise_fn=h, ratify_fn=r, note_fn=n,
        control=control, tick_interval=0.001,
        hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=spec_hunts, pod_builder=spec_pods,
    ))
    assert pod_calls == [(SPEC_FILE, "")]                  # the semantic spec id crossed the handoff
    assert pod_session_id(RUN, FAULT_KEY, SPEC_FILE) in control.started
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []   # moved to consumed
    assert len(hunter.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))) == 1


def test_unratified_config_is_refused_and_stays_produced(stores, monkeypatch):
    """The status gate: a produced HYPOTHESISED (not yet ratified) config must
    NOT dispatch a hunter - it stays produced (never dropped, at-least-once) -
    and, once the orchestrator settles, it is not "work left to dispatch":
    it never blocks the run's quiesce (the dispatchable-status gate the
    quiesce predicate shares)."""
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)

    # The pass ends with the draft HYPOTHESISED (the ratify seam returns
    # nothing ratified): no hunter may ever dispatch for it.
    def hypothesise(inp):
        return GateDecision(directions=[EnvisionedDirection(
            unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
            rationale="r", research_direction="rd",
            vulnerability_classes=[CLASS]) for c in inp.candidates])

    def ratify(inp):
        return RatifyDecision(configs=[])

    def note(inp):
        return NoteDecision(notes=[])

    control = _FakeControl()
    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[_candidate()], tools=_tools(hunt),
        hypothesise_fn=hypothesise, ratify_fn=ratify, note_fn=note,
        control=control, tick_interval=0.001,
        hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=_noop_hunts, pod_builder=_noop_pods,
    ))
    assert not any(":hunt:" in sid for sid in control.started)
    assert not any(":hunt:" in sid for sid in control.live(RUN))
    assert len(hunt.read_produced_configs(PROJECT)) == 1   # refused, never moved
    assert fake.statuses == [("running", RUN), (RUN, "complete")]


# --- AC3: the idle loop consumes and records a delivered PodExport ----------

def _write_config(store, **overrides):
    data = {
        "unit_id": UNIT, "fault_class": FAULT, "vulnerability_class": CLASS,
        "status": "ratified",
    }
    data.update(overrides)
    return store.write_config(PROJECT, data)


def _write_spec(hunter, *, fault_key=FAULT_KEY, status: str = "specified"):
    return hunter.write_spec(
        PROJECT, fault_key, fault_keyword="sqli", strategy_keyword="blind",
        spec={"spec_id": SPEC_FILE, "fault_key": fault_key,
              "fault": {"fault_id": "f1", "mechanism": "m", "supports": [],
                        "conflicts": [], "test": "t", "status": "specified"},
              "strategy": "blind", "spec_ref": "sr", "experiment_ref": "",
              "status": status},
    )


def test_idle_loop_consumes_and_records_a_delivered_pod_export(stores, monkeypatch):
    """AC3: after the hunt graph ends, the session idles on its inbox; a
    delivered PodExport is CONSUMED AND RECORDED (a freeform note on the
    hunter memory, stamped verdict-stub) and NOTHING more happens - no
    re-evaluation, no further dispatch."""
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    h, r, n = _single_class_seams()
    control = _FakeControl()
    export = {"verdict": "successful", "terminal_reason": "symptom-confirmed",
              "evidence": {"trail": []}, "clean": True, "iterations": 1,
              "marker": "the-export"}

    def spec_hunts(*, run_id, project_id, hunt_store, hunter_store, **kw):
        async def dispatch(config):
            hunter_store.write_spec(
                project_id, FAULT_KEY, fault_keyword="sqli", strategy_keyword="blind",
                spec={"status": "specified", "spec_id": SPEC_FILE,
                      "fault_key": FAULT_KEY,
                      "fault": {"fault_id": "f1", "mechanism": "m",
                                "supports": [], "conflicts": [],
                                "test": "t", "status": "specified"},
                      "strategy": "blind", "spec_ref": "sr", "experiment_ref": ""},
                mode="create", side="produced",
            )
            return DispatchResult(hypothesis_verdict=None, feedback="concluded")
        return dispatch, None

    async def export_pods(spec, **kw):
        export["consumed_at"] = "now"
        return export

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[_candidate()], tools=_tools(hunt),
        hypothesise_fn=h, ratify_fn=r, note_fn=n,
        control=control, tick_interval=0.001,
        hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=spec_hunts, pod_builder=export_pods,
    ))
    notes = hunter.read_notes(PROJECT)
    assert len(notes) == 1
    record = notes[0]
    assert record["kind"] == "freeform"
    assert record["provenance"].get("verdict_stub") is True
    assert record["provenance"].get("source") == pod_session_id(RUN, FAULT_KEY, SPEC_FILE)
    assert "the-export" in record["body"]           # the export payload was recorded
    # the DURABLE parent-keyed record is keyed by the parent's canonical
    # CONFIG_KEY (the `::`-joined join key), never the physical `_`-joined
    # folder - the two sides of the cross-family join agree (identity refactor)
    assert record["fault_key"] == CONFIG_KEY
    # the record is keyed <config_key>:pod-export:<spec_id> with action update:
    # the note key carries NO `:`-session-id path, and the pod session id is
    # recoverable ONLY from provenance["source"] (#199)
    assert record["note_name"] == f"pod-export:{SPEC_FILE}"
    assert record["key"] == f"{CONFIG_KEY}:pod-export:{SPEC_FILE}"
    assert "hunting:" not in record["key"]
    assert pod_session_id(RUN, FAULT_KEY, SPEC_FILE) not in record["key"]
    # NOTHING more: the spec was consumed only by the mover (no re-dispatch),
    # and the hunter produced no further records/specs.
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert len(hunter.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))) == 1


# --- identity-based refactor: the cross-run pod-dispatch wedge regression ------

def test_cross_run_specified_spec_dispatches_a_pod_without_a_parent(stores,
                                                                    monkeypatch):
    """The pod-dispatch WEDGE regression (identity-based refactor, 2026-08-25):

    A produced `specified` spec whose parent config was consumed by an EARLIER
    run (so NO live parent hunter inbox exists in THIS run) must still dispatch
    a pod - the dispatch is gated on the spec's OWN persisted status, never on
    a chain-adjacent parent's liveness. AND the move lands (produced->consumed)
    AND the durable parent-keyed export record exists keyed by the parent's
    canonical CONFIG_KEY, so the run can reach quiesce (never wedged).

    The produced spec is written DIRECTLY into the hunter store (no hunter
    dispatch this run) - exactly the cross-run shape that previously returned
    `None` from `_spec_dispatch` (missing parent inbox) and hung the run."""
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)

    # A produced SPECIFIED spec with NO produced/consumed parent config on disk
    # at all - the parent was consumed by an earlier run, no hunter dispatches.
    _write_spec(hunter, fault_key=FAULT_KEY, status="specified")
    pod_calls: list[str] = []

    async def record_pods(spec, **kw):
        pod_calls.append(kw["spec_id"])
        return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
                "evidence": {"trail": []}, "clean": True, "iterations": 1}

    control = _FakeControl()
    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[], tools=_tools(hunt),
        control=control, tick_interval=0.001,
        hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=_noop_hunts, pod_builder=record_pods,
    ))
    # the pod ran, and the spec moved produced -> consumed (the marker)
    assert pod_calls == [SPEC_FILE]
    assert pod_session_id(RUN, FAULT_KEY, SPEC_FILE) in control.started
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert len(hunter.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))) == 1
    # the DURABLE parent-keyed export record exists keyed by the canonical
    # CONFIG_KEY (no live parent; the durable note is the only record)
    notes = hunter.read_notes(PROJECT)
    assert len(notes) == 1
    assert notes[0]["fault_key"] == CONFIG_KEY
    assert notes[0]["provenance"].get("verdict_stub") is True
    assert notes[0]["provenance"].get("source") == pod_session_id(
        RUN, FAULT_KEY, SPEC_FILE)
    assert "symptom-confirmed" in notes[0]["body"]
    # the record is keyed <config_key>:pod-export:<spec_id>: the note key
    # carries NO `:`-session-id path, the session id lives only in provenance
    assert notes[0]["note_name"] == f"pod-export:{SPEC_FILE}"
    assert notes[0]["key"] == f"{CONFIG_KEY}:pod-export:{SPEC_FILE}"
    assert "hunting:" not in notes[0]["key"]
    # the run reached quiesce - a produced `specified` spec can never wedge it
    assert fake.statuses == [("running", RUN), (RUN, "complete")]
    assert control.live(RUN) == set()


# --- AC4: terminal only on quiesce; stop cancels every session. ---------------

def test_run_does_not_complete_while_a_session_is_live(stores, monkeypatch):
    """The run lands `complete` ONLY on quiesce: with a pod session still
    live (blocked mid-run), no terminal status is stamped; once the pod
    settles, the run completes."""
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    h, r, n = _single_class_seams()
    control = _FakeControl()
    release = asyncio.Event()

    def spec_hunts(*, run_id, project_id, hunt_store, hunter_store, **kw):
        async def dispatch(config):
            hunter_store.write_spec(
                project_id, FAULT_KEY, fault_keyword="sqli", strategy_keyword="blind",
                spec={"status": "specified", "spec_id": SPEC_FILE,
                      "fault_key": FAULT_KEY,
                      "fault": {"fault_id": "f1", "mechanism": "m",
                                "supports": [], "conflicts": [],
                                "test": "t", "status": "specified"},
                      "strategy": "blind", "spec_ref": "sr", "experiment_ref": ""},
                mode="create", side="produced",
            )
            return DispatchResult(hypothesis_verdict=None, feedback="concluded")
        return dispatch, None

    async def blocked_pod(spec, **kw):
        await release.wait()
        return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
                "evidence": {"trail": []}, "clean": True, "iterations": 1}

    async def _body():
        task = asyncio.get_running_loop().create_task(hunting_runtime.start_hunting(
            PROJECT, candidates=[_candidate()], tools=_tools(hunt),
            hypothesise_fn=h, ratify_fn=r, note_fn=n,
            control=control, tick_interval=0.001,
            hunt_store=hunt, hunter_store=hunter, pod_store=pod,
            hunter_builder=spec_hunts, pod_builder=blocked_pod,
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
    not-yet-produced pipeline (a ratified config the surfer cannot dispatch
    because the gate refuses), nothing completes while it sits produced."""
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    h, r, n = _single_class_seams()
    hunt_refuse = hunter_session_id(RUN, f"{UNIT}_{FAULT}_{CLASS}")
    control = _FakeControl(refuse={hunt_refuse})

    async def _body():
        task = asyncio.get_running_loop().create_task(hunting_runtime.start_hunting(
            PROJECT, candidates=[_candidate()], tools=_tools(hunt),
            hypothesise_fn=h, ratify_fn=r, note_fn=n,
            control=control, tick_interval=0.001,
            hunt_store=hunt, hunter_store=hunter, pod_store=pod,
            hunter_builder=_noop_hunts, pod_builder=_noop_pods,
        ))
        # The refused dispatch is retried every tick; the config stays produced.
        await _wait_until(lambda: bool(hunt.read_produced_configs(PROJECT)))
        await asyncio.sleep(0.05)
        assert not any(status == "complete" for _, status in fake.statuses)
        assert len(hunt.read_produced_configs(PROJECT)) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_body())


def test_stop_cancels_every_session_and_leaves_the_registry_empty(stores, monkeypatch):
    """AC4 stop: stop cancels EVERY session of the run by session id (the
    orchestrator, the surfer, a blocked hunter, a blocked pod) through the real
    shared control plane, persists `stopped`, and leaves the registry empty."""
    from polymerhus.app.runtime import RuntimeManager

    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    h, r, n = _single_class_seams()

    def block_hunts(*, run_id, project_id, hunt_store, hunter_store, **kw):
        async def dispatch(config):
            hunter_store.write_spec(
                project_id, FAULT_KEY, fault_keyword="sqli", strategy_keyword="blind",
                spec={"status": "specified", "spec_id": SPEC_FILE,
                      "fault_key": FAULT_KEY,
                      "fault": {"fault_id": "f1", "mechanism": "m",
                                "supports": [], "conflicts": [],
                                "test": "t", "status": "specified"},
                      "strategy": "blind", "spec_ref": "sr", "experiment_ref": ""},
                mode="create", side="produced",
            )
            await asyncio.sleep(30)          # mid-graph forever (until stop)
            return DispatchResult(hypothesis_verdict=None, feedback="never")
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
                PROJECT, run_id=hunting_run_id, candidates=[_candidate()],
                tools=_tools(hunt), hypothesise_fn=h, ratify_fn=r, note_fn=n,
                hunt_store=hunt, hunter_store=hunter, pod_store=pod,
                hunter_builder=block_hunts, pod_builder=block_pods,
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
    """A dropped config (G6 stays on disk, never dispatchable) and a
    hypothesised spec draft must neither dispatch nor hold the quiesce open:
    the run still completes."""
    hunt, hunter, pod = stores
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    h, r, n = _single_class_seams()

    def draft_hunts(*, run_id, project_id, hunt_store, hunter_store, **kw):
        async def dispatch(config):
            hunter_store.write_spec(
                project_id, FAULT_KEY, fault_keyword="sqli", strategy_keyword="blind",
                spec={"spec_id": SPEC_FILE, "fault_key": FAULT_KEY,
                      "fault": {"fault_id": "f1", "mechanism": "m",
                                "supports": [], "conflicts": [],
                                "test": "t", "status": "hypothesised"},
                      "strategy": "blind", "status": "hypothesised"},
                mode="create", side="produced",
            )
            return DispatchResult(hypothesis_verdict=None, feedback="concluded")
        return dispatch, None

    control = _FakeControl()
    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, candidates=[_candidate()], tools=_tools(hunt),
        hypothesise_fn=h, ratify_fn=r, note_fn=n,
        control=control, tick_interval=0.001,
        hunt_store=hunt, hunter_store=hunter, pod_store=pod,
        hunter_builder=draft_hunts, pod_builder=_noop_pods,
    ))
    # the hypothesised draft stayed produced but never blocked completion
    assert fake.statuses == [("running", RUN), (RUN, "complete")]
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == [SPEC_FILE]
    assert not any(":pod:" in sid for sid in control.started)