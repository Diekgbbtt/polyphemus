"""Unit tier: the hunting pipeline sync policy (`pipeline_sync.py`) - the PURE
decision surface behind the `hunting_pipeline_sync` mode (ADR
`docs/design/hunting-pipeline-sync-adr.md`).

The policy is a pure function over the produced items, the unit metadata, and a
storage-independent fact snapshot, so every mode's gating rule is pinned here
without a store, session, or clock:

- `parallel`: every item is admissible (today's behaviour);
- `batched`: one unit at a time in risk order; the unit's whole hunter batch
  dispatches concurrently, and its pods only once no hunt of the unit is still
  mid-graph or still holding a produced threat file;
- `serial`: the same queue, one agent at a time - hunter N+1 only after hunter
  N completed AND every one of its pods reached a terminal export; the pods of
  one hunt dispatch one at a time in file-stem order;
- empty member sets (a zero-spec hunt) advance the cursor immediately.
"""
from __future__ import annotations

import pytest

from polymerhus.attack.hunting.mover import TestSpecItem, ThreatItem
from polymerhus.attack.hunting.pipeline_sync import (
    DEFAULT_SYNC_MODE,
    PipelineSyncState,
    SyncFacts,
    SyncMode,
    UnitMeta,
    batch_state,
    decide,
    order_units,
    resolve_mode,
)

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


def _spec(hunt_key: str = "u1__threat-1", stem: str = "sqli__blind__boolean") -> TestSpecItem:
    return TestSpecItem(
        message_id=f"{hunt_key}/{stem}",
        session_id=f"hunting:{RUN}:pod:{hunt_key}:{stem}",
        hunt_key=hunt_key,
        spec_file=stem,
        spec={"status": "ratified", "target": {"unit_id": "Service:u1"}},
    )


def _unit(name: str, risk: int = 1, intake: int = 1) -> UnitMeta:
    return UnitMeta(
        unit_name=name, unit_id=f"Service:{name}", risk=risk,
        intake_position=intake,
    )


def _facts(**overrides) -> SyncFacts:
    stems = overrides.get("spec_stems") or {}
    values = dict(
        modeller_live=False,
        hunts_in_graph=frozenset(),
        live_pod_hunts=frozenset(),
        spec_stems={},
        terminal_specs=frozenset(),
        # The pure decision tests model an already-finalized hunter: every
        # hunt that carries a dispatch cursor is terminal for this run unless a
        # test overrides the lifecycle facts explicitly.
        pending_spec_stems={},
        consumed_spec_stems=dict(stems),
        terminal_hunts=frozenset(stems),
        blocked_hunts=frozenset(),
    )
    values.update(overrides)
    return SyncFacts(**values)


def _ids(items) -> set[str]:
    return {item.message_id for item in items}


# --- the mode vocabulary ---------------------------------------------------------

def test_sync_mode_values_and_default():
    assert {mode.value for mode in SyncMode} == {"serial", "batched", "parallel"}
    assert DEFAULT_SYNC_MODE is SyncMode.BATCHED


def test_the_threat_weight_uses_the_combined_risk():
    from polymerhus.attack.hunting.pipeline_sync import _threat_weight

    assert _threat_weight({"risk": 9, "likelihood": "high"}) == 9
    assert _threat_weight({"likelihood": "high"}) == 3
    assert _threat_weight({"risk": "bad"}) == 0
    assert _threat_weight(None) == 0


def test_order_units_is_risk_desc_then_intake_position_then_name():
    units = [
        _unit("low", risk=1, intake=1),
        _unit("high-b", risk=9, intake=2),
        _unit("high-a", risk=9, intake=2),
        _unit("high-first", risk=9, intake=1),
    ]
    ordered = [unit.unit_name for unit in order_units(units)]
    assert ordered == ["high-first", "high-a", "high-b", "low"]


