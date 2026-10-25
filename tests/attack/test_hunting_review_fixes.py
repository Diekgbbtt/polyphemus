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
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import (
    UnitOutcome,
    arun_modeller_pass,
)
from polymerhus.attack.hunting.threat_modeller_tools import ModellerTools

from tests.hunting_fixtures import (
    ScriptedModellerTurns,
    intake_unit,
    produce_model,
)

PROJECT = "gap-proj"
RUN = "gap-run"
UNIT = "Service:gap-unit"
STALL_TIMEOUT = 0.05


# --- 1: the run-level dispatch-gap warning ------------------------------------

def test_a_completed_model_with_nothing_dispatchable_names_the_gap(
        tmp_path, monkeypatch, caplog):
    """A run that models its unit but dispatches nothing must not land
    `complete` silently: one run-level warning names the reason.

    The modeller here completes a ZERO-LOOP model (every vulnerability dropped),
    so the mover consumes the model document without a dispatch (S2 8.4) and
    nothing is ever admitted - the line says that, without blaming a later
    ticket (the looping case is T4a's C1 test and the inert-builder line)."""
    from tests.attack.test_hunting_modeller_wiring import (
        RUN as WIRING_RUN,
        _FakeControl,
        _FakePg,
        _noop_hunter_builder,
        _noop_pod_builder,
        _patch_pg,
    )
    from tests.hunting_fixtures import modeller_gate_payloads

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(root_dir=tmp_path / "models")
    payloads = modeller_gate_payloads()
    from polymerhus.attack.hunting.threat_model import ModelState

    vulnerable = payloads[ModelState.VULNERABILITIES_WRITTEN]["vulnerabilities"][0]
    payloads[ModelState.VULNERABILITIES_WRITTEN] = {"vulnerabilities": [{
        **vulnerable,
        "dropped": True,
        "drop_reason": "the lookup binds the id to the tenant; the mechanics are absent",
        "drop_probe": "a second tenant's item id returning that item",
    }]}
    payloads[ModelState.COMPLETED] = {"loops": []}

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.runtime"):
        hid = asyncio.run(hunting_runtime.start_hunting(
            PROJECT, intake_units=[intake_unit(UNIT)],
            modeller_kwargs={"turn_fn": ScriptedModellerTurns(payloads=payloads)},
            graph_read_fn=lambda cypher, params: [],
            control=_FakeControl(),
            hunter_store=hunter, threat_store=models,
            hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
            tick_interval=0.001,
        ))

    assert hid == WIRING_RUN
    assert fake.statuses[-1] == (WIRING_RUN, "complete")
    # the zero-loop model was consumed without a dispatch (S2 8.4)
    assert models.read_completed_units(PROJECT) == [UNIT]
    gap_lines = [record.message for record in caplog.records
                 if "NOTHING is dispatchable" in record.message]
    assert gap_lines, "the run must name the dispatch gap in one warning"
    line = gap_lines[-1]
    assert "no dispatchable loop file was produced" in line
    assert "zero hunts" in line


def test_a_run_with_dispatchable_loop_work_does_not_claim_a_dispatch_gap(
        tmp_path, monkeypatch, caplog):
    """A produced loop file IS dispatchable work (S2 8.4): the run must not
    claim the dispatch gap (the warning is conditional on nothing
    dispatchable). The retired config family is not dispatch input at all, so a
    leftover produced config can no longer suppress the line (T4b #387)."""
    from tests.attack.test_hunting_modeller_wiring import (
        _FakeControl,
        _FakePg,
        _noop_hunter_builder,
        _noop_pod_builder,
        _patch_pg,
    )

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(root_dir=tmp_path / "models")
    produce_model(models, project_id=PROJECT, unit_id=UNIT, run_id=RUN)

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.runtime"):
        asyncio.run(hunting_runtime.start_hunting(
            PROJECT, intake_units=[intake_unit(UNIT)],
            modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
            graph_read_fn=lambda cypher, params: [],
            control=_FakeControl(),
            hunter_store=hunter, threat_store=models,
            hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
            tick_interval=0.001,
        ))

    assert not [record for record in caplog.records
                if "#379" in record.message], \
        "a dispatchable produced item must suppress the gap warning"


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

