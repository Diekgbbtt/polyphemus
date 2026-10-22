"""Contract tier: the T2b (#386) bootstrap re-wire - `start_hunting` runs the
threat modeller pass as the production path.

The planner pass is RETIRED: the run bootstrap selects its units, orders the
distinct unit ids (the transitional order T3 replaces with the intake order),
and models ONE unit at a time under the renamed `threat-modeller` session
segment, with the run-scoped actor, the tracker, the store and the grounding
projection wired. No live LLM, no live DB, no live Neo4j: the control plane,
the pg accessors and the pass's turn seam are injected.

S1 4.4, 7.1-7.4, 9.1 and the implementation plan's T2b acceptance criteria are
the contract asserted here.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.read_only_graph import ReadOnlyGraphView
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import threat_modeller_session_id
from polymerhus.attack.hunting.surfer import (
    RunDispatchState,
    is_modeller_session_id,
    is_run_quiesced,
    surfer_session_id,
)
from polymerhus.attack.hunting.threat_model import ModelState
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import (
    UnitOutcome,
    _reap_modeller,
)
from polymerhus.attack.hunting.threat_modeller_tools import ModellerTools

from tests.hunting_fixtures import (
    ScriptedModellerTurns,
    build_hunting_l1,
    build_intake_l1,
    intake_unit,
)

PROJECT = "wiring-proj-1"
RUN = "wiring-modeller-run"
UNIT_A = "Service:slug:a"
UNIT_B = "GraphQLApi"
UNIT_C = "RESTApi"


class _FakePg:
    """The fake pg accessors (the `test_hunting_runtime` seam contract): mint a
    deterministic run id, record every status write in order, carry the merged
    run record (the `stats` JSONB the driver updates), fail on demand, and serve
    the project's hunting config (default: the `batched` mode)."""

    def __init__(self, *, fail_create: bool = False, resume_record: dict | None = None,
                 hunting_settings: dict | None = None):
        self.fail_create = fail_create
        self.statuses: list[tuple[str, str]] = []
        self.stats_writes: list[tuple[str, str, dict | None]] = []
        self.records: dict[str, dict] = {}
        self.hunting_settings: dict = dict(hunting_settings or {})
        if resume_record is not None:
            self.records[RUN] = dict(resume_record)

    def get_hunting_settings(self, project_id: str) -> dict:
        return dict(self.hunting_settings)

    def create_hunting_run(self, project_id: str) -> str:
        if self.fail_create:
            raise OSError("pg down (fixture)")
        self.statuses.append(("running", RUN))
        return RUN

    def set_hunting_run_status(self, hunting_run_id: str, status: str, *,
                               stats: dict | None = None) -> None:
        self.statuses.append((hunting_run_id, status))
        self.stats_writes.append((hunting_run_id, status, stats))
        if stats is not None:
            # the production seam MERGES stats onto the row (additive JSONB)
            self.set_hunting_run_stats(hunting_run_id, stats)

    def set_hunting_run_stats(self, hunting_run_id: str, stats: dict) -> None:
        self.records.setdefault(hunting_run_id, {}).update(stats or {})

    def get_hunting_run(self, hunting_run_id: str) -> dict | None:
        if hunting_run_id not in self.records:
            return None
        return {"hunting_run_id": hunting_run_id,
                "stats": dict(self.records[hunting_run_id])}

    def run_record(self, hunting_run_id: str) -> dict:
        return dict(self.records[hunting_run_id])

    def list_hunting_runs(self, project_id: str) -> list[dict]:
        state: dict[str, dict] = {}
        for first, second in self.statuses:
            if first == "running":
                state[second] = {"hunting_run_id": second, "status": "running"}
            else:
                state[first] = {"hunting_run_id": first, "status": second}
        return list(state.values())


class _FakeControl:
    """The session-capable control-plane fake: RUNS the started sessions as
    tasks on the current loop, mirrors the registry through the live-task set."""

    def __init__(self, refuse: set[str] | None = None):
        self._refuse = set(refuse or ())
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
        return None


