"""Unit tier: the impure sync gate (`RunSyncGate`) - the adapter that turns the
stores and the session registry into the pure policy's fact snapshot.

Pins the storage-backed facts the ADR names:

- the modeller pass's session id is the first gate (nothing dispatches while it
  is live);
- the queue order reads each unit's model (`model_sum`-equivalent loop weights)
  and the run record's intake positions;
- a live pod session keeps its unit current (a consumed spec with no export is
  still work);
- the serial cursor reads the hunts' spec stems (produced + consumed) and the
  durable PodExport records.
"""
from __future__ import annotations

from polymerhus.attack.hunting.mover import (
    TestSpecItem,
    ThreatLoopItem,
    threat_modeller_session_id,
)
from polymerhus.attack.hunting.pipeline_sync import RunSyncGate, SyncMode

PROJECT = "proj-1"
RUN = "run-1"


def _loop(unit_name: str = "u1", loop_id: str = "loop-1", *,
          unit_id: str | None = None) -> ThreatLoopItem:
    dispatch = f"{unit_name}__{loop_id}"
    return ThreatLoopItem(
        message_id=dispatch,
        session_id=f"hunting:{RUN}:hunt:{dispatch}",
        unit_id=unit_id or f"Service:{unit_name}",
        unit_name=unit_name,
        loop_id=loop_id,
        dispatch_id=dispatch,
        likelihood="high",
        record={"loop": {"id": loop_id}},
    )


def _spec(hunt_key: str = "u1__loop-1", stem: str = "sqli_blind",
          unit_id: str = "Service:u1") -> TestSpecItem:
    return TestSpecItem(
        message_id=f"{hunt_key}/{stem}",
        session_id=f"hunting:{RUN}:pod:{hunt_key}:{stem}",
        hunt_key=hunt_key,
        spec_file=stem,
        spec={"status": "ratified", "target": {"unit_id": unit_id}},
    )


class FakeThreatStore:
    def __init__(self, models=None):
        self.models = models or {}
        self.reads = 0

    def read_model(self, project_id, unit_id):
        self.reads += 1
        return self.models.get(unit_id)


class FakeHunterStore:
    def __init__(self, produced=None, consumed=None, bodies=None):
        self._produced = produced or {}
        self._consumed = consumed or {}
        self._bodies = bodies or {}

    def produced_spec_files(self, project_id, hunt_key):
        return list(self._produced.get(hunt_key, ()))

    def consumed_spec_files(self, project_id, hunt_key):
        return list(self._consumed.get(hunt_key, ()))

    def read_spec(self, project_id, hunt_key, spec_id, *, side="produced"):
        return self._bodies.get((hunt_key, spec_id))


class FakePodStore:
    def __init__(self, exports=()):
        self.exports = set(exports)

    def read_pod_export(self, spec_id, run_id):
        return {"verdict": "successful"} if (spec_id, run_id) in self.exports else {}


def _gate(mode: SyncMode, *, models=None, produced=None, consumed=None,
          bodies=None, exports=(), intake_order=None) -> RunSyncGate:
    return RunSyncGate(
        mode=mode,
        project_id=PROJECT,
        run_id=RUN,
        threat_store=FakeThreatStore(models),
        hunter_store=FakeHunterStore(produced, consumed, bodies),
        pod_store=FakePodStore(exports),
        intake_order=intake_order,
    )


def _ids(items):
    return tuple(item.message_id for item in items)


def test_gate_holds_everything_while_the_modeller_is_live():
    gate = _gate(SyncMode.BATCHED)
    items = [_loop()]
    assert gate.filter(
        items, live_session_ids={threat_modeller_session_id(RUN)}) == ()


def test_gate_orders_units_by_the_model_risk_contribution():
    models = {
        "Service:u1": {"unit_id": "Service:u1", "loops": [
            {"id": "loop-1", "likelihood": "low"}]},
        "Service:u2": {"unit_id": "Service:u2", "loops": [
            {"id": "loop-1", "likelihood": "high"}]},
    }
    gate = _gate(SyncMode.BATCHED, models=models)
    items = [_loop("u1"), _loop("u2")]
    admitted = gate.filter(items)
    # u2 carries the heavier loop, so it is the current unit and its hunter batch
    # is the only admissible item.
    assert _ids(admitted) == (_loop("u2").message_id,)


