"""Unit tier: the impure sync gate (`RunSyncGate`) - the adapter that turns the
stores and the session registry into the pure policy's fact snapshot.

Pins the storage-backed facts the ADR names:

- the modeller pass's session id is the first gate (nothing dispatches while it
  is live);
- the queue order reads each unit's model (`model_sum`-equivalent threat weights)
  and the run record's intake positions;
- a live pod session keeps its unit current (a consumed spec with no export is
  still work);
- the serial cursor reads the hunts' spec stems (produced + consumed) and the
  durable PodExport records.
"""
from __future__ import annotations

from polymerhus.attack.hunting.mover import (
    TestSpecItem,
    ThreatItem,
    threat_modeller_session_id,
)
from polymerhus.attack.hunting.pipeline_sync import RunSyncGate, SyncMode

PROJECT = "proj-1"
RUN = "run-1"


def _threat(unit_name: str = "u1", threat_id: str = "threat-1", *,
          unit_id: str | None = None) -> ThreatItem:
    dispatch = f"{unit_name}__{threat_id}"
    return ThreatItem(
        message_id=dispatch,
        session_id=f"hunting:{RUN}:hunt:{dispatch}",
        unit_id=unit_id or f"Service:{unit_name}",
        unit_name=unit_name,
        threat_id=threat_id,
        dispatch_id=dispatch,
        likelihood="high",
        record={"threat": {"id": threat_id}},
    )


