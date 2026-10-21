"""Unit tier: the hunter's pass-chain tracker (S4 14, S3 8.4) - the pure module.

The #164 fault lifecycle (`hypothesised -> verified -> dropped -> specified`
and its four list moves) is retired in T5 (#378): the pure state
module now owns the eight pass literals, the phase-summary note contract, the
signal extraction off the observed tool call, the signal-acceptance rule, and
the passive advance. This file pins those seams; the graph topology rides
`tests/attack/test_hunter_graph.py`, the harness wiring the integration tier.
"""
from __future__ import annotations

from polymerhus.attack.hunting import hunter_state as S


# --- the pass vocabulary (S4 14.6) --------------------------------------------


def test_the_eight_pass_literals_are_the_chain_order():
    """S4 14.6/S3 8.4: the eight pass literals, in the declared order."""
    assert S.PASS_SEQUENCE == (
        "grounding", "slice", "collect", "discriminate",
        "generate", "well_formedness", "verify_claims", "complete",
    )
    assert set(S.HunterPass.__args__) == set(S.PASS_SEQUENCE)


def test_the_spec_status_vocabulary_is_the_ratified_three():
    """S4 14.6/Q52a: exactly `{hypothesised, ratified, dropped}`; the retired
    `verified`/`specified` values are gone from the state vocabulary."""
    assert S.SPEC_STATUSES == ("hypothesised", "ratified", "dropped")
    assert set(S.SpecStatus.__args__) == {"hypothesised", "ratified", "dropped"}


def test_the_phase_note_contract_is_the_state_literal_name():
    """S4 14.8/Q51a: the kind is `phase_summary`; the name is `phase:<state>`."""
    assert S.PHASE_SUMMARY_KIND == "phase_summary"
    assert S.phase_note_name("grounding") == "phase:grounding"
    assert S.phase_note_name("well_formedness") == "phase:well_formedness"
    assert S.phase_note_name("verify_claims") == "phase:verify_claims"


# --- the signal extraction off the observed tool call (S4 14.9) ---------------


def _note(name, *, kind="phase_summary", action="append"):
    return {"command": "write", "action": action, "note_name": name,
            "kind": kind, "body": "the pass output"}


def test_a_phase_summary_note_maps_to_its_phase_signal():
    assert S.detect_phase_signal("notes", _note("phase:slice")) == (
        {"kind": "phase_note", "phase": "slice"})
    # a re-iteration rewrites the SAME note (update) - still the exit signal
    assert S.detect_phase_signal(
        "notes", _note("phase:slice", action="update")) == (
        {"kind": "phase_note", "phase": "slice"})


def test_a_note_that_is_not_a_phase_exit_maps_to_no_signal():
    # another kind, another name shape, a read, a non-phase name, a delete
    assert S.detect_phase_signal("notes", _note("decision", kind="freeform")) is None
    assert S.detect_phase_signal("notes", _note("slice")) is None
    assert S.detect_phase_signal(
        "notes", {**_note("phase:slice"), "command": "read"}) is None
    assert S.detect_phase_signal("notes", _note("phase:nope")) is None
    assert S.detect_phase_signal(
        "notes", _note("phase:slice", action="delete")) is None


def test_only_the_five_note_exits_are_phase_signals():
    """S4 14.6: exactly five passes exit on a note; GENERATE and VERIFY-CLAIMS
    exit on the `hunts_store` writes and COMPLETE is terminal, so a note named
    for them is not a signal (a note may never substitute the store write)."""
    for phase in ("generate", "verify_claims", "complete"):
        assert S.detect_phase_signal("notes", _note(f"phase:{phase}")) is None
        assert S.exit_signal_pass({"kind": "phase_note", "phase": phase}) is None
    for phase in ("grounding", "slice", "collect", "discriminate",
                  "well_formedness"):
        assert S.detect_phase_signal("notes", _note(f"phase:{phase}")) == (
            {"kind": "phase_note", "phase": phase})


def test_a_spec_set_write_maps_to_its_exit_signal():
    """F-025: the GENERATE exit is the first one-spec `hypothesised` write; the
    VERIFY-CLAIMS exit is the `finalize` call (S4 14.4). A single terminal
    status write does not close the set, so it carries no signal."""
    hypothesised = {"command": "write", "spec": {"status": "hypothesised"}}
    assert S.detect_phase_signal("hunts_store", hypothesised) == (
        {"kind": "spec_set_write", "statuses": ["hypothesised"]})
    assert S.detect_phase_signal(
        "hunts_store", {"command": "write", "spec": {"status": "ratified"}}) is None
    assert S.detect_phase_signal(
        "hunts_store", {"command": "write", "spec": {"status": "dropped"}}) is None
    assert S.detect_phase_signal("hunts_store", {"command": "finalize"}) == (
        {"kind": "spec_set_finalize"})


def test_a_partial_or_unshaped_spec_write_maps_to_no_signal():
    """A call the detector cannot classify (statusless, empty, or a read) is no
    signal: the machine records only what the model signalled."""
    assert S.detect_phase_signal("hunts_store", {"command": "write", "spec": []}) is None
    assert S.detect_phase_signal("hunts_store", {"command": "write", "spec": {}}) is None
    assert S.detect_phase_signal(
        "hunts_store", {"command": "write", "spec": {"status": "bogus"}}) is None
    assert S.detect_phase_signal("hunts_store", {"command": "read"}) is None