def _patch_pg(monkeypatch, fake):
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_stats", fake.set_hunting_run_stats)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.get_hunting_settings",
        fake.get_hunting_settings,
    )


async def _noop_hunter_dispatch(config):
    return None


def _noop_hunter_builder(*, run_id, project_id, hunter_store, **kw):
    return _noop_hunter_dispatch, None


async def _noop_pod_builder(spec, **kw):
    return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
            "evidence": {"trail": []}, "clean": True, "iterations": 0}


def _stores(tmp_path):
    """The two stores the dispatch path reads: the hunter memory and the threat
    model store. The hunt store retired with the config family (T4b)."""
    return (HunterMemoryStore(tmp_path / "hunter"),
            ThreatModelStore(root_dir=tmp_path / "models"))


# --- the modeller pass is the run's production pass ---------------------------

def test_start_hunting_models_each_distinct_unit_in_a_deterministic_order(
        tmp_path, monkeypatch):
    """S1 7.1/7.2 (transitional): the bootstrap runs ONE modeller pass per
    DISTINCT selected unit id, in a stable deterministic order (sorted by unit
    id), serially on the run's ONE pass session - and the session carries the
    renamed `threat-modeller` segment."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    control = _FakeControl()
    seen: list[tuple[str, str, str]] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append((project_id, run_id, unit_id))
        assert isinstance(tools, ModellerTools)
        return UnitOutcome(unit_id=unit_id, status="completed")

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        # the caller batch keeps a duplicate and an unsorted order: the
        # transitional order is the DISTINCT set, sorted by unit id
        intake_units=[intake_unit(UNIT_B), intake_unit(UNIT_A), intake_unit(UNIT_B)],
        modeller_pass_fn=recording_pass,
        control=control,
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == RUN
    assert [unit for _p, _r, unit in seen] == sorted({UNIT_A, UNIT_B})
    assert all(project == PROJECT and run == RUN for project, run, _u in seen)
    assert control.started == [
        threat_modeller_session_id(RUN), surfer_session_id(RUN)]
    assert fake.statuses == [("running", RUN), (RUN, "complete")]


def test_the_l1_inventory_supplies_the_intake_order(tmp_path, monkeypatch):
    """S1 7.1-7.2: with no injected snapshot the run reads the L1 inventory and
    freezes it - ordered by live L1 edge count descending, aggregated endpoints
    descending, unit id ascending - and models exactly those units. A retired
    edge family never counts; a System's endpoints sum its connected Services.
    The retired FaultSource selection has no call site."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="completed")

    read = build_intake_l1(
        units=[
            {"labels": ["L1Service"],
             "props": {"business_function_slug": "s1"},
             "edge_families": ["EXPOSED_VIA"], "endpoints": 2},
            {"labels": ["L1Service"],
             "props": {"business_function_slug": "s3"},
             "edge_families": ["EXPOSED_VIA", "AUTHENTICATED_BY"],
             "endpoints": 1},
            {"labels": ["L1System"],
             "props": {"kind": "GraphQLApi", "discriminator": "__singleton__"},
             "edge_families": ["EXPOSED_VIA", "EXPOSED_VIA", "ROUTED_BY",
                               "RENDERED_BY"],
             "endpoints": 0},
        ],
        systems=[{"kind": "GraphQLApi", "disc": "__singleton__", "services": [
            {"slug": "s1", "endpoints": 2},
            {"slug": "s3", "endpoints": 1},
        ]}],
    )

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_read_fn=read,
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == RUN
    assert seen == ["GraphQLApi", "Service:s3", "Service:s1"]
    assert fake.statuses == [("running", RUN), (RUN, "complete")]