def test_resolve_mode_prefers_the_run_record_then_the_settings_then_the_default():
    assert resolve_mode("serial", {"pipeline_sync": "parallel"}) is SyncMode.SERIAL
    assert resolve_mode(None, {"pipeline_sync": "parallel"}) is SyncMode.PARALLEL
    assert resolve_mode(None, {}) is SyncMode.BATCHED
    assert resolve_mode("bogus", {"pipeline_sync": "bogus"}) is SyncMode.BATCHED


# --- the modeller gate -----------------------------------------------------------

@pytest.mark.parametrize("mode", [SyncMode.BATCHED, SyncMode.SERIAL])
def test_modeller_live_holds_every_item(mode):
    items = [_threat(), _spec()]
    admitted = decide(mode, items, [_unit("u1")], _facts(modeller_live=True))
    assert admitted == frozenset()


# --- batched ---------------------------------------------------------------------

def test_batched_admits_the_whole_unit_hunter_batch():
    items = [_threat(threat_id="threat-1"), _threat(threat_id="threat-2")]
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], _facts())
    assert admitted == _ids(items)


def test_batched_refuses_pods_while_a_hunt_file_remains():
    items = [_threat(threat_id="threat-1"), _spec()]
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], _facts())
    assert admitted == {items[0].message_id}


def test_batched_refuses_pods_while_a_hunt_is_mid_graph():
    items = [_spec()]
    admitted = decide(
        SyncMode.BATCHED, items, [_unit("u1")],
        _facts(hunts_in_graph=frozenset({"u1__threat-1"})),
    )
    assert admitted == frozenset()


def test_batched_admits_all_pods_after_the_hunt_batch():
    items = [_spec(stem="a_x"), _spec(stem="b_y")]
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], _facts())
    assert admitted == _ids(items)


def test_batched_holds_the_next_unit_until_the_current_unit_is_done():
    items = [_spec(hunt_key="u1__threat-1"), _threat(unit_name="u2")]
    units = [_unit("u1", risk=9), _unit("u2", risk=1)]
    admitted = decide(SyncMode.BATCHED, items, units, _facts())
    # u1 is the current unit (risk-desc) and is in its pod phase; u2 is held.
    assert admitted == {items[0].message_id}


def test_batched_skips_a_done_unit_in_the_queue():
    items = [_threat(unit_name="u2")]
    units = [_unit("u1", risk=9), _unit("u2", risk=1)]
    admitted = decide(SyncMode.BATCHED, items, units, _facts())
    assert admitted == {items[0].message_id}


# --- serial ----------------------------------------------------------------------

def test_serial_admits_one_hunter_and_holds_its_siblings():
    items = [_threat(threat_id="threat-1"), _threat(threat_id="threat-2")]
    facts = _facts(
        spec_stems={"u1__threat-2": ("sqli__blind__boolean",)},
        terminal_specs=frozenset(),
    )
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], facts)
    assert admitted == {items[0].message_id}


def test_serial_dispatches_pods_one_at_a_time_in_stem_order():
    hunt = "u1__threat-1"
    items = [_spec(hunt_key=hunt, stem="a_first"), _spec(hunt_key=hunt, stem="b_second")]
    facts = _facts(spec_stems={hunt: ("a_first", "b_second")})
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], facts)
    assert admitted == {items[0].message_id}


def test_serial_advances_the_pod_cursor_past_terminal_specs():
    hunt = "u1__threat-1"
    items = [_spec(hunt_key=hunt, stem="b_second")]
    facts = _facts(
        spec_stems={hunt: ("a_first", "b_second")},
        terminal_specs=frozenset({(hunt, "a_first")}),
    )
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], facts)
    assert admitted == {items[0].message_id}


def test_serial_holds_the_next_hunter_until_the_previous_hunts_pods_are_terminal():
    hunt = "u1__threat-1"
    items = [_spec(hunt_key=hunt, stem="a_first"), _threat(threat_id="threat-2")]
    facts = _facts(spec_stems={hunt: ("a_first",)})
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], facts)
    # threat-2's hunter is held behind threat-1's unfinished pod; threat-1's pod dispatches.
    assert admitted == {items[0].message_id}


