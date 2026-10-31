"""Unit tier: the hunting pipeline sync policy (`pipeline_sync.py`) - the PURE
decision surface behind the `hunting_pipeline_sync` mode (ADR
`docs/design/hunting-pipeline-sync-adr.md`; CVSS 4.0 amendment 2026-10-31).

The policy is a pure function over the produced items, the threat metadata, and
a storage-independent fact snapshot, so every mode's gating rule is pinned here
without a store, session, or clock:

- `parallel`: every item is admissible (today's behaviour);
- `batched`: the GLOBAL threat queue is worked in risk order - the current
  threat's hunter, then its pods once the hunter is terminal, in fixed blocks of
  `pod_batch_size` threats;
- `serial`: the same global queue, one agent at a time - hunter N+1 only after
  hunter N completed AND every one of its pods reached a terminal export; the
  pods of one hunt dispatch one at a time in file-stem order;
- empty member sets (a zero-spec hunt) advance the cursor immediately.

The queue is per-THREAT (spec 8): risk descending, then the unit intake
position, then the threat rank, then the dispatch id. There is no per-unit cap,
and the unit model sum never orders it.
"""
from __future__ import annotations

import logging

import pytest

from polymerhus.attack.hunting.mover import TestSpecItem, ThreatItem
from polymerhus.attack.hunting.risk_score import severity_band
from polymerhus.attack.hunting.pipeline_sync import (
    DEFAULT_SYNC_MODE,
    PipelineSyncState,
    SyncFacts,
    SyncMode,
    ThreatMeta,
    UnitMeta,
    batch_state,
    decide,
    hunt_rank,
    order_threats,
    resolve_mode,
    resolve_pod_batch_size,
    resolve_promotion_risk_threshold,
    risk_is_promoted,
    threat_is_demoted,
    threat_is_promoted,
    threat_queue,
    unit_of_dispatch,
)

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


def _spec(hunt_key: str = "u1__threat-1", stem: str = "sqli__blind__boolean") -> TestSpecItem:
    return TestSpecItem(
        message_id=f"{hunt_key}/{stem}",
        session_id=f"hunting:{RUN}:pod:{hunt_key}:{stem}",
        hunt_key=hunt_key,
        spec_file=stem,
        spec={"status": "ratified", "target": {"unit_id": "Service:u1"}},
    )


def _unit(name: str, intake: int = 1) -> UnitMeta:
    return UnitMeta(
        unit_name=name, unit_id=f"Service:{name}", intake_position=intake,
    )


def _meta(
    dispatch: str = "u1__threat-1", *,
    unit: str | None = None,
    risk: float = 9.3,
    intake: int = 1,
    rank: int | None = None,
) -> ThreatMeta:
    return ThreatMeta(
        dispatch_id=dispatch,
        unit_name=unit or unit_of_dispatch(dispatch),
        risk=risk,
        intake_position=intake,
        rank=hunt_rank(dispatch) if rank is None else rank,
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
        threats=(),
    )
    values.update(overrides)
    return SyncFacts(**values)


def _ids(items) -> set[str]:
    return {item.message_id for item in items}


# --- the mode vocabulary ---------------------------------------------------------

def test_sync_mode_values_and_default():
    assert {mode.value for mode in SyncMode} == {"serial", "batched", "parallel"}
    assert DEFAULT_SYNC_MODE is SyncMode.BATCHED


def test_the_model_threat_risk_reads_the_derived_float():
    from polymerhus.attack.hunting.pipeline_sync import _model_threat_risk

    assert _model_threat_risk({"risk": 9.3}) == 9.3
    assert _model_threat_risk({"risk": 9}) == 9.0
    assert _model_threat_risk({"risk": "bad"}) == 0.0
    assert _model_threat_risk({"risk": True}) == 0.0
    assert _model_threat_risk({}) == 0.0
    assert _model_threat_risk(None) == 0.0