def test_the_gap_reason_names_the_stuck_loop_and_is_absent_with_work(
        tmp_path, monkeypatch):
    """`report_dispatch_gap` is the ONE predicate behind the warning: when a
    completed model exists and nothing is dispatchable, it names the stuck
    produced loop files - and returns None when the produced loop is
    dispatchable work, no model completed, or a dispatch was recorded."""
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(root_dir=tmp_path / "models")
    _produce_one_loop_model(models, run_id=RUN)

    from polymerhus.attack.hunting.surfer import RunDispatchState

    empty = RunDispatchState()
    # a pending read that says "nothing dispatchable" while the loop file is
    # still produced: the gap line names the stuck loop (a refused admission or
    # a stopped role left it behind)
    monkeypatch.setattr(
        "polymerhus.attack.hunting.surfer.run_work_remaining",
        lambda *a, **kw: False)
    reason = hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="completed")],
        state=empty, threat_store=models, hunter_store=hunter)
    assert reason is not None
    assert "1 produced loop file" in reason
    assert "stayed undispatched" in reason
    monkeypatch.undo()

    # unpatched, the same LOOP is dispatchable work, so the gap line is not a
    # gap at all: the run is not quiescing yet
    assert hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="completed")],
        state=empty, threat_store=models, hunter_store=hunter) is None

    # a degraded unit is not a produced model: no gap to report
    assert hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="degraded")],
        state=empty, threat_store=models, hunter_store=hunter) is None

    # a hunter dispatch recorded on the run state suppresses the line
    dispatched = RunDispatchState()
    dispatched.hunter_inboxes[f"{UNIT}__loop-1"] = object()
    assert hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="completed")],
        state=dispatched, threat_store=models, hunter_store=hunter) is None

    # a still-dispatchable produced SPEC suppresses the line too (the pod
    # family stays live; the retired config family would no longer count)
    _write_ratified_spec(hunter)
    assert hunting_runtime.report_dispatch_gap(
        PROJECT, RUN, [UnitOutcome(unit_id=UNIT, status="completed")],
        state=empty, threat_store=models, hunter_store=hunter) is None


def test_a_production_builder_run_consumes_a_zero_loop_model(
        tmp_path, monkeypatch, caplog):
    """R1 (T4a review round 2): the INERT run (the production builder, which cannot
    consume the loop payload) must still consume a zero-loop produced COMPLETED
    valid model - the modeller's legitimate "nothing to hunt here" outcome - with
    no dispatch, and the gap line must not claim a decided model was undecided.

    The run is complete, the model is in consumed/, and a LATER intake excludes
    the unit (a consumed model is decided), so the zero-loop unit is never
    re-modelled."""
    from tests.attack.test_hunting_modeller_wiring import (
        RUN as WIRING_RUN,
        _FakeControl,
        _FakePg,
        _noop_pod_builder,
        _patch_pg,
    )
    from tests.hunting_fixtures import ScriptedModellerTurns

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(root_dir=tmp_path / "models")
    control = _FakeControl()

    # NO hunter_builder: the run resolves the PRODUCTION one (T6: it consumes the
    # loop payload end to end; there is no loop here, so nothing dispatches)
    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.runtime"):
        hid = asyncio.run(hunting_runtime.start_hunting(
            PROJECT, intake_units=[intake_unit(UNIT)],
            modeller_kwargs={"turn_fn": _zero_loop_turns()},
            graph_read_fn=lambda cypher, params: [],
            control=control,
            hunter_store=hunter, threat_store=models,
            pod_builder=_noop_pod_builder,
            tick_interval=0.001,
        ))

    assert hid == WIRING_RUN
    assert fake.statuses[-1] == (WIRING_RUN, "complete")
    # the zero-loop model IS consumed (the mover's no-dispatch consume, S2 8.4)
    assert models.read_completed_units(PROJECT) == [UNIT]
    assert models.read_produced_loops(PROJECT) == []
    # and the gap line does NOT claim the model is undecided
    lines = [record.message for record in caplog.records
             if "NOTHING is dispatchable" in record.message]
    assert lines
    assert "every model is decided" in lines[-1]

    # a later intake excludes the unit: a consumed model is decided (S2 9.3)
    from polymerhus.attack.hunting.unit_intake import freeze_intake

    plan = freeze_intake([intake_unit(UNIT)], completed_ids=[UNIT])
    assert plan.order == ()
    assert [(exclusion.unit_id, exclusion.reason) for exclusion in plan.excluded] \
        == [(UNIT, "completed")]


