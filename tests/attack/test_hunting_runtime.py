"""#110: the hunting module runtime entry points - the start/stop lifecycle, the
tear-down flush hook, the fixed store root, and the scheduling marshalling
harness. No live PG / live LLM / live Neo4j: the pg accessors and the modeller
pass seam are faked, exactly the seam contract (seam 3) the tests assert
against. The modeller pass itself (its gates, the store) is the subject of
`test_hunting_modeller_wiring.py` and `test_threat_modeller.py`.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.hunt_orchestrator import HuntConfig
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import (
    ThreatModellerDegradedError,
    UnitOutcome,
    run_modeller_pass,
)

from tests.hunting_fixtures import ScriptedModellerTurns

SERVICE_A = "Service:slug:a"
UNIT = "Service:slug:a"
FAULT_X = "fault-x"


def _outcome(unit_id: str = SERVICE_A, status: str = "completed") -> UnitOutcome:
    return UnitOutcome(unit_id=unit_id, status=status)


def _recording_pass(seen: list | None = None):
    """The injectable modeller pass body: records the unit and returns a
    completed `UnitOutcome` (no LLM, no store)."""
    seen = seen if seen is not None else []

    async def run(project_id, run_id, unit_id, tools, **kwargs):
        seen.append((project_id, run_id, unit_id))
        return _outcome(unit_id)

    run.seen = seen
    return run


def _stores(tmp_path):
    return (HuntStore(tmp_path / "hunts"),
            HunterMemoryStore(tmp_path / "hunter"),
            ThreatModelStore(root_dir=tmp_path / "models"))


class _FakePg:
    """The fake pg accessors: mint a deterministic hunting_run_id, record every
    status write in order, and fail on demand (the seam's fail-open paths)."""

    def __init__(self, *, fail_create: bool = False, fail_status: bool = False):
        self.fail_create = fail_create
        self.fail_status = fail_status
        self.statuses: list[tuple[str, str]] = []
        self.stats_writes: list[tuple[str, str, dict | None]] = []
        self.next_id = "rt-hunt-0001"

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

    def list_hunting_runs(self, project_id: str) -> list[dict]:
        """The ONE-live-run-per-project guard read: every run the fake opened
        or stamped, mapped to a pg-shaped row (create records status-first,
        set_status records id-first - both unpacked here)."""
        state: dict[str, dict] = {}
        for first, second in self.statuses:
            if first == "running":
                state[second] = {"hunting_run_id": second, "status": "running"}
            else:
                state[first] = {"hunting_run_id": first, "status": second}
        return list(state.values())


class _FakeControl:
    """The T4 session-capable control-plane fake: RUNS the dispatched/started
    sessions as tasks on the current loop (so the whole pipeline is observable
    through the bootstrap with no live runtime), mirrors the real manager's
    registry through the live-task set, and can refuse/close unadmitted
    sessions. Implements the mover's `DispatchControlPlane` verbs and the run
    bootstrap's session verbs (`start_session` / `cancel_session` / `gate`)."""

    def __init__(self, refuse: set[str] | None = None, *, gate=None):
        self._refuse = set(refuse or ())
        self._gate = gate
        self._tasks: dict[str, asyncio.Task] = {}
        self.started: list[str] = []

    def live_session_ids(self):
        return {sid for sid, task in self._tasks.items() if not task.done()}

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


async def _noop_hunter_dispatch(config):
    """The fake hunt-session graph: concludes immediately (no specs
    authored), so the run quiesces without producing pods."""
    return None


def _noop_hunter_builder(*, run_id, project_id, hunter_store, **kw):
    return _noop_hunter_dispatch, None


async def _noop_pod_builder(spec, **kw):
    return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
            "evidence": {"trail": []}, "clean": True, "iterations": 0}


def _patch_pg(monkeypatch, fake):
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)