def test_serial_advances_to_the_next_hunt_when_the_previous_hunt_is_fully_done():
    hunt = "u1__threat-1"
    items = [_threat(threat_id="threat-2")]
    facts = _facts(
        spec_stems={hunt: ("a_first",)},
        terminal_specs=frozenset({(hunt, "a_first")}),
    )
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], facts)
    assert admitted == {items[0].message_id}


def test_serial_treats_a_specless_hunt_as_done():
    items = [_threat(threat_id="threat-2")]
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], _facts())
    # threat-1 was dispatched earlier, authored no specs and left the graph: done.
    assert admitted == {items[0].message_id}


def test_serial_holds_the_next_unit_while_the_current_units_hunt_is_in_graph():
    items = [_threat(unit_name="u2")]
    units = [_unit("u1", risk=9), _unit("u2", risk=1)]
    facts = _facts(hunts_in_graph=frozenset({"u1__threat-1"}))
    admitted = decide(SyncMode.SERIAL, items, units, facts)
    assert admitted == frozenset()


# --- parallel and the empty surface ---------------------------------------------

def test_parallel_admits_every_item():
    items = [_threat(), _spec(), _threat(unit_name="u2")]
    admitted = decide(SyncMode.PARALLEL, items, [_unit("u1"), _unit("u2")], _facts())
    assert admitted == _ids(items)


def test_no_items_yields_no_decision():
    assert decide(SyncMode.BATCHED, [], [_unit("u1")], _facts()) == frozenset()


# --- the state classes -----------------------------------------------------------

def test_batch_state_batched_reports_the_hunt_then_the_pod_phase():
    hunt = "u1__threat-1"
    hunting = batch_state(
        SyncMode.BATCHED, "u1", [_threat(threat_id="threat-1")], _facts())
    assert hunting.phase == "hunt"
    assert hunting.hunts == (hunt,)

    podding = batch_state(SyncMode.BATCHED, "u1", [_spec()], _facts())
    assert podding.phase == "pod"


def test_batch_state_serial_reports_the_cursor_and_the_pod_cursor():
    hunt = "u1__threat-1"
    facts = _facts(
        spec_stems={hunt: ("a_first", "b_second")},
        terminal_specs=frozenset({(hunt, "a_first")}),
    )
    state = batch_state(SyncMode.SERIAL, "u1", [_spec(stem="b_second")], facts)
    assert state.phase == "serial"
    assert state.hunts == (hunt,)
    assert state.cursor == hunt
    assert state.pods == ("a_first", "b_second")
    assert state.pod_cursor == "b_second"

    done = batch_state(
        SyncMode.SERIAL, "u1", [],
        _facts(
            spec_stems={hunt: ("a_first",)},
            terminal_specs=frozenset({(hunt, "a_first")}),
        ),
    )
    assert done.phase == "done"
    assert done.cursor is None


def test_pipeline_sync_state_caches_the_meta_and_the_intake_position():
    state = PipelineSyncState(
        mode=SyncMode.SERIAL, intake_order=("Service:u2",))
    meta = state.meta_for("u2", "Service:u2", risk=4)
    assert meta.risk == 4
    assert meta.intake_position == 1
    assert state.cached("u2") is meta
    assert state.meta_for("u1", "Service:u1", risk=0).intake_position == 1_000_000
    assert state.mode is SyncMode.SERIAL


def test_the_gate_reads_the_live_target_identity_unit():
    """The live spec carries `target_identity.unit_id`; the gate must find it
    before the legacy `target.unit_id` and the provenance fallback."""
    from polymerhus.attack.hunting.pipeline_sync import _spec_unit_id

    assert _spec_unit_id(
        {"target_identity": {"unit_id": "Service:u1"}}) == "Service:u1"
    assert _spec_unit_id({"target": {"unit_id": "Service:u2"}}) == "Service:u2"
    assert _spec_unit_id(
        {"provenance": {"unit_id": "Service:u3"}}) == "Service:u3"
    assert _spec_unit_id({}) == ""