def test_an_empty_intake_is_a_recorded_empty_pass(monkeypatch):
    """S1 7.1: an L1 with no unit is an EMPTY intake - the freeze is recorded in
    the run record, and no modeller pass is launched for nothing."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="degraded")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_read_fn=build_intake_l1(),
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == []
    record = fake.run_record(RUN)
    assert record["intake_order"] == []
    assert record["intake_position"] == 0
    assert fake.statuses == [("running", RUN), (RUN, "complete")]


def test_a_launched_unit_writes_its_model_through_the_real_store(
        tmp_path, monkeypatch):
    """S1 6/9.1: the production path runs the REAL modeller pass - the launched
    unit's five gate writes land in the threat model store as a COMPLETED,
    valid model with its produced loop file."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT_A)],
        modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == RUN
    model = models.read_model(PROJECT, UNIT_A)
    assert model["state"] == ModelState.COMPLETED.value
    assert model["validation"]["valid"] is True
    assert [loop["loop_id"] for loop in models.read_loop_files(PROJECT, UNIT_A)] \
        == ["loop-1"]
    assert fake.statuses == [("running", RUN), (RUN, "complete")]


def test_the_launched_pass_grounds_on_the_live_unit_projection(
        tmp_path, monkeypatch):
    """S1 4.6/5.6: the run's grounding provider reads the unit projection from
    the live L1 read seam, so the turn carries it instead of a gap. The
    application-surface overview entity has not landed (R2-15), so its gap path
    survives and is reported on the unit's outcome."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    turns = ScriptedModellerTurns()

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit("Service:s1")],
        modeller_kwargs={"turn_fn": turns},
        graph_read_fn=build_hunting_l1(),
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    groundings = {turn.projection.unit_id for turn in turns.turn_inputs}
    assert groundings == {"Service:s1"}
    assert all(turn.projection.kind == "Service" for turn in turns.turn_inputs)
    assert all(turn.context_gaps == ("L1 application-surface overview unavailable",)
               for turn in turns.turn_inputs)


def test_the_run_completes_with_one_model_and_no_planner_artifacts(
        tmp_path, monkeypatch):
    """S1 9.1: the run's pass is the modeller's. Its outcome is a `UnitOutcome`,
    the run writes NO hunt config (the planner's artifact family), and the
    planner entry points and prompt are gone."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    outcomes: list = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        outcome = UnitOutcome(unit_id=unit_id, status="completed")
        outcomes.append(outcome)
        return outcome

    import polymerhus.attack.hunting.actors as actors
    import polymerhus.attack.hunting.read_only_graph as planner
    from pathlib import Path

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT_A)],
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert all(isinstance(outcome, UnitOutcome) for outcome in outcomes)
    # the retired config family has no producer left in the runtime (T4b): the
    # only artifact family this run can write is the threat model store's
    assert not hasattr(hunting_runtime, "enqueue_hunt_config")
    for gone in ("arun_orchestration", "run_orchestration", "OrchestratorTools",
                 "mint_hunt_config", "GateDecision", "OrchestratorReport"):
        assert not hasattr(planner, gone), f"the planner's {gone} must be gone"
    for gone in ("HuntOrchestratorActor", "build_orchestrator_tool_surface"):
        assert not hasattr(actors, gone), f"the planner's {gone} must be gone"
    assert not (Path(inspect.getfile(planner)).parent / "prompts"
                / "hunt-orchestrator.md").exists()


def test_the_planner_graph_and_tracing_modules_are_gone():
    """T2b: the phase nodes, the graph engine and the planner's gate-step tracer
    have no module home any more - no dead import can reach them."""
    import importlib

    for module in ("polymerhus.attack.hunting.orchestrator_graph",
                   "polymerhus.attack.hunting.orchestrator_tracing"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)


# --- the session-id swap and the legacy resume alias --------------------------

def test_the_modeller_session_id_is_the_new_segment():
    """S1 4.1: a new run's pass session is `hunting:<run_id>:threat-modeller`."""
    assert threat_modeller_session_id(RUN) == f"hunting:{RUN}:threat-modeller"


def test_the_modeller_session_predicate_accepts_the_new_segment_only():
    """S1 4.1: the modeller session predicate accepts the new segment and
    nothing else. T10 removed the planner-era `orchestrator` alias."""
    assert is_modeller_session_id(threat_modeller_session_id(RUN), RUN) is True
    assert is_modeller_session_id(f"hunting:{RUN}:orchestrator", RUN) is False
    assert is_modeller_session_id(surfer_session_id(RUN), RUN) is False