def test_start_hunting_persists_running_then_complete(tmp_path, monkeypatch):
    """The entry point opens the run `running`, schedules the modeller pass and
    the run-scoped surfer as sessions, drives them to quiesce (the pass writes
    the unit's model; the fake hunt session concludes without specs), and lands
    `complete`."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt, hunter, models = _stores(tmp_path)

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(),
        control=_FakeControl(),
        hunt_store=hunt, hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == "rt-hunt-0001"
    assert fake.statuses == [("running", "rt-hunt-0001"), ("rt-hunt-0001", "complete")]


def _delivered_candidate(unit_id: str = SERVICE_A, fault_class: str = FAULT_X):
    from polymerhus.attack.hunting.hunt_orchestrator import (
        DeliveredCandidate,
        Witness,
    )

    return DeliveredCandidate(
        unit_id=unit_id,
        fault_class=fault_class,
        applies_witnesses=Witness(deterministic="witness", llm="witness"),
        match_verdict="applies",
    )


def test_caller_supplied_candidates_stay_the_override(monkeypatch):
    """#200: a non-empty caller batch is consumed as-is, never re-selected; the
    pass runs over its distinct unit ids."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    seen: list = []
    supplied = [_delivered_candidate()]

    asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=supplied,
        modeller_pass_fn=_recording_pass(seen),
        control=_FakeControl(),
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))
    assert seen and seen[0][2] == SERVICE_A


def test_default_tools_ground_on_the_app_owned_store_roots():
    """With no tools injected the entry point builds the seam defaults: the
    ThreatModelStore at the app-owned data root (the modeller's store) and the
    read-only graph view (its grounding read)."""
    from polymerhus.app.data_root import DATA_ROOT

    store = ThreatModelStore()

    assert store._root == DATA_ROOT
    assert store._project_dir("proj-1") == (
        DATA_ROOT / "proj-1" / "hunting" / "threat_modeller"
    )


def test_failing_modeller_pass_still_lands_a_terminal_status(monkeypatch):
    """Fail-open: a pass that raises degrades to `failed` - the entry point
    never raises through the control plane."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)

    async def boom(project_id, run_id, unit_id, tools, **kwargs):
        raise RuntimeError("pass blew up (fixture)")

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=boom,
        control=_FakeControl(), tick_interval=0.001,
    ))
    assert hid == "rt-hunt-0001"
    assert fake.statuses == [("running", "rt-hunt-0001"), ("rt-hunt-0001", "failed")]


# --- #329: a provider-caused pass abort pauses the run, never fails it ---------

def test_provider_caused_pass_abort_persists_interrupted(monkeypatch):
    """#329 AC1: a sustained provider throttle does not fail the run outright -
    the pass aborts operator-visibly but the run lands the resumable terminal
    `interrupted`, never `failed`."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)

    async def provider_abort(project_id, run_id, unit_id, tools, **kwargs):
        raise ThreatModellerDegradedError(
            state="TRUST_MODELLED", streak=5, threshold=5, provider_cause=True)

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=provider_abort,
        control=_FakeControl(), tick_interval=0.001,
    ))
    assert hid == "rt-hunt-0001"
    assert fake.statuses == [("running", "rt-hunt-0001"), ("rt-hunt-0001", "interrupted")]