def test_order_threats_is_risk_desc_then_intake_then_rank_then_dispatch_id():
    threats = [
        _meta("u-b__threat-1", risk=9.3, intake=2),
        _meta("u-a__threat-1", risk=9.3, intake=1),
        _meta("u-c__threat-2", risk=9.3, intake=1),
        _meta("u-c__threat-1", risk=9.3, intake=1),
        _meta("u-z__threat-9", risk=2.0, intake=0),
        _meta("u-a__threat-2", risk=9.3, intake=1),
    ]
    ordered = [threat.dispatch_id for threat in order_threats(threats)]
    assert ordered == [
        "u-a__threat-1", "u-c__threat-1", "u-a__threat-2", "u-c__threat-2",
        "u-b__threat-1", "u-z__threat-9",
    ]


def test_order_threats_is_deterministic_across_input_order():
    threats = [
        _meta("u1__threat-2", risk=9.3, intake=1),
        _meta("u1__threat-1", risk=9.3, intake=1),
        _meta("u2__threat-1", risk=9.3, intake=1),
        _meta("u0__threat-3", risk=2.0, intake=1),
    ]
    first = order_threats(threats)
    second = order_threats(reversed(threats))
    assert first == second
    assert [threat.dispatch_id for threat in first] == [
        "u1__threat-1", "u2__threat-1", "u1__threat-2", "u0__threat-3",
    ]


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

def test_batched_admits_only_the_current_threats_hunter():
    """One hunter at a time: the global queue's highest-risk threat."""
    items = [_threat(threat_id="threat-2", risk=2.0), _threat(threat_id="threat-1")]
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], _facts())
    assert admitted == {items[1].message_id}


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


def test_batched_admits_all_pods_of_the_first_hunt():
    hunt = "u1__threat-1"
    items = [
        _spec(hunt_key=hunt, stem="a_x"),
        _spec(hunt_key=hunt, stem="b_y"),
    ]
    facts = _facts(spec_stems={hunt: ("a_x", "b_y")})
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], facts)
    assert admitted == _ids(items)


def test_batched_admits_only_the_current_blocks_pods():
    first, second = "u1__threat-1", "u1__threat-2"
    items = [
        _spec(hunt_key=first, stem="a_x"),
        _spec(hunt_key=second, stem="b_y"),
    ]
    facts = _facts(spec_stems={first: ("a_x",), second: ("b_y",)})
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], facts)
    assert admitted == {items[0].message_id}


def test_batched_holds_the_next_hunt_until_every_pod_of_the_current_hunt_is_terminal():
    first, second = "u1__threat-1", "u1__threat-2"
    items = [
        _spec(hunt_key=first, stem="a_x"),
        _spec(hunt_key=first, stem="b_y"),
        _spec(hunt_key=second, stem="c_z"),
    ]
    facts = _facts(
        spec_stems={first: ("a_x", "b_y"), second: ("c_z",)},
        terminal_specs=frozenset({(first, "a_x")}),
    )
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], facts)
    assert admitted == {items[1].message_id}


def test_batched_advances_to_the_next_hunt_when_the_first_hunt_is_exported():
    first, second = "u1__threat-1", "u1__threat-2"
    items = [_spec(hunt_key=second, stem="c_z")]
    facts = _facts(
        spec_stems={first: ("a_x",), second: ("c_z",)},
        terminal_specs=frozenset({(first, "a_x")}),
    )
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], facts)
    assert admitted == {items[0].message_id}


def test_batched_holds_pods_until_the_hunter_is_terminal():
    hunt = "u1__threat-1"
    items = [_spec(hunt_key=hunt, stem="a_x")]
    facts = _facts(
        spec_stems={hunt: ("a_x",)},
        terminal_hunts=frozenset(),
    )
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], facts)
    assert admitted == frozenset()


def test_batched_holds_pods_for_a_blocked_hunt():
    hunt = "u1__threat-1"
    items = [_spec(hunt_key=hunt, stem="a_x")]
    facts = _facts(
        spec_stems={hunt: ("a_x",)},
        blocked_hunts=frozenset({hunt}),
    )
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1")], facts)
    assert admitted == frozenset()


def test_batched_does_not_hold_a_threat_behind_another_units_pod():
    """No unit barrier: a high-risk threat's hunter dispatches even while a
    DIFFERENT unit's pod phase is pending."""
    hunt = "u1__threat-1"
    items = [_spec(hunt_key=hunt), _threat(unit_name="u2", risk=9.3)]
    units = [_unit("u1", intake=1), _unit("u2", intake=2)]
    facts = _facts(
        spec_stems={hunt: ("sqli__blind__boolean",)},
        threats=(_meta(hunt, risk=2.0, intake=1),),
    )
    admitted = decide(SyncMode.BATCHED, items, units, facts)
    assert admitted == {items[1].message_id}