def test_a_kb_query_maps_to_the_rider_signal_and_anything_else_to_none():
    """The `kb_query` signal never advances the state (S4 14.9): it rides the
    grounding retrieval-gap rider."""
    assert S.detect_phase_signal("kb_query", {"scenario_id": "s"}) == {"kind": "kb_query"}
    assert S.detect_phase_signal("exec", {"command": "curl"}) is None
    assert S.detect_phase_signal("notes", None) is None
    assert S.detect_phase_signal("notes", "not-a-mapping") is None


# --- the signal-acceptance rule (S4 14.5, Q50a) -------------------------------


def _note_signal(phase):
    return {"kind": "phase_note", "phase": phase}


def _set_signal(*statuses):
    return {"kind": "spec_set_write", "statuses": list(statuses)}


def _finalize_signal():
    return {"kind": "spec_set_finalize"}


def test_the_expected_exit_advances_to_the_next_pass():
    assert S.detect_signal({"state": "grounding"}, _note_signal("grounding")) == (
        {"kind": "advance", "target": "slice"})
    assert S.detect_signal({"state": "collect"}, _note_signal("collect")) == (
        {"kind": "advance", "target": "discriminate"})
    # the GENERATE exit is the first one-spec hypothesised write; the
    # VERIFY-CLAIMS exit is the finalize call
    assert S.detect_signal({"state": "generate"}, _set_signal("hypothesised")) == (
        {"kind": "advance", "target": "well_formedness"})
    assert S.detect_signal({"state": "verify_claims"},
                           _finalize_signal()) == (
        {"kind": "advance", "target": "complete"})
    # a single terminal status write does not close the set
    assert S.detect_signal({"state": "verify_claims"},
                           _set_signal("ratified")) == {"kind": "none"}


def test_a_later_signals_forward_jump_records_the_skipped_passes():
    """A skipped note must never wedge the tracker (S3 8.4): a later pass's
    signal advances as a reality-restoring forward jump and the skipped passes
    ride the trail."""
    assert S.detect_signal({"state": "grounding"}, _set_signal("hypothesised")) == (
        {"kind": "forward_jump", "target": "well_formedness",
         "skipped": ["slice", "collect", "discriminate", "generate"]})
    assert S.detect_signal({"state": "slice"},
                           _note_signal("discriminate")) == (
        {"kind": "forward_jump", "target": "generate",
         "skipped": ["collect", "discriminate"]})
    assert S.detect_signal({"state": "collect"},
                           _finalize_signal()) == (
        {"kind": "forward_jump", "target": "complete",
         "skipped": ["discriminate", "generate", "well_formedness",
                     "verify_claims"]})


def test_an_earlier_signal_stays_trail_only():
    """An inner-loop re-entry appends to the trail as `reentry` and never moves
    the state back (S4 14.5)."""
    assert S.detect_signal({"state": "verify_claims"},
                           _note_signal("grounding")) == (
        {"kind": "trail_only", "reason": "reentry"})
    assert S.detect_signal({"state": "complete"},
                           _finalize_signal()) == (
        {"kind": "trail_only", "reason": "reentry"})


def test_no_signal_stays():
    """A kb_query never advances (S4 14.9); an absent signal and a missing
    state channel both stay."""
    assert S.detect_signal({"state": "grounding"}, {"kind": "kb_query"}) == (
        {"kind": "none"})
    assert S.detect_signal({"state": "grounding"}, None) == {"kind": "none"}
    # the chain opens ungrounded: an absent state channel is `grounding`
    assert S.detect_signal({}, _note_signal("grounding")) == (
        {"kind": "advance", "target": "slice"})


# --- the passive advance (S4 14.5) --------------------------------------------


def test_advance_moves_the_state_injects_the_exited_hint_and_records_the_trail():
    state = {"state": "grounding", "specs": [], "trail": []}
    signal = _note_signal("grounding")
    new_state, hint, entry = S.advance_state(
        state, S.detect_signal(state, signal), signal)
    # the state moves, nothing else does (the specs channel is last-write and
    # the input is never mutated)
    assert new_state["state"] == "slice"
    assert new_state["specs"] == []
    assert state["state"] == "grounding"
    # the hint is the exited pass's constant
    assert hint == S.GROUNDING_HINT
    # the trail entry records the signal, the outcome, and the state move
    assert entry == {
        "signal": {"kind": "phase_note", "phase": "grounding"},
        "outcome": "advance",
        "from": "grounding",
        "to": "slice",
    }