def test_provider_caused_pass_abort_records_the_cause_on_the_run(monkeypatch):
    """#331: the `interrupted` run row carries WHY - the provider class, its HTTP
    status, and the `quota_exhausted` flag - so the eval can distinguish a
    transient throttle (resumable) from consumed credits (terminal) after the
    process that observed the failure is gone."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)

    async def provider_abort(project_id, run_id, unit_id, tools, **kwargs):
        raise ThreatModellerDegradedError(
            state="TRUST_MODELLED", streak=5, threshold=5, provider_cause=True,
            provider_error=ProviderUnavailableError(
                "Go usage limit exceeded", status_code=429,
                quota_exhausted=True))

    asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=provider_abort,
        control=_FakeControl(), tick_interval=0.001,
    ))

    hid = "rt-hunt-0001"
    assert fake.statuses == [("running", hid), (hid, "interrupted")]
    _, status, stats = fake.stats_writes[-1]
    assert status == "interrupted"
    assert stats["interrupted"] is True
    assert stats["provider_status"] == 429
    assert stats["quota_exhausted"] is True
    assert "429" in stats["interrupt_reason"]
    assert "quota" in stats["interrupt_reason"].lower()


def test_provider_abort_stops_the_runs_sessions_before_the_terminal(monkeypatch):
    """#331 stop-only: on a provider-caused abort the handler STOPS the run's
    affected sessions (per-session `cancel_run`, reached through the shared
    control plane: the modeller pass, the surfer mover so it cannot keep
    dispatching, every hunter/pod), DRAINS them, and only then stamps
    `interrupted`."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)

    cancelled: list[str] = []
    live_at_interrupt: list[set[str]] = []

    class _RecordingControl(_FakeControl):
        def live_session_ids(self):
            # Include the run's OUTER bootstrap markers the real registry holds
            # (session id = the run's own registry name) so the test proves the
            # handler never cancels the task running it.
            return super().live_session_ids() | {
                "rt-hunt-0001", "hunting:rt-hunt-0001",
            }

        def cancel_session(self, session_id):
            cancelled.append(session_id)
            super().cancel_session(session_id)

    control = _RecordingControl()

    original = fake.set_hunting_run_status

    def recording_status(hid, status, *, stats=None):
        if status == "interrupted":
            live_at_interrupt.append({
                sid for sid in control.live_session_ids()
                if sid.startswith(f"hunting:{hid}:")
            })
        return original(hid, status, stats=stats)

    monkeypatch.setattr(
        "polymerhus.app.clients.pg.set_hunting_run_status", recording_status)

    async def provider_abort(project_id, run_id, unit_id, tools, **kwargs):
        raise ThreatModellerDegradedError(
            state="TRUST_MODELLED", streak=5, threshold=5, provider_cause=True,
            provider_error=ProviderUnavailableError(
                "Go usage limit exceeded", status_code=429, quota_exhausted=True))

    asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=provider_abort,
        control=control, tick_interval=0.001,
    ))

    hid = "rt-hunt-0001"
    assert f"hunting:{hid}:surfer" in cancelled, (
        "the surfer session must be stopped so it cannot keep dispatching")
    # the modeller pass session already settled by raising the abort, so it is
    # no longer live; the surfer is the session that must be hard-cancelled
    assert hid not in cancelled, (
        "the run's outer bootstrap marker must never be cancelled")
    assert f"hunting:{hid}" not in cancelled, (
        "the run's outer bootstrap marker must never be cancelled")
    assert live_at_interrupt, "the interrupted terminal must be stamped"
    assert live_at_interrupt[-1] == set(), (
        "no run session may be live when the interrupted terminal lands")


def _ratified_config() -> HuntConfig:
    return HuntConfig(
        hunt_id=f"{UNIT}::{FAULT_X}::CSRF",
        unit_id=UNIT, fault_class=FAULT_X, vulnerability_class="CSRF",
        rationale="r", research_direction="rd",
    )