def test_batched_skips_a_done_threat_in_the_queue():
    items = [_threat(unit_name="u2", risk=2.0)]
    facts = _facts(threats=(
        _meta("u2__threat-1", risk=2.0),
        # A finished, fully exported higher threat: not work any more.
        _meta("u1__threat-1", risk=9.3),
    ), terminal_hunts=frozenset({"u1__threat-1"}))
    admitted = decide(SyncMode.BATCHED, items, [_unit("u1"), _unit("u2")], facts)
    assert admitted == {items[0].message_id}


# --- serial ----------------------------------------------------------------------

def test_serial_admits_one_hunter_and_holds_its_siblings():
    items = [
        _threat(threat_id="threat-2", risk=2.0),
        _threat(threat_id="threat-1", risk=9.3),
    ]
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], _facts())
    assert admitted == {items[1].message_id}


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
    items = [_spec(hunt_key=hunt, stem="a_first"), _threat(threat_id="threat-2", risk=2.0)]
    facts = _facts(
        spec_stems={hunt: ("a_first",)},
        threats=(_meta(hunt, risk=9.3), _meta("u1__threat-2", risk=2.0)),
    )
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], facts)
    # threat-2's hunter is held behind threat-1's unfinished pod; threat-1's pod
    # dispatches.
    assert admitted == {items[0].message_id}


def test_serial_advances_to_the_next_hunt_when_the_previous_hunt_is_fully_done():
    hunt = "u1__threat-1"
    items = [_threat(threat_id="threat-2", risk=2.0)]
    facts = _facts(
        spec_stems={hunt: ("a_first",)},
        terminal_specs=frozenset({(hunt, "a_first")}),
        threats=(_meta(hunt, risk=9.3), _meta("u1__threat-2", risk=2.0)),
    )
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], facts)
    assert admitted == {items[0].message_id}


def test_serial_treats_a_specless_hunt_as_done():
    items = [_threat(threat_id="threat-2", risk=2.0)]
    facts = _facts(
        threats=(_meta("u1__threat-1", risk=9.3), _meta("u1__threat-2", risk=2.0)),
        terminal_hunts=frozenset({"u1__threat-1"}),
    )
    admitted = decide(SyncMode.SERIAL, items, [_unit("u1")], facts)
    # threat-1 was dispatched earlier, authored no specs and left the graph: done.
    assert admitted == {items[0].message_id}


def test_serial_holds_the_next_threat_while_the_current_threat_is_in_graph():
    items = [_threat(unit_name="u2", risk=2.0)]
    units = [_unit("u1", intake=1), _unit("u2", intake=2)]
    facts = _facts(
        hunts_in_graph=frozenset({"u1__threat-1"}),
        threats=(_meta("u1__threat-1", risk=9.3), _meta("u2__threat-1", risk=2.0)),
    )
    admitted = decide(SyncMode.SERIAL, items, units, facts)
    assert admitted == frozenset()


# --- the global queue (spec 8) ---------------------------------------------------

def test_a_one_threat_unit_at_9_3_dispatches_before_a_four_threat_unit_below_it():
    """The queue is per-threat (spec 8): the one-threat unit's 9.3 outranks every
    threat of the four-threat unit, so it dispatches first regardless of unit."""
    one = _threat(unit_name="one", risk=9.3)
    four = [
        _threat(unit_name="four", threat_id=f"threat-{index}", risk=risk)
        for index, risk in enumerate((9.2, 9.2, 5.3, 2.0), start=1)
    ]
    items = [*four, one]
    units = [_unit("one", intake=1), _unit("four", intake=2)]

    queue = threat_queue(items, units, _facts())
    assert [meta.dispatch_id for meta in queue] == [
        "one__threat-1",
        "four__threat-1",
        "four__threat-2",
        "four__threat-3",
        "four__threat-4",
    ]
    admitted = decide(SyncMode.BATCHED, items, units, _facts())
    assert admitted == {one.message_id}

    # Once the one-threat unit's hunt is done, the four-threat unit's top
    # threat is current: no unit barrier held it behind anything else.
    facts = _facts(terminal_hunts=frozenset({"one__threat-1"}))
    admitted = decide(SyncMode.BATCHED, four, units, facts)
    assert admitted == {four[0].message_id}


