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
from polymerhus.attack.hunting.risk_score import severity_band

PROJECT = "proj-1"
RUN = "run-1"


def _threat(unit_name: str = "u1", threat_id: str = "threat-1", *,
          unit_id: str | None = None, risk: float = 9.3) -> ThreatItem:
    dispatch = f"{unit_name}__{threat_id}"
    return ThreatItem(
        message_id=dispatch,
        session_id=f"hunting:{RUN}:hunt:{dispatch}",
        unit_id=unit_id or f"Service:{unit_name}",
        unit_name=unit_name,
        threat_id=threat_id,
        dispatch_id=dispatch,
        record={"threat": {"id": threat_id}},
        risk=risk,
        band=severity_band(risk).value,
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
    def __init__(self, models=None, produced=None):
        self.models = models or {}
        self.produced = produced or []
        self.reads = 0

    def read_model(self, project_id, unit_id):
        self.reads += 1
        return self.models.get(unit_id)

    def read_produced_threats(self, project_id):
        return list(self.produced)


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
          malformed=(), threat_produced=None, pod_batch_size=1,
          promotion_risk_threshold=None) -> RunSyncGate:
    return RunSyncGate(
        mode=mode,
        project_id=PROJECT,
        run_id=RUN,
        threat_store=FakeThreatStore(models, threat_produced),
        hunter_store=FakeHunterStore(
            produced, consumed, bodies, terminals=terminals,
            malformed=malformed),
        pod_store=FakePodStore(exports),
        intake_order=intake_order,
        pod_batch_size=pod_batch_size,
        promotion_risk_threshold=promotion_risk_threshold,
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


def test_gate_orders_threats_by_the_derived_score():
    models = {
        "Service:u1": {"state": "COMPLETED", "unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "risk": 2.0}]},
        "Service:u2": {"state": "COMPLETED", "unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "risk": 9.3}]},
    }
    gate = _gate(SyncMode.BATCHED, models=models)
    items = [_threat("u1", risk=2.0), _threat("u2", risk=9.3)]
    admitted = gate.filter(items)
    # u2's threat carries the higher derived score, so its hunter is the only
    # admissible item: the unit model sum orders nothing.
    assert _ids(admitted) == (_threat("u2").message_id,)


def test_gate_holds_the_next_unit_behind_a_live_pod():
    models = {
        "Service:u1": {"state": "COMPLETED", "unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "risk": 9.9}]},
        "Service:u2": {"state": "COMPLETED", "unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "risk": 2.0}]},
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


def _spec_body(unit_id: str = "Service:u1") -> dict:
    return {"status": "ratified", "target": {"unit_id": unit_id}}


def test_gate_batched_admits_only_the_first_hunts_pods():
    first, second = "u1__threat-1", "u1__threat-2"
    bodies = {
        (first, "a_first"): _spec_body(),
        (second, "b_second"): _spec_body(),
    }
    terminals = {
        first: _terminal(first, a_first="ratified"),
        second: _terminal(second, b_second="ratified"),
    }
    gate = _gate(
        SyncMode.BATCHED,
        produced={first: ["a_first"], second: ["b_second"]},
        bodies=bodies,
        terminals=terminals,
    )
    spec_first = _spec(first, "a_first")
    spec_second = _spec(second, "b_second")

    admitted = gate.filter([spec_first, spec_second])

    assert _ids(admitted) == (spec_first.message_id,)


def test_gate_batched_holds_the_next_hunt_until_every_pod_of_the_current_hunt_is_terminal():
    first, second = "u1__threat-1", "u1__threat-2"
    bodies = {
        (first, "a_first"): _spec_body(),
        (first, "b_second"): _spec_body(),
        (second, "c_third"): _spec_body(),
    }
    terminals = {
        first: _terminal(first, a_first="ratified", b_second="ratified"),
        second: _terminal(second, c_third="ratified"),
    }
    gate = _gate(
        SyncMode.BATCHED,
        consumed={first: ["a_first", "b_second"], second: ["c_third"]},
        bodies=bodies,
        terminals=terminals,
        exports={("a_first", RUN)},
    )
    spec_b = _spec(first, "b_second")
    spec_c = _spec(second, "c_third")

    admitted = gate.filter([spec_b, spec_c])

    assert _ids(admitted) == (spec_b.message_id,)


def test_gate_batched_advances_to_the_next_hunt_when_the_first_is_exported():
    first, second = "u1__threat-1", "u1__threat-2"
    bodies = {
        (first, "a_first"): _spec_body(),
        (second, "c_third"): _spec_body(),
    }
    terminals = {
        first: _terminal(first, a_first="ratified"),
        second: _terminal(second, c_third="ratified"),
    }
    gate = _gate(
        SyncMode.BATCHED,
        consumed={first: ["a_first"], second: ["c_third"]},
        bodies=bodies,
        terminals=terminals,
        exports={("a_first", RUN)},
    )
    spec_a = _spec(first, "a_first")
    spec_c = _spec(second, "c_third")

    admitted = gate.filter([spec_a, spec_c])

    assert _ids(admitted) == (spec_c.message_id,)


def test_gate_batched_holds_pods_until_every_hunt_is_terminal():
    hunt = "u1__threat-1"
    gate = _gate(
        SyncMode.BATCHED,
        produced={hunt: ["a_first"]},
        bodies={(hunt, "a_first"): _spec_body()},
    )

    admitted = gate.filter([_spec(hunt, "a_first")])

    assert admitted == ()


def test_gate_batched_holds_the_next_hunt_while_the_current_hunt_has_a_live_pod():
    first, second = "u1__threat-1", "u1__threat-2"
    bodies = {
        (first, "a_first"): _spec_body(),
        (second, "c_third"): _spec_body(),
    }
    terminals = {
        first: _terminal(first, a_first="ratified"),
        second: _terminal(second, c_third="ratified"),
    }
    gate = _gate(
        SyncMode.BATCHED,
        consumed={first: ["a_first"], second: ["c_third"]},
        bodies=bodies,
        terminals=terminals,
        exports={("a_first", RUN)},
    )
    live = f"hunting:{RUN}:pod:{first}:a_first"

    admitted = gate.filter([_spec(second, "c_third")], live_session_ids={live})

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
        "Service:u1": {"state": "COMPLETED", "unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "risk": 9.3}]},
        "Service:u2": {"state": "COMPLETED", "unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "risk": 2.0}]},
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
        "Service:u1": {"state": "COMPLETED", "unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "risk": 9.3}]},
        "Service:u2": {"state": "COMPLETED", "unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "risk": 2.0}]},
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
        "Service:u1": {"state": "COMPLETED", "unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "risk": 9.3}]},
        "Service:u2": {"state": "COMPLETED", "unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "risk": 2.0}]},
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
        "Service:u1": {"state": "COMPLETED", "unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "risk": 9.3}]},
        "Service:u2": {"state": "COMPLETED", "unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "risk": 2.0}]},
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
        "Service:u1": {"state": "COMPLETED", "unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "risk": 9.3}]},
        "Service:u2": {"state": "COMPLETED", "unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "risk": 2.0}]},
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
        "Service:u1": {"state": "COMPLETED", "unit_id": "Service:u1", "threats": [
            {"id": "threat-1", "risk": 9.3}]},
        "Service:u2": {"state": "COMPLETED", "unit_id": "Service:u2", "threats": [
            {"id": "threat-1", "risk": 9.3}]},
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


def test_gate_batched_admits_the_first_block_of_n_hunts():
    first, second, third = "u1__threat-1", "u1__threat-2", "u1__threat-3"
    bodies = {
        (first, "a_first"): _spec_body(),
        (second, "b_second"): _spec_body(),
        (third, "c_third"): _spec_body(),
    }
    terminals = {
        first: _terminal(first, a_first="ratified"),
        second: _terminal(second, b_second="ratified"),
        third: _terminal(third, c_third="ratified"),
    }
    gate = _gate(
        SyncMode.BATCHED,
        produced={
            first: ["a_first"], second: ["b_second"], third: ["c_third"],
        },
        bodies=bodies,
        terminals=terminals,
        pod_batch_size=2,
    )
    items = [
        _spec(first, "a_first"),
        _spec(second, "b_second"),
        _spec(third, "c_third"),
    ]

    admitted = gate.filter(items)

    assert _ids(admitted) == (items[0].message_id, items[1].message_id)


def test_gate_batched_holds_the_next_block_until_the_first_block_is_exported():
    first, second, third = "u1__threat-1", "u1__threat-2", "u1__threat-3"
    bodies = {
        (first, "a_first"): _spec_body(),
        (second, "b_second"): _spec_body(),
        (third, "c_third"): _spec_body(),
    }
    terminals = {
        first: _terminal(first, a_first="ratified"),
        second: _terminal(second, b_second="ratified"),
        third: _terminal(third, c_third="ratified"),
    }
    gate = _gate(
        SyncMode.BATCHED,
        consumed={
            first: ["a_first"], second: ["b_second"], third: ["c_third"],
        },
        bodies=bodies,
        terminals=terminals,
        exports={("a_first", RUN)},
        pod_batch_size=2,
    )
    items = [
        _spec(first, "a_first"),
        _spec(second, "b_second"),
        _spec(third, "c_third"),
    ]

    admitted = gate.filter(items)

    # Hunt 1 is exported, hunt 2 still holds the first block, and hunt 3 must
    # not slide into its place.
    assert _ids(admitted) == (items[1].message_id,)


def test_gate_batched_does_not_slide_a_done_hunt_out_of_its_block():
    first, second, third = "u1__threat-1", "u1__threat-2", "u1__threat-3"
    model = {"Service:u1": {"state": "COMPLETED", "threats": [
        {"id": "threat-1", "risk": 9},
        {"id": "threat-2", "risk": 9},
        {"id": "threat-3", "risk": 9},
    ]}}
    bodies = {
        (second, "b_second"): _spec_body(),
        (third, "c_third"): _spec_body(),
    }
    terminals = {
        first: _terminal(first, a_first="ratified"),
        second: _terminal(second, b_second="ratified"),
        third: _terminal(third, c_third="ratified"),
    }
    gate = _gate(
        SyncMode.BATCHED,
        models=model,
        consumed={
            first: ["a_first"], second: ["b_second"], third: ["c_third"],
        },
        bodies=bodies,
        terminals=terminals,
        exports={("a_first", RUN)},
        pod_batch_size=2,
    )
    items = [_spec(second, "b_second"), _spec(third, "c_third")]

    admitted = gate.filter(items)

    assert _ids(admitted) == (items[0].message_id,)


def test_gate_ignores_a_demoted_hunt_with_a_stale_spec_folder():
    first, second = "u1__threat-1", "u1__threat-2"
    model = {"Service:u1": {"state": "COMPLETED", "threats": [
        {"id": "threat-1", "risk": 9},
        {"id": "threat-2", "risk": 1},
    ]}}
    demoted = [{
        "run_id": RUN,
        "unit_name": "u1",
        "threats": [{"threat_id": "threat-2", "record": {"risk": 1}}],
    }]
    gate = _gate(
        SyncMode.BATCHED,
        models=model,
        produced={first: ["a_first"], second: ["b_second"]},
        bodies={
            (first, "a_first"): _spec_body(),
            (second, "b_second"): _spec_body(),
        },
        terminals={first: _terminal(first, a_first="ratified")},
        threat_produced=demoted,
        promotion_risk_threshold=5,
    )
    item = _spec(first, "a_first")

    admitted = gate.filter([item])

    assert _ids(admitted) == (item.message_id,)


def test_gate_ignores_a_demoted_leftover_spec_after_the_model_moved():
    """The gate half of the after-consume audit: a demoted hunt's leftover spec
    folder must not block the pod phase once the unit model left produced/."""
    first, second = "u1__threat-1", "u1__threat-2"
    model = {"Service:u1": {
        "state": "COMPLETED",
        "run_id": RUN,
        "threats": [
            {"id": "threat-1", "risk": 9},
            {"id": "threat-2", "risk": 1},
        ],
    }}
    gate = _gate(
        SyncMode.BATCHED,
        models=model,
        produced={first: ["a_first"], second: ["b_second"]},
        bodies={
            (first, "a_first"): _spec_body(),
            (second, "b_second"): _spec_body(),
        },
        terminals={first: _terminal(first, a_first="ratified")},
        promotion_risk_threshold=5,
    )
    item = _spec(first, "a_first")

    assert _ids(gate.filter([item])) == (item.message_id,)


def test_gate_ignores_an_unobservable_promoted_model_threat():
    """A promoted model threat with no item, no spec, no graph, no pod, and no
    terminal marker has no hunt artifact. It must not hold the pod phase."""
    first, second = "u1__threat-1", "u1__threat-2"
    model = {"Service:u1": {"state": "COMPLETED", "threats": [
        {"id": "threat-1", "risk": 9},
        {"id": "threat-2", "risk": 9},
    ]}}
    gate = _gate(
        SyncMode.BATCHED,
        models=model,
        produced={first: ["a_first"]},
        bodies={(first, "a_first"): _spec_body()},
        terminals={first: _terminal(first, a_first="ratified")},
    )
    item = _spec(first, "a_first")

    assert _ids(gate.filter([item])) == (item.message_id,)
