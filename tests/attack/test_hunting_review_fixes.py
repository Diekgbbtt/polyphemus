"""T2b review fixes: the run-level dispatch-gap warning, the bounded actor
reap, and the tool-seam gap sink (T2b #386 review round).

Three reviewer findings, each asserted at its own seam:

1. A completed modeller pass that produced models while the run has nothing
   dispatchable must say WHY in one run-level line (the per-loop dispatch is
   T4 #377's and does not exist yet) - never land `complete` silently after
   dispatching zero hunts.
2. The provider-failure handler's actor reap is BOUNDED: a stalled actor (its
   in-flight turn never returns) is cancelled and dropped instead of delaying
   the resumable `interrupted` stamp unboundedly.
3. A degraded live-tool call (the Kali `exec` probe, the HTTP-history reads)
   records a tool-seam gap on the unit outcome, so a dead probe seam is visible
   in the run's report instead of a clean model built from the projection alone.
"""
from __future__ import annotations

import asyncio

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    Witness,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import (
    UnitOutcome,
    arun_modeller_pass,
)
from polymerhus.attack.hunting.threat_modeller_tools import ModellerTools

from tests.hunting_fixtures import ScriptedModellerTurns

PROJECT = "gap-proj"
RUN = "gap-run"
UNIT = "Service:gap-unit"
STALL_TIMEOUT = 0.05


def _candidate(unit_id: str = UNIT) -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id, fault_class="fault-x",
        applies_witnesses=Witness(deterministic="w"), match_verdict="applies")


# --- 1: the run-level dispatch-gap warning ------------------------------------

def test_a_completed_model_with_nothing_dispatchable_names_the_t4_gap(
        tmp_path, monkeypatch, caplog):
    """A run that models its unit but dispatches nothing must not land
    `complete` silently: one run-level warning names the T4 gap."""
    from tests.attack.test_hunting_modeller_wiring import (
        RUN as WIRING_RUN,
        _FakeControl,
        _FakePg,
        _noop_hunter_builder,
        _noop_pod_builder,
        _patch_pg,
    )

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(root_dir=tmp_path / "models")

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.runtime"):
        hid = asyncio.run(hunting_runtime.start_hunting(
            PROJECT, candidates=[_candidate()],
            modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
            graph_read_fn=lambda cypher, params: [],
            control=_FakeControl(),
            hunt_store=hunt, hunter_store=hunter, threat_store=models,
            hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
            tick_interval=0.001,
        ))

    assert hid == WIRING_RUN
    assert fake.statuses[-1] == (WIRING_RUN, "complete")
    gap_lines = [record.message for record in caplog.records
                 if "#377" in record.message]
    assert gap_lines, "the run must name the dispatch gap in one warning"
    line = gap_lines[-1]
    assert "T4" in line
    assert "dispatchable" in line and "zero" in line and "hunt" in line


def test_a_run_with_a_dispatchable_config_does_not_claim_a_dispatch_gap(
        tmp_path, monkeypatch, caplog):
    """A pre-produced ratified config IS dispatchable work: the run must not
    claim the T4 gap (the warning is conditional on nothing dispatchable)."""
    from tests.attack.test_hunting_modeller_wiring import (
        _FakeControl,
        _FakePg,
        _noop_hunter_builder,
        _noop_pod_builder,
        _patch_pg,
    )

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(root_dir=tmp_path / "models")
    hunt.write_config(PROJECT, {
        "hunt_id": f"{UNIT}::fault-x::CSRF", "unit_id": UNIT,
        "fault_class": "fault-x", "vulnerability_class": "CSRF",
        "status": "ratified",
        # the seeds the ratified-config validity predicate requires
        "rationale": "r", "research_direction": "rd",
    })

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.runtime"):
        asyncio.run(hunting_runtime.start_hunting(
            PROJECT, candidates=[_candidate()],
            modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
            graph_read_fn=lambda cypher, params: [],
            control=_FakeControl(),
            hunt_store=hunt, hunter_store=hunter, threat_store=models,
            hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
            tick_interval=0.001,
        ))

    assert not [record for record in caplog.records
                if "#377" in record.message], \
        "a dispatchable produced config must suppress the T4 gap warning"


# --- 2: the bounded actor reap ------------------------------------------------