def test_no_per_unit_cap_queues_every_threat_of_one_unit():
    risks = (9.3, 2.0, 5.3, 6.9)
    items = [
        _threat(threat_id=f"threat-{index}", risk=risk)
        for index, risk in enumerate(risks, start=1)
    ]
    queue = threat_queue(items, [_unit("u1")], _facts())
    assert [meta.dispatch_id for meta in queue] == [
        "u1__threat-1", "u1__threat-4", "u1__threat-3", "u1__threat-2",
    ]

    # Each threat is admitted in its turn: the only limit is the one-hunter
    # phase, never a per-unit cap.
    remaining = list(items)
    admitted: list[str] = []
    for _ in range(len(items)):
        chosen = decide(SyncMode.BATCHED, remaining, [_unit("u1")], _facts())
        assert len(chosen) == 1
        admitted.append(next(iter(chosen)))
        remaining = [
            item for item in remaining if item.message_id not in chosen
        ]
    assert admitted == [
        "u1__threat-1", "u1__threat-4", "u1__threat-3", "u1__threat-2",
    ]


def test_the_ties_on_the_global_frontier_are_deterministic():
    items = [
        _threat(unit_name="b", risk=9.3),
        _threat(unit_name="a", risk=9.3),
    ]
    units = [_unit("a", intake=1), _unit("b", intake=1)]
    first = decide(SyncMode.BATCHED, items, units, _facts())
    second = decide(SyncMode.BATCHED, list(reversed(items)), units, _facts())
    assert first == second == {"a__threat-1"}


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
        SyncMode.BATCHED, hunt, [_threat(threat_id="threat-1")], _facts())
    assert hunting.phase == "hunt"
    assert hunting.current == hunt
    assert hunting.hunts == (hunt,)

    podding = batch_state(
        SyncMode.BATCHED, hunt, [_spec()],
        _facts(spec_stems={hunt: ("sqli__blind__boolean",)}),
    )
    assert podding.phase == "pod"
    assert podding.cursor == hunt


