"""Unit tier: the hunter's pass-chain graph topology (S4 14.10).

The graph is the PASSIVE tracker over the ReAct host: `supervise` is the sole
entry, `detect` is the pure acceptance rule, `advance` writes the state move
plus the hint plus the trail entry. The machine never gates a tool call and
never rejects a signal; END is reached only on `complete`.
"""
from __future__ import annotations

from polymerhus.attack.hunting import hunter_graph as G
from polymerhus.attack.hunting import hunter_state as S


def _signal(phase):
    return {"kind": "phase_note", "phase": phase}


def _drive(state: dict, signal=None) -> dict:
    """One harness-style drive: hand the tracker its accumulated state plus the
    observation, read the merged channels back."""
    graph = G.build_hunter_graph().compile()
    return graph.invoke({**state, "observed_signal": signal})


# --- the entry router (S4 14.10) ----------------------------------------------


def test_the_entry_router_ends_only_on_complete():
    """S4 14.10: `supervise` routes to END on `complete`, to `detect` when a
    signal is pending, and holds (no destination) otherwise - a mid-chain drive
    never claims the chain is over."""
    assert G.route_supervise({"state": S.COMPLETE}) == "__end__"
    assert G.route_supervise(
        {"state": "collect", "observed_signal": _signal("collect")}) == G._DETECT
    # no signal, not complete: the turn carries no signal - stay
    assert G.route_supervise({"state": "collect"}) is None
    # the chain opens ungrounded
    assert G.route_supervise(
        {"observed_signal": _signal("grounding")}) == G._DETECT
    assert G.route_supervise({}) is None


# --- the active path (S4 14.10) -----------------------------------------------


def test_the_drive_advances_and_injects_the_exited_hint_and_the_trail_entry():
    driven = _drive({"state": "grounding", "specs": [], "trail": []},
                    _signal("grounding"))
    assert driven["state"] == "slice"
    assert driven["injected_constant"] == S.GROUNDING_HINT
    assert driven["trail"] == [{
        "signal": _signal("grounding"),
        "outcome": "advance",
        "from": "grounding",
        "to": "slice",
    }]
    # the observation is consumed: it never leaks onto the next drive
    assert driven["observed_signal"] is None


def test_the_drive_forwards_jumps_and_records_the_skipped_passes():
    driven = _drive({"state": "grounding", "specs": [], "trail": []},
                    {"kind": "spec_set_write", "statuses": ["hypothesised"]})
    assert driven["state"] == "well_formedness"
    assert driven["injected_constant"] == S.GENERATE_HINT
    assert driven["trail"][0]["skipped"] == [
        "slice", "collect", "discriminate", "generate"]


def test_the_drive_trails_an_earlier_signal_and_never_moves_the_state_back():
    driven = _drive({"state": "verify_claims", "specs": [], "trail": []},
                    _signal("collect"))
    assert driven["state"] == "verify_claims"
    assert driven.get("injected_constant") is None
    assert driven["trail"] == [{
        "signal": _signal("collect"),
        "outcome": "trail_only",
        "from": "verify_claims",
        "to": "verify_claims",
    }]


def test_the_drive_stays_when_the_turn_carries_no_signal():
    """S4 14.10: `supervise --no signal--> supervise (stay)`. Nothing moves, no
    hint is injected, and no trail entry is appended."""
    driven = _drive({"state": "slice", "specs": [], "trail": []}, None)
    assert driven["state"] == "slice"
    assert driven.get("injected_constant") is None
    assert driven.get("trail") == []


def test_the_drive_appends_the_trail_across_drives():
    """The `trail` channel is `operator.add`: the accumulated trajectory is
    never re-appended (only the fresh entry returns per drive)."""
    state = {"state": "grounding", "specs": [], "trail": []}
    state = _drive(state, _signal("grounding"))
    state = _drive(state, _signal("slice"))
    assert [entry["outcome"] for entry in state["trail"]] == ["advance", "advance"]
    assert [entry["to"] for entry in state["trail"]] == ["slice", "collect"]


def test_the_drive_ends_on_complete_and_a_later_signal_moves_nothing():
    """S4 14.10: the finalize call lands `complete`; the graph then ends - a
    later signal is not even observed (no state move, no trail entry)."""
    state = {"state": "verify_claims", "specs": [], "trail": []}
    state = _drive(state, {"kind": "spec_set_finalize"})
    assert state["state"] == "complete"
    assert state["injected_constant"] == S.VERIFY_CLAIMS_HINT
    ended = _drive(state, _signal("grounding"))
    assert ended["state"] == "complete"
    assert len(ended["trail"]) == 1  # only the terminal drive's entry


def test_a_garbage_signal_never_raises_and_never_moves_the_state():
    """The no-block invariant: whatever the model signalled, the tracker
    records and never rejects - an unreadable signal is a stay."""
    state = {"state": "collect", "specs": [], "trail": []}
    for junk in ({"kind": "nope"}, {"kind": "phase_note", "phase": "nope"},
                 "not-a-mapping", 17):
        driven = _drive(state, junk)
        assert driven["state"] == "collect"
        assert driven.get("trail") == []