def test_the_provider_failure_reap_is_bounded_and_cancels_a_stalled_actor(
        monkeypatch):
    """A stalled modeller actor (stop never returns) must not delay the
    resumable terminal: the reap times out at `drain_timeout`, the actor's task
    is cancelled, and the run still lands `interrupted`."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError
    from polymerhus.attack.hunting import threat_modeller as tm
    from tests.attack.test_hunting_modeller_wiring import _FakeControl, _FakePg

    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status",
                        fake.set_hunting_run_status)

    class _StalledActor:
        """The reviewer's stalled actor: `stop` awaits its in-flight turn
        forever, and the session task is still running."""

        def __init__(self):
            self._task = asyncio.ensure_future(asyncio.sleep(30))
            self.stop_entered = False

        async def stop(self):
            self.stop_entered = True
            await asyncio.sleep(30)

        def last_degrade_cause(self):
            return None

    actor = None

    async def _drive():
        nonlocal actor
        actor = _StalledActor()
        tm._MODELLER_ACTORS.clear()
        tm._MODELLER_ACTORS[RUN] = actor
        await asyncio.wait_for(
            hunting_runtime.stop_hunting_for_provider_failure(
                _FakeControl(), RUN,
                error=ProviderUnavailableError("throttled", status_code=429,
                                               quota_exhausted=False),
                tick_interval=0.001, drain_timeout=STALL_TIMEOUT,
            ),
            timeout=5,
        )
        await asyncio.sleep(0)  # let the cancellation land
        await asyncio.sleep(0)
        return actor

    actor = asyncio.run(_drive())

    assert actor.stop_entered is True, "the reap must attempt the stop"
    assert actor._task.cancelled() is True, (
        "a reap that times out must cancel the actor's task")
    assert tm._MODELLER_ACTORS == {}
    assert fake.statuses == [(RUN, "interrupted")]


# --- 3: the tool-seam gap sink ------------------------------------------------

def test_a_dead_exec_seam_records_a_context_gap_on_the_unit_outcome(tmp_path):
    """A degraded `exec` call (no Kali seam) records a tool-seam gap the pass
    folds into the unit outcome, so a run whose probe seam is dead reports the
    gap instead of a clean model built from the projection alone."""
    store = ThreatModelStore(root_dir=tmp_path)
    tools = ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN,
                          exec_fn=None)
    turns = _exec_probing_turns()

    outcome = asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, tools,
                                             turn_fn=turns))

    assert outcome.status == "completed"
    assert any("exec" in gap for gap in outcome.context_gaps), outcome.context_gaps


def test_a_dead_http_history_seam_records_a_context_gap(tmp_path):
    """The HTTP-history read pair records its gap through the SAME sink (the
    modeller binds both seams fail-open)."""
    store = ThreatModelStore(root_dir=tmp_path)
    tools = ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN,
                          http_search_fn=None, http_get_fn=None)
    turns = _exec_probing_turns(http=True)

    outcome = asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, tools,
                                             turn_fn=turns))

    assert any("http" in gap for gap in outcome.context_gaps), outcome.context_gaps


def test_the_hunter_exec_tool_keeps_its_fail_open_bundle(tmp_path):
    """The hunter's tools are UNCHANGED: with no gap sink the degraded bundle is
    exactly what it always was, and nothing is recorded anywhere."""
    import json

    from polymerhus.attack.hunting.hunter_tools import ExecTool, build_hunter_tools

    tool = ExecTool(exec_fn=None)
    assert json.loads(tool.invoke({"command": "id"}))["degraded"] is True

    hunter_tools = build_hunter_tools(project_id=PROJECT)
    exec_tools = [t for t in hunter_tools if t.name == "exec"]
    assert exec_tools and getattr(exec_tools[0], "_gap_sink", None) is None


def _exec_probing_turns(http: bool = False):
    """The scripted turn seam that writes every gate AND probes through the live
    tools, so the seam failure is exercised exactly as a model would."""
    inner = ScriptedModellerTurns()

    def turns(turn):
        surface = {tool.name: tool for tool in turn.tools}
        if turn.state.value == "UNIT_TECHNICAL_SHARP":
            if http:
                surface["search_http_history"].invoke({"filters": []})
                surface["get_http_artifact"].invoke({"artifact_id": "a1"})
            else:
                surface["exec"].invoke({"command": "id"})
        return inner(turn)

    turns.inner = inner
    return turns


# --- the run-level reason helper ---------------------------------------------

def test_the_gap_reason_names_the_t4_ticket_and_is_absent_with_work(tmp_path):
    """`run_work_remaining_gap_reason` is the ONE predicate behind the warning:
    it names T4 (#377) when a completed model exists and nothing is
    dispatchable, and returns None otherwise (a dispatchable config, no
    completed model)."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")

    from polymerhus.attack.hunting.surfer import RunDispatchState

    empty = RunDispatchState()
    reason = hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="completed")],
        state=empty, hunt_store=hunt, hunter_store=hunter)
    assert reason is not None
    assert "T4" in reason and "#377" in reason

    # a degraded unit is not a produced model: no gap to report
    assert hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="degraded")],
        state=empty, hunt_store=hunt, hunter_store=hunter) is None

    # a hunter dispatch recorded on the run state suppresses the line
    dispatched = RunDispatchState()
    dispatched.hunter_inboxes[f"{UNIT}::fault-x::CSRF"] = object()
    assert hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="completed")],
        state=dispatched, hunt_store=hunt, hunter_store=hunter) is None

    # a still-dispatchable produced item suppresses the line too
    hunt.write_config(PROJECT, {
        "hunt_id": f"{UNIT}::fault-x::CSRF", "unit_id": UNIT,
        "fault_class": "fault-x", "vulnerability_class": "CSRF",
        "status": "ratified",
        # the seeds the ratified-config validity predicate requires
        "rationale": "r", "research_direction": "rd",
    })
    assert hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="completed")],
        state=empty, hunt_store=hunt, hunter_store=hunter) is None


def test_the_sink_is_shared_by_the_surface_builder(tmp_path):
    """The sink is ONE per tools instance (like the suite seam), so the actor's
    captured surface records into the same log the pass reads."""
    from polymerhus.attack.hunting.threat_modeller_tools import (
        build_modeller_tool_surface,
    )

    store = ThreatModelStore(root_dir=tmp_path)
    tools = ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN)
    surface = build_modeller_tool_surface(PROJECT, UNIT, tools)
    surface["exec"].invoke({"command": "id"})
    surface["exec"].invoke({"command": "id"})

    assert tools.seam_gaps is not None
    assert len(tools.seam_gaps.gaps) == 2
    assert all("exec" in gap for gap in tools.seam_gaps.gaps)