def test_advance_on_a_forward_jump_hints_the_signalling_pass_and_records_skips():
    state = {"state": "grounding", "specs": [{"spec_id": "s1"}], "trail": []}
    signal = _set_signal("hypothesised")
    new_state, hint, entry = S.advance_state(
        state, S.detect_signal(state, signal), signal)
    # the jump lands on the signalling pass's successor, the specs channel rides
    # through untouched, and the hint is the SIGNALLING (exited) pass's constant
    assert new_state["state"] == "well_formedness"
    assert new_state["specs"] == [{"spec_id": "s1"}]
    assert hint == S.GENERATE_HINT
    assert entry["outcome"] == "forward_jump"
    assert entry["skipped"] == ["slice", "collect", "discriminate", "generate"]


def test_an_earlier_signal_advances_nothing_and_only_trails():
    state = {"state": "collect", "specs": [], "trail": []}
    signal = _note_signal("grounding")
    new_state, hint, entry = S.advance_state(
        state, S.detect_signal(state, signal), signal)
    assert new_state["state"] == "collect"      # never moves the state back
    assert hint is None
    assert entry == {
        "signal": {"kind": "phase_note", "phase": "grounding"},
        "outcome": "trail_only",
        "from": "collect",
        "to": "collect",
    }


def test_no_signal_advances_nothing_and_appends_nothing():
    state = {"state": "slice", "specs": [], "trail": []}
    new_state, hint, entry = S.advance_state(
        state, S.detect_signal(state, {"kind": "kb_query"}), {"kind": "kb_query"})
    assert new_state["state"] == "slice"
    assert hint is None
    assert entry is None


def test_the_state_move_is_monotonic_over_any_signal_sequence():
    """S4 14.12: no outcome ever names an earlier pass as its target, whatever
    the order the signals arrive in - the state axis only moves forward."""
    state: dict = {"state": "grounding", "specs": [], "trail": []}
    signals = [
        _note_signal("grounding"), _note_signal("slice"), _note_signal("collect"),
        _note_signal("grounding"), _note_signal("slice"), _note_signal("collect"),
        _note_signal("discriminate"), _set_signal("hypothesised"),
        _note_signal("discriminate"), _note_signal("well_formedness"),
        _finalize_signal(),
    ]
    seen = [state["state"]]
    for signal in signals:
        outcome = S.detect_signal(state, signal)
        state, _, _ = S.advance_state(state, outcome, signal)
        seen.append(state["state"])
    assert seen == [
        "grounding", "slice", "collect", "discriminate", "discriminate",
        "discriminate", "discriminate", "generate", "well_formedness",
        "well_formedness", "verify_claims", "complete",
    ]


# --- the seven hints and the grounding rider (S4 14.7) -------------------------


def test_the_seven_transition_hints_are_the_ratified_literals():
    """S4 14.7 (Q46a plus the grounding exit): one hint per transition gate,
    keyed by the EXITED pass - the literals come from the spec table, so the
    test can disagree with the code."""
    assert S.TRANSITION_HINTS == {
        "grounding": (
            "The grounding summary is persisted. Define the failure-mode slice "
            "the loop opens."
        ),
        "slice": (
            "Write the slice note, then collect the discrimination-axis instances."
        ),
        "collect": (
            "Close the collection with the instances note, then discriminate."
        ),
        "discriminate": (
            "Persist the discrimination outcome, then generate the spec set."
        ),
        "generate": (
            "The first spec is persisted as `hypothesised`. This is one spec, "
            "not the closed set: continue writing every remaining spec, one "
            "`spec` per call, then run the well-formedness check over the "
            "slice; the check absorbs the class-exhaustiveness question in "
            "its new form."
        ),
        "well_formedness": (
            "Well-formedness is confirmed. Record the drops and merges, then "
            "verify the claims."
        ),
        "verify_claims": (
            "The spec set is finalized. The hunt is complete; the pod dispatch "
            "and its verdict belong to the harness."
        ),
    }
    # `complete` is terminal: it has no exit and no hint
    assert "complete" not in S.TRANSITION_HINTS


def test_the_grounding_kb_rider_is_re_worded_for_the_new_chain():
    """S4 14.7/Q53: the grounding retrieval-gap rider is separate from the
    transition table and points at SLICE, never the retired DECOMPOSE."""
    assert S.GROUNDING_KB_HINT == (
        "The kb_query retrieval is folded in. Did it close the gap that "
        "triggered it? Yes -> proceed to SLICE; no -> record the residual "
        "uncertainty and proceed on weaker grounding."
    )
    assert S.GROUNDING_KB_HINT not in S.TRANSITION_HINTS.values()


# --- the retired surface (S4 14.11) -------------------------------------------


def test_the_retired_fault_lifecycle_is_gone_from_the_state_module():
    """S4 14.11: the fault lifecycle, its lists, its detector/push, its phase
    flag, and the old hint constants are removed - no dead surface remains."""
    for gone in (
        "FaultStatus", "FAULT_STATUSES", "FaultItem", "HuntPhase",
        "TransitionName", "detect_transition", "push_transition",
        "hypothesised_faults", "verified_faults", "dropped_faults",
        "ratified_specs", "current_fault", "phase",
        "D2_HINT", "D3_HINT", "COMMIT_SPECIFICATION_HINT", "NEXT_FAULT_HINT",
        "NEXT_ITERATION_HINT",
    ):
        assert not hasattr(S, gone), f"{gone} is retired (S4 14.11)"