def test_batch_state_serial_reports_the_cursor_and_the_pod_cursor():
    hunt = "u1__threat-1"
    facts = _facts(
        spec_stems={hunt: ("a_first", "b_second")},
        terminal_specs=frozenset({(hunt, "a_first")}),
    )
    state = batch_state(SyncMode.SERIAL, hunt, [_spec(stem="b_second")], facts)
    assert state.phase == "serial"
    assert state.hunts == (hunt,)
    assert state.cursor == hunt
    assert state.pods == ("a_first", "b_second")
    assert state.pod_cursor == "b_second"

    done = batch_state(
        SyncMode.SERIAL, hunt, [],
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
    meta = state.meta_for("u2", "Service:u2")
    assert meta.intake_position == 1
    assert state.cached("u2") is meta
    assert state.meta_for("u1", "Service:u1").intake_position == 1_000_000
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


# --- the pod batch size and the promotion threshold (2026-10-26; floats 2026-10-31) --

def test_resolve_pod_batch_size_prefers_the_run_record_then_the_settings_then_one():
    assert resolve_pod_batch_size(3, {"pod_batch_size": 2}) == 3
    assert resolve_pod_batch_size(None, {"pod_batch_size": 2}) == 2
    assert resolve_pod_batch_size(None, {}) == 1
    assert resolve_pod_batch_size("bogus", {"pod_batch_size": 2}) == 2
    assert resolve_pod_batch_size(0, {"pod_batch_size": -1}) == 1
    assert resolve_pod_batch_size(True, {"pod_batch_size": 2}) == 2


def test_resolve_promotion_risk_threshold_prefers_the_run_record_then_the_settings_then_none():
    assert resolve_promotion_risk_threshold(
        2.5, {"promotion_risk_threshold": 4.0}, recorded_present=True) == 2.5
    assert resolve_promotion_risk_threshold(
        None, {"promotion_risk_threshold": 4.0}, recorded_present=True) is None
    assert resolve_promotion_risk_threshold(
        None, {"promotion_risk_threshold": 4.0}) == 4.0
    # A pre-v5 int stored in the blob still reads as a float.
    assert resolve_promotion_risk_threshold(
        None, {"promotion_risk_threshold": 4}) == 4.0
    assert resolve_promotion_risk_threshold(None, {}) is None
    assert resolve_promotion_risk_threshold(
        "bad", {"promotion_risk_threshold": 4.0}, recorded_present=True) == 4.0
    assert resolve_promotion_risk_threshold(
        -1, {"promotion_risk_threshold": -2.0}, recorded_present=True) is None


def test_risk_is_promoted_is_inclusive_and_off_by_default():
    assert risk_is_promoted(2.5, 2.5)
    assert not risk_is_promoted(2.4, 2.5)
    assert risk_is_promoted(9.3, 9.3)
    assert not risk_is_promoted(9.29, 9.3)
    assert risk_is_promoted(1.0, None)
    assert risk_is_promoted(1.0, 0)


def test_threat_is_promoted_reads_the_risk():
    assert threat_is_promoted({"risk": 6.9}, 5.0)
    assert not threat_is_promoted({"risk": 4.0}, 5.0)
    # A v4 threat file carries the same score as an int.
    assert threat_is_promoted({"risk": 9}, 9.0)
    # A legacy file without the stored risk falls back to the impact product:
    # high likelihood (3) x high impact (3) = 9.
    legacy = {
        "likelihood": "high",
        "threat": {"impact": {
            "confidentiality": "high",
            "integrity": "none",
            "availability": "none",
            "end_impact": "reads another tenant",
        }},
    }
    assert threat_is_promoted(legacy, 9.0)
    assert not threat_is_promoted(legacy, 9.1)
    # The model document stores the impact at the threat's own level; the same
    # fallback must read it.
    model_shape = {
        "likelihood": "high",
        "impact": {
            "confidentiality": "high",
            "integrity": "none",
            "availability": "none",
            "end_impact": "reads another tenant",
        },
    }
    assert threat_is_promoted(model_shape, 9.0)
    assert not threat_is_promoted(model_shape, 9.1)


def _spec_set(hunts):
    items = []
    stems = {}
    for index, hunt in enumerate(hunts, start=1):
        stem = f"s{index}"
        items.append(_spec(hunt_key=hunt, stem=stem))
        stems[hunt] = (stem,)
    return items, stems


def test_batched_admits_the_first_block_of_n_hunts():
    hunts = ("u1__threat-1", "u1__threat-2", "u1__threat-3")
    items, stems = _spec_set(hunts)

    admitted = decide(
        SyncMode.BATCHED, items, [_unit("u1")], _facts(spec_stems=stems),
        pod_batch_size=2,
    )

    assert admitted == {items[0].message_id, items[1].message_id}


def test_batched_holds_the_next_block_until_every_spec_in_the_block_is_terminal():
    hunts = ("u1__threat-1", "u1__threat-2", "u1__threat-3")
    items, stems = _spec_set(hunts)
    facts = _facts(
        spec_stems=stems,
        terminal_specs=frozenset({(hunts[0], "s1")}),
    )

    admitted = decide(
        SyncMode.BATCHED, items, [_unit("u1")], facts, pod_batch_size=2,
    )

    assert admitted == {items[1].message_id}


def test_batched_block_does_not_slide_when_an_earlier_hunt_is_done():
    hunts = ("u1__threat-1", "u1__threat-2", "u1__threat-3")
    items, stems = _spec_set(hunts)
    facts = _facts(
        spec_stems=stems,
        terminal_specs=frozenset({(hunts[0], "s1")}),
    )

    admitted = decide(
        SyncMode.BATCHED, [items[1], items[2]], [_unit("u1")], facts,
        pod_batch_size=2,
    )

    # Hunt 1 is done, but hunt 2 still holds the first block: hunt 3 must not
    # slide into its place.
    assert admitted == {items[1].message_id}


def test_batched_block_advances_to_the_next_block():
    hunts = (
        "u1__threat-1", "u1__threat-2", "u1__threat-3", "u1__threat-4",
    )
    items, stems = _spec_set(hunts)
    facts = _facts(
        spec_stems=stems,
        terminal_specs=frozenset({
            (hunts[0], "s1"), (hunts[1], "s2"),
        }),
    )

    admitted = decide(
        SyncMode.BATCHED, items, [_unit("u1")], facts, pod_batch_size=2,
    )

    assert admitted == {items[2].message_id, items[3].message_id}


def test_batched_block_holds_on_a_blocked_hunt():
    hunts = ("u1__threat-1", "u1__threat-2")
    items, stems = _spec_set(hunts)
    facts = _facts(
        spec_stems=stems,
        blocked_hunts=frozenset({hunts[0]}),
    )

    admitted = decide(
        SyncMode.BATCHED, items, [_unit("u1")], facts, pod_batch_size=2,
    )

    assert admitted == frozenset()


def test_batched_zero_spec_hunt_is_done_inside_its_block():
    first, second = "u1__threat-1", "u1__threat-2"
    item = _spec(hunt_key=second, stem="s2")
    facts = _facts(
        spec_stems={first: (), second: ("s2",)},
        terminal_hunts=frozenset({first, second}),
    )

    admitted = decide(
        SyncMode.BATCHED, [item], [_unit("u1")], facts, pod_batch_size=2,
    )

    assert admitted == {item.message_id}


def test_batched_batch_size_larger_than_the_hunts_clamps():
    hunts = ("u1__threat-1", "u1__threat-2", "u1__threat-3")
    items, stems = _spec_set(hunts)

    admitted = decide(
        SyncMode.BATCHED, items, [_unit("u1")], _facts(spec_stems=stems),
        pod_batch_size=10,
    )

    assert admitted == _ids(items)


def test_serial_ignores_the_pod_batch_size():
    first, second = "u1__threat-1", "u1__threat-2"
    items = [
        _spec(hunt_key=first, stem="a_first"),
        _spec(hunt_key=first, stem="b_second"),
        _spec(hunt_key=second, stem="c_third"),
    ]
    facts = _facts(spec_stems={
        first: ("a_first", "b_second"), second: ("c_third",),
    })

    admitted = decide(
        SyncMode.SERIAL, items, [_unit("u1")], facts, pod_batch_size=2,
    )

    assert admitted == {items[0].message_id}


def test_parallel_ignores_the_pod_batch_size():
    hunts = ("u1__threat-1", "u1__threat-2", "u1__threat-3")
    items, stems = _spec_set(hunts)

    admitted = decide(
        SyncMode.PARALLEL, items, [_unit("u1")], _facts(spec_stems=stems),
        pod_batch_size=2,
    )

    assert admitted == _ids(items)


def test_batch_state_reports_the_pod_block():
    hunts = ("u1__threat-1", "u1__threat-2", "u1__threat-3")
    items, stems = _spec_set(hunts)

    state = batch_state(
        SyncMode.BATCHED, hunts[0], items, _facts(spec_stems=stems),
        pod_batch_size=2,
    )

    assert state.phase == "pod"
    assert state.pod_batch == (hunts[0], hunts[1])
    assert state.cursor == hunts[0]


def test_threat_is_demoted_reads_only_a_readable_positive_risk():
    assert threat_is_demoted({"risk": 1.0}, 5.0)
    assert threat_is_demoted({"risk": 2.4}, 2.5)
    assert not threat_is_demoted({"risk": 2.5}, 2.5)
    assert not threat_is_demoted({"risk": 9.3}, 5.0)
    assert not threat_is_demoted({"risk": 0.0}, 5.0)
    assert not threat_is_demoted({"risk": 1.0}, None)
    assert not threat_is_demoted({"risk": "bad"}, 5.0)


def test_a_malformed_setting_warns_and_falls_through(caplog):
    with caplog.at_level(
        logging.WARNING, logger="polymerhus.attack.hunting.pipeline_sync",
    ):
        assert resolve_pod_batch_size(
            "bogus", {"pod_batch_size": 2}) == 2
        assert resolve_promotion_risk_threshold(
            "bad", {"promotion_risk_threshold": 4.0},
            recorded_present=True,
        ) == 4.0

    assert "pod_batch_size" in caplog.text
    assert "promotion_risk_threshold" in caplog.text