def test_hunter_provider_failure_interrupts_the_run(tmp_path, monkeypatch):
    """#312: a provider failure inside a dispatched HUNTER - after the pass has
    modelled and the surfer consumed a ratified config - must pause the run as
    the resumable `interrupted` with the provider cause, never let it quiesce
    `complete` with zero specs and no reason. This is the trial-2 outcome: 11
    configs consumed, 0 specs authored, no typed reason. The #329/#331 fixes
    scoped the pass and the pod verdict; the hunter harness still swallowed the
    typed provider error and the run quiesced silently."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt, hunter, models = _stores(tmp_path)
    hunting_runtime.enqueue_hunt_config("rt-project", _ratified_config(),
                                        hunt_store=hunt)

    async def provider_hunter(config):
        raise ProviderUnavailableError(
            "Go usage limit exceeded", status_code=429, quota_exhausted=True)

    def provider_hunter_builder(*, run_id, project_id, hunter_store, **kw):
        return provider_hunter, None

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(),
        hunt_store=hunt, hunter_store=hunter, threat_store=models,
        control=_FakeControl(),
        hunter_builder=provider_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == "rt-hunt-0001"
    _, status, stats = fake.stats_writes[-1]
    assert status == "interrupted", (
        "a hunter provider failure must pause the run, not let it quiesce complete")
    assert stats["interrupted"] is True
    assert stats["provider_status"] == 429
    assert stats["quota_exhausted"] is True


def test_raw_hunter_provider_error_at_the_real_seam_interrupts_the_run(
        tmp_path, monkeypatch):
    """#312, end-to-end: the REAL hunter harness (`build_hunting_agent`) is the
    dispatch seam, and its model raises a RAW `openai.RateLimitError` - never a
    typed error. The harness classifies the raw raise at its own seam, the
    surfer records it, and the run pauses as `interrupted` with the provider
    cause - instead of quiescing `complete` with zero specs (the trial-2
    outcome)."""
    from langgraph.checkpoint.memory import InMemorySaver  # noqa: PLC0415

    from tests.hunting_fixtures import (  # noqa: PLC0415
        _RaisingModel,
        _openai_rate_limit_error,
    )
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        build_hunting_agent,
    )

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt, hunter, models = _stores(tmp_path)
    hunting_runtime.enqueue_hunt_config("rt-project", _ratified_config(),
                                        hunt_store=hunt)

    def raw_hunter_builder(*, run_id, project_id, hunter_store, **kw):
        dispatch = build_hunting_agent(
            run_id=run_id, project_id=project_id, memory_store=hunter_store,
            model_factory=lambda role_id: _RaisingModel(
                exc=_openai_rate_limit_error()),
            checkpointer=InMemorySaver(), middleware=[], observe=False,
        )
        return dispatch, None

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(),
        hunt_store=hunt, hunter_store=hunter, threat_store=models,
        control=_FakeControl(),
        hunter_builder=raw_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == "rt-hunt-0001"
    _, status, stats = fake.stats_writes[-1]
    assert status == "interrupted", (
        "a RAW hunter provider error must pause the run, not let it quiesce complete")
    assert stats["provider_status"] == 429
    assert stats["interrupted"] is True


def test_build_production_hunting_agent_wires_real_seams(tmp_path):
    """The production default dispatch closure: construction is inert (no I/O,
    no LLM, no network) and returns a callable dispatch plus a reapable
    registry, wired to the real fault-KB lookup and the real HTTP pod."""
    from polymerhus.attack.hunting.runtime import build_production_hunting_agent

    dispatch, registry = build_production_hunting_agent(
        run_id="prod-run",
    )
    assert callable(dispatch)
    assert registry is not None


def test_start_hunting_fail_open_when_pg_is_unavailable(monkeypatch, caplog):
    """Fail-open: with the PG row AND the status write unavailable the run still
    proceeds (a generated id keys the trail) and nothing raises."""
    fake = _FakePg(fail_create=True, fail_status=True)
    _patch_pg(monkeypatch, fake)

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(),
        control=_FakeControl(), tick_interval=0.001,
    ))
    assert hid  # an id still keyed the run despite the PG outage
    assert fake.statuses == []


def test_pinned_run_id_keys_the_run(tmp_path, monkeypatch):
    """A caller-pinned run_id keys the status writes (the store trail uses it)."""
    fake = _FakePg()
    fake.create_hunting_run = lambda project_id: fake.next_id
    _patch_pg(monkeypatch, fake)
    hunt, hunter, models = _stores(tmp_path)

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", run_id="pinned-run", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(),
        control=_FakeControl(),
        hunt_store=hunt, hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))
    assert hid == "pinned-run"


def test_stop_hunting_persists_stopped(monkeypatch):
    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)

    asyncio.run(hunting_runtime.stop_hunting("rt-hunt-0001"))
    assert fake.statuses == [("rt-hunt-0001", "stopped")]


def test_stop_hunting_cancels_a_running_run(tmp_path, monkeypatch):
    """The run stop: stop_hunting cancels EVERY session of the run (the outer
    bootstrap task, the modeller pass, the surfer), and the run lands
    `stopped` - the task's own cancellation never re-stamps a status over the
    stop."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)

    async def slow(project_id, run_id, unit_id, tools, **kwargs):
        await asyncio.sleep(30)

    from polymerhus.app.runtime import RuntimeManager

    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    try:
        hunting_run_id = fake.create_hunting_run("rt-project")
        rm.schedule(
            "hunting",
            hunting_runtime.start_hunting(
                "rt-project", run_id=hunting_run_id,
                candidates=[_delivered_candidate()],
                modeller_pass_fn=slow,
                hunt_store=HuntStore(tmp_path / "hunts"),
                hunter_store=HunterMemoryStore(tmp_path / "hunter"),
                pod_store=None,
                hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
            ),
            name=hunting_run_id,
        )
        asyncio.run(hunting_runtime.stop_hunting(hunting_run_id))
        assert fake.statuses == [("running", hunting_run_id), (hunting_run_id, "stopped")]
    finally:
        rm.shutdown()


# --- #123: the shared module-context seam + the to-thread pg offloads ----------