def _zero_loop_turns():
    """The scripted modeller turn seam whose COMPLETED write has no loop (every
    vulnerability dropped): the model the mover consumes without a dispatch."""
    from tests.hunting_fixtures import ScriptedModellerTurns, modeller_gate_payloads
    from polymerhus.attack.hunting.threat_model import ModelState

    payloads = modeller_gate_payloads()
    vulnerable = payloads[ModelState.VULNERABILITIES_WRITTEN]["vulnerabilities"][0]
    payloads[ModelState.VULNERABILITIES_WRITTEN] = {"vulnerabilities": [{
        **vulnerable, "dropped": True,
        "drop_reason": "the mechanics are absent",
        "drop_probe": "a second tenant's item id returning that item",
    }]}
    payloads[ModelState.COMPLETED] = {"loops": []}
    return ScriptedModellerTurns(payloads=payloads)


def _write_ratified_spec(hunter) -> None:
    """One produced `ratified` test spec (the pod family's dispatch gate) -
    the surviving dispatchable produced family (S3 8.7). The draft lands first
    so the store's identity-stability rule holds."""
    spec = {"status": "hypothesised", "discriminators": [
        {"axis": "fault", "value": "sqli"},
        {"axis": "technique", "value": "blind"}]}
    hunter.write_specs(
        PROJECT, "Service-catalogue-and-discovery__loop-1", [spec])
    hunter.write_specs(
        PROJECT, "Service-catalogue-and-discovery__loop-1",
        [{**spec, "status": "ratified"}])


def _produce_one_loop_model(store, *, run_id: str, unit_id: str = UNIT):
    """This module's binding of the SHARED produced-model fixture."""
    return produce_model(
        store, project_id=PROJECT, unit_id=unit_id, run_id=run_id)


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


def test_the_stop_reap_is_bounded_by_the_drain_timeout(monkeypatch):
    """T3 #376 carry-forward: `stop_hunting`'s actor reap is bounded by the same
    drain timeout as the provider-failure path - a stalled actor's task is
    cancelled and the `stopped` terminal still lands."""
    from polymerhus.attack.hunting import threat_modeller as tm
    from tests.attack.test_hunting_modeller_wiring import _FakePg

    fake = _FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status",
                        fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs",
                        fake.list_hunting_runs)

    class _StalledActor:
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
        # the stop's own drain bound is 30s; shrink the bounded awaits so the
        # test stays fast (a real 30s wait would not prove the bound)
        real_wait_for = asyncio.wait_for
        monkeypatch.setattr(
            asyncio, "wait_for",
            lambda aw, timeout: real_wait_for(aw, timeout=min(timeout, STALL_TIMEOUT)))
        await real_wait_for(hunting_runtime.stop_hunting(RUN), timeout=5)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return actor

    actor = asyncio.run(_drive())

    assert actor.stop_entered is True, "the reap must attempt the stop"
    assert actor._task.cancelled() is True, (
        "a reap that times out must cancel the actor's task")
    assert tm._MODELLER_ACTORS == {}
    assert fake.statuses == [(RUN, "stopped")]


def test_the_dispatch_gap_survives_a_transient_pending_work_read_failure(
        tmp_path, monkeypatch, caplog):
    """T3 #376 carry-forward: the dispatch-gap report is guarded - a transient
    failure of the surfer's pending-work read must not raise into the run
    terminal; the gap line still lands."""
    from polymerhus.attack.hunting.surfer import run_work_remaining
    from tests.attack.test_hunting_modeller_wiring import _FakePg

    def _explode(*_a, **_kw):
        raise OSError("store read failed (fixture)")

    monkeypatch.setattr(
        "polymerhus.attack.hunting.surfer.run_work_remaining", _explode)
    from polymerhus.attack.hunting.surfer import RunDispatchState

    models = ThreatModelStore(root_dir=tmp_path / "models")
    _produce_one_loop_model(models, run_id=RUN)
    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.runtime"):
        reason = hunting_runtime.report_dispatch_gap(
            PROJECT, RUN,
            [UnitOutcome(unit_id=UNIT, status="completed")],
            state=RunDispatchState(),
            threat_store=models,
            hunter_store=HunterMemoryStore(tmp_path / "hunter"),
        )

    assert reason is not None and "produced loop file" in reason
    assert any("pending-work read degraded" in record.message
               for record in caplog.records)