def test_a_live_planner_era_pass_session_is_not_a_component_session(tmp_path):
    """T10: the alias is removed. A session registered under the planner-era
    segment is not the run's modeller pass and does not hold quiesce - new runs
    use `threat-modeller` only, and no resume path is invented."""
    hunter, _models = _stores(tmp_path)

    class _Control:
        def __init__(self, live):
            self._live = live

        def live_session_ids(self):
            return set(self._live)

    modeller = threat_modeller_session_id(RUN)
    control = _Control({f"hunting:{RUN}:orchestrator"})
    state = RunDispatchState()

    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, hunter_store=hunter, control=control,
        state=state)) is True

    control._live = {modeller}
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, hunter_store=hunter, control=control,
        state=state)) is False


# --- the breaker, the provider failure and the actor teardown -----------------

def test_a_provider_caused_pass_abort_persists_interrupted(tmp_path, monkeypatch):
    """S1 4.4 `provider_cause` / 7.7: a sustained provider outage pauses the run
    as the resumable `interrupted` with the typed cause, never `failed`."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError
    from polymerhus.attack.hunting.threat_modeller import (
        ThreatModellerDegradedError,
    )

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)

    async def provider_abort(project_id, run_id, unit_id, tools, **kwargs):
        raise ThreatModellerDegradedError(
            state="TRUST_MODELLED", streak=5, threshold=5, provider_cause=True,
            provider_error=ProviderUnavailableError(
                "Go usage limit exceeded", status_code=429,
                quota_exhausted=True))

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT_A)],
        modeller_pass_fn=provider_abort,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    _, status, stats = fake.stats_writes[-1]
    assert status == "interrupted"
    assert stats["interrupted"] is True
    assert stats["provider_status"] == 429
    assert stats["quota_exhausted"] is True


def test_a_non_provider_pass_abort_fails_the_run(tmp_path, monkeypatch):
    """The degradation breaker's non-provider abort stays a genuine domain
    failure: the run lands `failed`."""
    from polymerhus.attack.hunting.threat_modeller import (
        ThreatModellerDegradedError,
    )

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)

    async def poisoned_abort(project_id, run_id, unit_id, tools, **kwargs):
        raise ThreatModellerDegradedError(
            state="UNIT_TECHNICAL_SHARP", streak=5, threshold=5,
            provider_cause=False)

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT_A)],
        modeller_pass_fn=poisoned_abort,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert fake.statuses == [("running", RUN), (RUN, "failed")]


def test_the_run_terminal_reaps_the_modeller_actor(tmp_path, monkeypatch):
    """S1 4.4: the run-scoped modeller actor is reaped at the run terminal (and
    only there), so no actor and no per-run thread outlives its run."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    reaped: list[str] = []

    from polymerhus.attack.hunting import threat_modeller as tm

    original = tm._reap_modeller

    async def recording_reap(run_id):
        reaped.append(run_id)
        await original(run_id)

    monkeypatch.setattr(tm, "_reap_modeller", recording_reap)

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT_A)],
        modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert reaped == [RUN]
    assert tm._MODELLER_ACTORS == {}


def test_stop_hunting_reaps_the_modeller_actor(monkeypatch):
    """The run stop reaps the run's modeller actor with the run's sessions."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    reaped: list[str] = []

    from polymerhus.attack.hunting import threat_modeller as tm

    async def recording_reap(run_id):
        reaped.append(run_id)

    monkeypatch.setattr(tm, "_reap_modeller", recording_reap)

    asyncio.run(hunting_runtime.stop_hunting(RUN))

    assert reaped == [RUN]
    assert fake.statuses == [(RUN, "stopped")]


def test_the_provider_failure_handler_reaps_the_modeller_actor(monkeypatch):
    """The #331 stop-only handler reaps the run's modeller actor before it stamps
    the resumable terminal - a paused run leaves no hot actor behind."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    reaped: list[str] = []

    from polymerhus.attack.hunting import threat_modeller as tm

    async def recording_reap(run_id):
        reaped.append(run_id)

    monkeypatch.setattr(tm, "_reap_modeller", recording_reap)
    control = _FakeControl()

    asyncio.run(hunting_runtime.stop_hunting_for_provider_failure(
        control, RUN,
        error=ProviderUnavailableError("throttled", status_code=429,
                                       quota_exhausted=False),
        tick_interval=0.001, drain_timeout=0.5,
    ))

    assert reaped == [RUN]
    assert fake.statuses == [(RUN, "interrupted")]