def test_gate_holds_the_next_unit_behind_a_live_pod():
    models = {
        "Service:u1": {"unit_id": "Service:u1", "loops": [
            {"id": "loop-1", "likelihood": "critical"}]},
        "Service:u2": {"unit_id": "Service:u2", "loops": [
            {"id": "loop-1", "likelihood": "low"}]},
    }
    pod_session = f"hunting:{RUN}:pod:u1__loop-1:sqli_blind"
    bodies = {
        ("u1__loop-1", "sqli_blind"): {
            "status": "ratified", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.BATCHED, models=models,
        consumed={"u1__loop-1": ["sqli_blind"]}, bodies=bodies,
    )
    admitted = gate.filter([_loop("u2")], live_session_ids={pod_session})
    assert admitted == ()


def test_gate_serial_reads_stems_and_exports_for_the_cursor_hunt():
    hunt = "u1__loop-1"
    gate = _gate(
        SyncMode.SERIAL,
        produced={hunt: ["a_first", "b_second"]},
    )
    # loop-1 is still a produced file: the hunter is the only admissible item.
    assert _ids(gate.filter([_loop("u1")])) == (f"{hunt}",)

    # The hunter left the graph and authored two specs: the first pod goes now.
    spec_a = _spec(hunt, "a_first")
    spec_b = _spec(hunt, "b_second")
    admitted = gate.filter([spec_a, spec_b])
    assert _ids(admitted) == (spec_a.message_id,)

    # The first export is durable: the second pod goes now.
    gate_x = _gate(
        SyncMode.SERIAL,
        produced={hunt: ["a_first", "b_second"]},
        exports={(("a_first"), RUN)},
    )
    assert _ids(gate_x.filter([spec_b])) == (spec_b.message_id,)


def test_gate_serial_ignores_a_dropped_spec_at_the_cursor():
    """A hunter-dropped spec is terminal by decision, not a missing export.

    Regression: the serial cursor counted every produced/consumed stem, so a
    dropped spec with no PodExport held the hunt forever.
    """
    hunt = "u1__loop-1"
    bodies = {
        (hunt, "a_dropped"): {
            "status": "dropped", "target": {"unit_id": "Service:u1"}},
        (hunt, "b_ratified"): {
            "status": "ratified", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.SERIAL,
        produced={hunt: ["a_dropped", "b_ratified"]},
        bodies=bodies,
    )
    spec_b = _spec(hunt, "b_ratified")
    assert _ids(gate.filter([spec_b])) == (spec_b.message_id,)


def test_gate_serial_moves_to_the_next_hunt_after_the_pods_are_terminal():
    hunt = "u1__loop-1"
    gate = _gate(
        SyncMode.SERIAL,
        produced={hunt: ["a_first"]},
        exports={(("a_first"), RUN)},
    )
    next_loop = _loop("u1", "loop-2")
    assert _ids(gate.filter([next_loop])) == (next_loop.message_id,)


def test_gate_intake_position_breaks_a_risk_tie():
    models = {
        "Service:u1": {"unit_id": "Service:u1", "loops": [
            {"id": "loop-1", "likelihood": "high"}]},
        "Service:u2": {"unit_id": "Service:u2", "loops": [
            {"id": "loop-1", "likelihood": "high"}]},
    }
    gate = _gate(
        SyncMode.BATCHED, models=models,
        intake_order=lambda: ("Service:u2", "Service:u1"),
    )
    assert _ids(gate.filter([_loop("u1"), _loop("u2")])) == (
        _loop("u2").message_id,)


def test_gate_parallel_returns_every_item_unchanged():
    gate = _gate(SyncMode.PARALLEL)
    items = [_loop("u1"), _loop("u2"), _spec()]
    assert gate.filter(items) == tuple(items)