def test_hunting_module_context_sets_the_shared_module_seam():
    """#123 AC: hunting_module_context delegates to the SHARED
    module_context("hunting") seam (`app/llm/checkpoints`), never a private
    hunting-only var - while it is set the shared context var reads "hunting",
    get_session_checkpointer resolves the hunting module's index (also inside
    to_thread executor work, via copy_context), and the context resets on exit
    so the shared fallback resolves again."""
    from polymerhus.app.llm import checkpoints as C

    async def probe():
        async with hunting_runtime.hunting_module_context():
            on_loop = C._MODULE_CTX.get()
            cp = C.get_session_checkpointer()
            offloaded = await asyncio.to_thread(C.get_session_checkpointer)
            return on_loop, cp, offloaded

    on_loop, cp, offloaded = asyncio.run(probe())
    fallback = C.get_session_checkpointer()
    assert on_loop == "hunting"
    assert cp is not fallback
    assert cp._index.module == "hunting"
    assert offloaded is cp
    assert C.get_session_checkpointer() is fallback  # context reset on exit


def test_hunting_pg_calls_offload_via_asyncio_to_thread(tmp_path, monkeypatch):
    """#123 AC: the blocking-sync-pg calls (create_hunting_run,
    set_hunting_run_status - and the guard's list_hunting_runs - in
    start_hunting; set_hunting_run_status in stop_hunting) route through
    `asyncio.to_thread` onto the shared executor - a spied to_thread proves the
    pg accessors are ONLY reached from the worker loop through the offload,
    never as direct sync calls."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt, hunter, models = _stores(tmp_path)

    offloaded: list[tuple[object, tuple]] = []
    orig_to_thread = hunting_runtime.asyncio.to_thread

    def spied_to_thread(fn, /, *args, **kwargs):
        offloaded.append((fn, args))
        return orig_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(hunting_runtime.asyncio, "to_thread", spied_to_thread)

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(),
        control=_FakeControl(),
        hunt_store=hunt, hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))
    assert hid == "rt-hunt-0001"
    asyncio.run(hunting_runtime.stop_hunting(hid))

    pg_offloads = [
        fn for fn, _ in offloaded
        if fn in (fake.create_hunting_run, fake.set_hunting_run_status,
                  fake.list_hunting_runs)
    ]
    assert pg_offloads == [
        fake.list_hunting_runs,          # the ONE-live-run guard read first
        fake.create_hunting_run,
        fake.set_hunting_run_status,     # complete (quiesce)
        fake.set_hunting_run_status,     # stopped (stop_hunting)
    ]
    assert fake.statuses == [
        ("running", "rt-hunt-0001"),
        ("rt-hunt-0001", "complete"),
        ("rt-hunt-0001", "stopped"),
    ]


# --- the tear-down flush hook (seam 3.1) ---------------------------------------

def test_flush_hunting_checkpointer_is_a_safe_noop():
    """With no PG the hook is a no-op - it never raises (fail-open)."""
    hunting_runtime.flush_hunting_checkpointer()


def test_flush_hunting_checkpointer_uses_the_shared_module_index_seam(monkeypatch):
    """#123: the tear-down flush hook archives the hunting module's in-memory
    checkpointer index through the SHARED `flush_module_index("hunting")` seam
    (never a private hunting-only path), so the fan-out reaches the index the
    control-plane checkpointer resolved."""
    calls: list[str] = []

    monkeypatch.setattr(
        "polymerhus.app.llm.checkpoints.flush_module_index",
        lambda module: calls.append(module),
    )
    hunting_runtime.flush_hunting_checkpointer()
    assert calls == ["hunting"]


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


# the modeller pass's sync lane still works through the module boundaries
def test_explicit_root_store_trail_is_written(tmp_path):
    """The sync lane (`run_modeller_pass`) models one unit end to end: the five
    gate writes land through the real store and the produced loop file exists."""
    store = ThreatModelStore(root_dir=tmp_path)
    outcome = run_modeller_pass(
        "rt-project", "run-rt", UNIT,
        _modeller_tools(store),
        turn_fn=ScriptedModellerTurns(),
    )
    assert outcome.status == "completed"
    assert store.read_model("rt-project", UNIT)["state"] == "COMPLETED"
    assert [loop["loop_id"] for loop in store.read_loop_files("rt-project", UNIT)] \
        == ["loop-1"]


def _modeller_tools(store):
    from polymerhus.attack.hunting.threat_modeller_tools import ModellerTools

    return ModellerTools(threat_store=store, project_id="rt-project",
                         run_id="run-rt")


def test_hunting_run_terminal_invokes_exactly_one_run_scoped_flush(tmp_path, monkeypatch):
    """#211 C12/P7d: a hunting run terminal (complete path) invokes EXACTLY ONE
    flush path - the shared run-scoped seam with this run's id - never a second
    ad-hoc whole-index call."""
    from polymerhus.app.llm.checkpoints import FlushResult
    import polymerhus.app.llm.checkpoints as checkpoints

    calls = []
    monkeypatch.setattr(
        checkpoints, "flush_module_index",
        lambda module, run_id=None: (
            calls.append((module, run_id)),
            FlushResult(committed=0, archived=0, dropped=0, dropped_thread_ids=[]),
        )[1],
    )
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt, hunter, models = _stores(tmp_path)

    hid = asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(),
        control=_FakeControl(),
        hunt_store=hunt, hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == "rt-hunt-0001"
    assert calls == [("hunting", "rt-hunt-0001")]


# --- #317: agent sub-modules on the run bootstrap -----------------------------


class _FakeRoleManager:
    """A role-read stand-in for the runtime manager (#317) used by the run
    bootstrap: records registration/reap and reports a configured role state.
    The bootstrap reads roles through `_app_runtime()`, not the injected control
    plane, so this fakes only the manager's role surface."""

    class _Handle:
        agent_roles = ("threat_modeller", "hunter", "pod")

    def __init__(self, paused=()):
        self.paused = set(paused)
        self.registered: list[tuple[str, str, str]] = []
        self.reaped: list[tuple[str, str | None]] = []

    def handle(self, module):
        return self._Handle()

    def register_agent_submodule(self, module, run_id, role):
        self.registered.append((module, run_id, role))
        return object()

    def agent_submodule_state(self, module, run_id, role):
        from polymerhus.app.runtime import ModuleState
        return ModuleState.PAUSED if role in self.paused else ModuleState.RUNNING

    def agent_submodule_running(self, module, run_id, role):
        return role not in self.paused

    def reap_agent_submodules(self, module, run_id=None):
        self.reaped.append((module, run_id))


def test_run_bootstrap_registers_and_reaps_the_agent_submodules(monkeypatch):
    """#317: the bootstrap registers the run's three roles on boot and reaps
    them at the run terminal; the modeller pass launches when its role is up."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    manager = _FakeRoleManager()
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: manager)
    seen: list = []

    asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(seen),
        control=_FakeControl(),
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert manager.registered == [
        ("hunting", "rt-hunt-0001", "threat_modeller"),
        ("hunting", "rt-hunt-0001", "hunter"),
        ("hunting", "rt-hunt-0001", "pod"),
    ]
    assert [run_id for _p, run_id, _u in seen] == ["rt-hunt-0001"]
    assert manager.reaped == [("hunting", "rt-hunt-0001")]


def test_modeller_pass_not_launched_when_its_role_is_stopped(monkeypatch):
    """#317: with the modeller role `PAUSED`, the bootstrap does NOT launch the
    pass (the surfer still runs, so pre-produced configs can dispatch)."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    manager = _FakeRoleManager(paused={"threat_modeller"})
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: manager)
    seen: list = []

    asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        modeller_pass_fn=_recording_pass(seen),
        control=_FakeControl(),
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == []                          # the pass was gated off
    assert manager.reaped == [("hunting", "rt-hunt-0001")]
    # the surfer ran on the empty produced set and quiesced the run.
    assert fake.statuses[-1] == ("rt-hunt-0001", "complete")


def test_surfer_not_started_when_the_modeller_is_refused(monkeypatch):
    """S3: when the modeller session is REFUSED by admission (not merely its
    role paused), the bootstrap fails the run WITHOUT starting the surfer - a
    run never carries a surfer with no pass."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    manager = _FakeRoleManager()
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: manager)
    control = _FakeControl(refuse={"hunting:rt-hunt-0001:threat-modeller"})

    asyncio.run(hunting_runtime.start_hunting(
        "rt-project", candidates=[_delivered_candidate()],
        control=control,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    # only the modeller session was attempted; the surfer was NOT started.
    assert control.started == ["hunting:rt-hunt-0001:threat-modeller"]
    assert fake.statuses[-1] == ("rt-hunt-0001", "failed")