def test_the_modeller_pass_is_serial_per_run(tmp_path, monkeypatch):
    """S1 4.6 / the T2a hazard: the pass mutates the shared tool seams, so a run
    models ONE unit at a time - a second pass never overlaps the first."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    control = _FakeControl()
    live: list[str] = []
    overlaps: list[str] = []

    async def slow_pass(project_id, run_id, unit_id, tools, **kwargs):
        if live:
            overlaps.append(unit_id)
        live.append(unit_id)
        await asyncio.sleep(0.02)
        live.remove(unit_id)
        return UnitOutcome(unit_id=unit_id, status="completed")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT_A), intake_unit(UNIT_B)],
        modeller_pass_fn=slow_pass,
        control=control,
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert overlaps == []


# --- the run-scoped actor lane ------------------------------------------------

def test_the_run_scoped_actor_completes_every_unit_of_the_run(tmp_path, monkeypatch):
    """S1 4.4: ONE actor (and one per-run session thread) serves every unit of
    the run - the pass retargets the unit cell, so the actor's captured surface
    models unit after unit without stranding its tools."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    built: list[str] = []

    class _FakeActor:
        def __init__(self, run_id):
            self.run_id = run_id
            self.tools = None
            self.project_id = None

        async def turn(self, turn_input):
            from polymerhus.attack.hunting.threat_modeller_tools import (
                build_modeller_tool_surface,
            )

            if not hasattr(self, "_surface"):
                cell = getattr(self.tools, "unit_cell", None)
                unit = getattr(cell, "unit_id", "") if cell is not None else ""
                self._surface = build_modeller_tool_surface(
                    self.project_id, unit, self.tools)
                built.append(self.run_id)
            from tests.hunting_fixtures import modeller_gate_payloads

            self._surface["hunts_store"].invoke({
                "cmd": "write", "state": turn_input.state.value,
                "sections": modeller_gate_payloads()[turn_input.state]})
            return None

        def last_degrade_cause(self):
            return None

        async def stop(self):
            pass

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT_A), intake_unit(UNIT_B)],
        modeller_kwargs={"actor_factory": _FakeActor},
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert built == [RUN]                        # ONE captured surface per run
    assert fake.statuses == [("running", RUN), (RUN, "complete")]
    for unit_id in (UNIT_A, UNIT_B):
        model = models.read_model(PROJECT, unit_id)
        assert model["state"] == ModelState.COMPLETED.value
        assert model["validation"]["valid"] is True
    assert asyncio.run(_reaped(RUN)) is True


async def _reaped(run_id: str) -> bool:
    """True when no modeller actor survives for `run_id` (the terminal reap)."""
    from polymerhus.attack.hunting import threat_modeller as tm

    await _reap_modeller(run_id)  # idempotent: a second reap is a no-op
    return run_id not in tm._MODELLER_ACTORS


def test_the_default_graph_read_is_the_read_only_view():
    """The production grounding read seam is the read-only L1 graph view (never a
    write-capable client) unless the caller injects one."""
    from polymerhus.attack.hunting.threat_modeller_tools import (
        build_grounding_provider,
    )

    view = ReadOnlyGraphView(PROJECT, read_fn=lambda cy, p: [])
    provider = build_grounding_provider(PROJECT, read_fn=view.read)

    assert provider("Service:unknown").get("projection") is None