def _spec(hunt_key: str = "u1__threat-1", stem: str = "sqli__blind__boolean",
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
    def __init__(self, produced=None, consumed=None, bodies=None,
                 terminals=None, malformed=()):
        self._produced = produced or {}
        self._consumed = consumed or {}
        self._bodies = bodies or {}
        self._terminals = terminals or {}
        self._malformed = set(malformed)

    def produced_spec_files(self, project_id, hunt_key):
        return list(self._produced.get(hunt_key, ()))

    def consumed_spec_files(self, project_id, hunt_key):
        return list(self._consumed.get(hunt_key, ()))

    def read_spec(self, project_id, hunt_key, spec_id, *, side="produced"):
        if (hunt_key, spec_id) in self._malformed:
            raise OSError(f"malformed spec {hunt_key}/{spec_id}")
        return self._bodies.get((hunt_key, spec_id))

    def read_terminal_set(self, project_id, hunt_key):
        return self._terminals.get(hunt_key)

    def list_hunt_keys(self, project_id):
        return sorted(set(self._produced) | set(self._consumed))


class FakePodStore:
    def __init__(self, exports=()):
        self.exports = set(exports)

    def read_pod_export(self, spec_id, run_id):
        return {"verdict": "successful"} if (spec_id, run_id) in self.exports else {}


def _gate(mode: SyncMode, *, models=None, produced=None, consumed=None,
          bodies=None, exports=(), intake_order=None, terminals=None,
          malformed=()) -> RunSyncGate:
    return RunSyncGate(
        mode=mode,
        project_id=PROJECT,
        run_id=RUN,
        threat_store=FakeThreatStore(models),
        hunter_store=FakeHunterStore(
            produced, consumed, bodies, terminals=terminals,
            malformed=malformed),
        pod_store=FakePodStore(exports),
        intake_order=intake_order,
    )


def _terminal(hunt: str, **statuses: str) -> dict:
    return {
        "schema_version": 1,
        "hunt_key": hunt,
        "run_id": RUN,
        "status": "terminal",
        "spec_statuses": dict(statuses),
    }


def _ids(items):
    return tuple(item.message_id for item in items)


def test_gate_holds_everything_while_the_modeller_is_live():
    gate = _gate(SyncMode.BATCHED)
    items = [_threat()]
    assert gate.filter(
        items, live_session_ids={threat_modeller_session_id(RUN)}) == ()


def test_gate_orders_units_by_the_model_risk_contribution():
    models = {
        "Service:u1": {"unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "likelihood": "low"}]},
        "Service:u2": {"unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "likelihood": "high"}]},
    }
    gate = _gate(SyncMode.BATCHED, models=models)
    items = [_threat("u1"), _threat("u2")]
    admitted = gate.filter(items)
    # u2 carries the heavier threat, so it is the current unit and its hunter batch
    # is the only admissible item.
    assert _ids(admitted) == (_threat("u2").message_id,)


def test_gate_holds_the_next_unit_behind_a_live_pod():
    models = {
        "Service:u1": {"unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "likelihood": "critical"}]},
        "Service:u2": {"unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "likelihood": "low"}]},
    }
    pod_session = f"hunting:{RUN}:pod:u1__threat-1:sqli_blind"
    bodies = {
        ("u1__threat-1", "sqli__blind__boolean"): {
            "status": "ratified", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.BATCHED, models=models,
        consumed={"u1__threat-1": ["sqli__blind__boolean"]}, bodies=bodies,
    )
    admitted = gate.filter([_threat("u2")], live_session_ids={pod_session})
    assert admitted == ()


def test_gate_serial_reads_stems_and_exports_for_the_cursor_hunt():
    hunt = "u1__threat-1"
    bodies = {
        (hunt, "a_first"): {
            "status": "ratified", "target": {"unit_id": "Service:u1"}},
        (hunt, "b_second"): {
            "status": "ratified", "target": {"unit_id": "Service:u1"}},
    }
    terminal = _terminal(hunt, a_first="ratified", b_second="ratified")
    gate = _gate(
        SyncMode.SERIAL,
        produced={hunt: ["a_first", "b_second"]},
        bodies=bodies,
        terminals={hunt: terminal},
    )
    # threat-1 is still a produced file: the hunter is the only admissible item.
    assert _ids(gate.filter([_threat("u1")])) == (f"{hunt}",)

    # The hunter left the graph and finalized: the first pod goes now.
    spec_a = _spec(hunt, "a_first")
    spec_b = _spec(hunt, "b_second")
    admitted = gate.filter([spec_a, spec_b])
    assert _ids(admitted) == (spec_a.message_id,)

    # The first export is durable: the second pod goes now.
    gate_x = _gate(
        SyncMode.SERIAL,
        produced={hunt: ["b_second"]},
        consumed={hunt: ["a_first"]},
        bodies=bodies,
        terminals={hunt: terminal},
        exports={(("a_first"), RUN)},
    )
    assert _ids(gate_x.filter([spec_b])) == (spec_b.message_id,)


def test_gate_serial_ignores_a_dropped_spec_at_the_cursor():
    """A hunter-dropped spec is terminal by decision, not a missing export.

    Regression: the serial cursor counted every produced/consumed stem, so a
    dropped spec with no PodExport held the hunt forever.
    """
    hunt = "u1__threat-1"
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
        terminals={hunt: _terminal(
            hunt, a_dropped="dropped", b_ratified="ratified")},
    )
    spec_b = _spec(hunt, "b_ratified")
    assert _ids(gate.filter([spec_b])) == (spec_b.message_id,)


def test_gate_serial_blocks_a_stale_hypothesised_hunt():
    """A stale draft must hold the queue, not be silently skipped."""
    stale = "u1__threat-1"
    models = {
        "Service:u1": {"unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "likelihood": "high"}]},
        "Service:u2": {"unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "likelihood": "low"}]},
    }
    bodies = {
        (stale, "a_draft"): {
            "status": "hypothesised", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.SERIAL,
        models=models,
        produced={stale: ["a_draft"]},
        bodies=bodies,
    )
    assert gate.filter([_threat("u2")]) == ()


def test_gate_serial_blocks_a_hypothesised_spec_behind_a_terminal_marker():
    """A stale draft written after finalize must not hide behind the marker."""
    hunt = "u1__threat-1"
    models = {
        "Service:u1": {"unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "likelihood": "high"}]},
        "Service:u2": {"unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "likelihood": "low"}]},
    }
    bodies = {
        (hunt, "a_late"): {
            "status": "hypothesised", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.SERIAL,
        models=models,
        produced={hunt: ["a_late"]},
        bodies=bodies,
        terminals={hunt: _terminal(hunt, a_late="ratified")},
    )
    assert gate.filter([_threat("u2")]) == ()


def test_gate_serial_requires_the_hunter_terminal_marker():
    """A consumed spec with an export is not completion without the marker."""
    hunt = "u1__threat-1"
    models = {
        "Service:u1": {"unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "likelihood": "high"}]},
        "Service:u2": {"unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "likelihood": "low"}]},
    }
    bodies = {
        (hunt, "a_first"): {
            "status": "ratified", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.SERIAL,
        models=models,
        consumed={hunt: ["a_first"]},
        bodies=bodies,
        exports={(("a_first"), RUN)},
    )
    assert gate.filter([_threat("u2")]) == ()


def test_gate_serial_blocks_an_invalid_spec_status():
    """A non-ratified, non-dropped status is not dispatchable and must not be
    skipped. An unparsable YAML body is the same failure, owned by the upstream
    write-gate ticket; the gate also treats it as blocked when the unit id is
    recoverable."""
    hunt = "u1__threat-1"
    models = {
        "Service:u1": {"unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "likelihood": "high"}]},
        "Service:u2": {"unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "likelihood": "low"}]},
    }
    bodies = {
        (hunt, "bad"): {
            "status": "garbage", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.SERIAL,
        models=models,
        produced={hunt: ["bad"]},
        bodies=bodies,
    )
    assert gate.filter([_threat("u2")]) == ()


def test_gate_serial_treats_unsuccessful_export_as_terminal():
    """A failed or degraded pod execution still closes the consumed spec."""
    hunt = "u1__threat-1"
    models = {
        "Service:u1": {"unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "likelihood": "high"}]},
        "Service:u2": {"unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "likelihood": "low"}]},
    }
    bodies = {
        (hunt, "a_first"): {
            "status": "ratified", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.SERIAL,
        models=models,
        consumed={hunt: ["a_first"]},
        bodies=bodies,
        terminals={hunt: _terminal(hunt, a_first="ratified")},
        exports={(("a_first"), RUN)},
    )
    assert _ids(gate.filter([_threat("u2")])) == (
        _threat("u2").message_id,)


def test_gate_serial_moves_to_the_next_hunt_after_the_pods_are_terminal():
    hunt = "u1__threat-1"
    bodies = {
        (hunt, "a_first"): {
            "status": "ratified", "target": {"unit_id": "Service:u1"}},
    }
    gate = _gate(
        SyncMode.SERIAL,
        consumed={hunt: ["a_first"]},
        bodies=bodies,
        terminals={hunt: _terminal(hunt, a_first="ratified")},
        exports={(("a_first"), RUN)},
    )
    next_threat = _threat("u1", "threat-2")
    assert _ids(gate.filter([next_threat])) == (next_threat.message_id,)


def test_gate_intake_position_breaks_a_risk_tie():
    models = {
        "Service:u1": {"unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "likelihood": "high"}]},
        "Service:u2": {"unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "likelihood": "high"}]},
    }
    gate = _gate(
        SyncMode.BATCHED, models=models,
        intake_order=lambda: ("Service:u2", "Service:u1"),
    )
    assert _ids(gate.filter([_threat("u1"), _threat("u2")])) == (
        _threat("u2").message_id,)


def test_gate_parallel_returns_every_item_unchanged():
    gate = _gate(SyncMode.PARALLEL)
    items = [_threat("u1"), _threat("u2"), _spec()]
    assert gate.filter(items) == tuple(items)
