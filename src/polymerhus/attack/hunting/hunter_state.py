"""The hunter's pass-chain tracker (#164, S4 14): the pure state-machine module.

The single source of truth for the state-graph hunter's state tracking: the
eight-pass chain (S4 14.2, S3 8.4), the phase-summary note contract, the signal
extraction off the observed tool call, the signal-acceptance rule, and the
passive advance. The pre-#164 fault lifecycle (`{hypothesised, verified,
dropped, specified}` and its four semantic lists) is retired: the redesigned
hunter runs a pass sequence over one loop and its phases mostly end without a
status-bearing store write, so the tracker advances on the most accurate
available proxy signal per pass (S4 14.4).

The pass chain is:

```
GROUNDING -> SLICE -> COLLECT -> DISCRIMINATE -> GENERATE
  -> WELL_FORMEDNESS -> VERIFY-CLAIMS -> COMPLETE
```

This module is PURE by construction (R4, GP8c): it imports no driver, performs
no I/O at import, and holds no side effects (CODING_STANDARD section 6). The
state machine is PASSIVE: the harness reads the signal off the model's tool
call (`detect_phase_signal`), the pure acceptance rule decides what the signal
does (`detect_signal`), and `advance_state` moves the state, injects the exited
pass's constant, and records the trail. It NEVER gates a tool call on the
current state and never rejects a signal: the graph records what the model
signalled (the no-block invariant). The state axis is monotonic - a later
pass's signal forward-jumps, an earlier one only trails. The deterministic
surface is exactly the state machine (the state move plus the injected
transition constants) and the channel shapes.
"""
from __future__ import annotations

import logging
import operator
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict, cast

logger = logging.getLogger(__name__)

# --- the pass chain (S4 14.2/14.6) -------------------------------------------

HunterPass = Literal[
    "grounding",
    "slice",
    "collect",
    "discriminate",
    "generate",
    "well_formedness",
    "verify_claims",
    "complete",
]
"""The eight hunter passes (S4 14.6): the tracked state's literals."""

PASS_SEQUENCE: tuple[HunterPass, ...] = (
    "grounding",
    "slice",
    "collect",
    "discriminate",
    "generate",
    "well_formedness",
    "verify_claims",
    "complete",
)
"""The pass chain in canonical order: the monotonic state axis.

`START -> GROUNDING` is implicit (S4 14.4) - the hunt begins ungrounded - and
`complete` is terminal: it has no exit signal and no successor."""

COMPLETE: HunterPass = "complete"
"""The terminal pass: the graph reaches END only here (S4 14.10)."""

SpecStatus = Literal["hypothesised", "ratified", "dropped"]
"""The spec-set lifecycle verbatim (S4 14.6, Q52a).

Exactly `{hypothesised, ratified, dropped}`: `hypothesised` is the GENERATE
draft, `ratified` the surviving spec at the terminal write, `dropped` the
declassed unfeasible spec. The retired `verified` and `specified` values belong
to no live state surface."""

SPEC_STATUSES: tuple[SpecStatus, ...] = ("hypothesised", "ratified", "dropped")
"""The three spec statuses in canonical order."""

PHASE_SUMMARY_KIND = "phase_summary"
"""The interposed phase-exit note kind (S4 14.8, Q51a).

The hunter's `notes` kind, and the hunter's alone: the hunt-store and pod note
enums do not gain it and the modeller's `notes` tool refuses it. It is episodic
memory, not authoritative state - the spec store writes stay authoritative for
the spec set."""

PHASE_NOTE_PREFIX = "phase:"
"""The phase-summary note-name prefix: the note name is `phase:<state>`."""

NOTE_EXIT_PASSES: tuple[HunterPass, ...] = (
    "grounding",
    "slice",
    "collect",
    "discriminate",
    "well_formedness",
)
"""The five passes whose declared exit signal is a phase-summary note (S4 14.4).

GENERATE exits on the first one-spec `hypothesised` write, VERIFY-CLAIMS exits
on `hunts_store` `finalize`, and COMPLETE is terminal, so those three carry no
note exit: a `phase_summary` note named for them is not a signal, and a note
can never substitute the authoritative store write (S4 14.8: "the spec store
writes remain authoritative for the spec set")."""


def phase_note_name(state: HunterPass) -> str:
    """The phase-summary note name for `state` (S4 14.6): `phase:<state>`.

    The name carries the state literal verbatim (`phase:well_formedness`), so
    the note and the tracked state can never drift under a rename."""
    return f"{PHASE_NOTE_PREFIX}{state}"


# --- the channels (S4 14.9) ---------------------------------------------------


class SpecItem(TypedDict):
    """One spec of the set the hunter tracks (S4 14.9).

    `spec_id` is the derived identity (the file-name stem
    `<class>__<value>__<value>`), `discriminators` the ordered `{axis, value}`
    instances the hunter separated the slot on, `spec_ref` its authored file,
    and `verification_symptoms` the concrete observable failure modes the pod
    probes. The channel is last-write and carries the WHOLE set."""

    spec_id: str
    status: SpecStatus
    discriminators: list[dict]
    spec_ref: str
    verification_symptoms: list[str]
    summary: str


class HuntState(TypedDict, total=False):
    """The tracker's channels (S4 14.9).

    Every channel is last-write EXCEPT `trail` (the `operator.add` trajectory
    record: append-only, replay only, never authoritative). There is
    deliberately NO `messages` channel: the ReAct turns own their message
    history in the per-hunt session checkpointer. The transient drive inputs
    (`observed_signal`) and the read-only driver assemblies are not part of
    this pure vocabulary; the compiled graph rides them."""

    state: HunterPass
    specs: list[SpecItem]
    injected_constant: str | None
    trail: Annotated[list[dict], operator.add]


# --- the transient signals (S4 14.9) -----------------------------------------


class PhaseNoteSignal(TypedDict):
    """A `phase_summary` note write whose name is `phase:<phase>`."""

    kind: Literal["phase_note"]
    phase: HunterPass


class SpecSetWriteSignal(TypedDict):
    """A one-spec `hunts_store` write carrying a hypothesised draft."""

    kind: Literal["spec_set_write"]
    statuses: list[SpecStatus]


class SpecSetFinalizeSignal(TypedDict):
    """A `hunts_store` finalize call closing the whole spec set."""

    kind: Literal["spec_set_finalize"]


class KbQuerySignal(TypedDict):
    """A `kb_query` call: the grounding retrieval-gap rider's carrier."""

    kind: Literal["kb_query"]


PhaseSignal = (
    PhaseNoteSignal | SpecSetWriteSignal | SpecSetFinalizeSignal | KbQuerySignal
)
"""The transient drive inputs the harness observes off one tool call.

The signal carries only the observed statuses, never a spec body: the machine
records what the model signalled and never reaches into the payload."""


# --- the signal detector (S4 14.9) --------------------------------------------


def _phase_note_signal(args: Mapping[str, Any]) -> PhaseSignal | None:
    """The exit signal of a `notes` write: the interposed phase-summary note.

    The write option is `action` (`append` / `update`), never `command` (#209):
    a re-iteration rewrites the same note with `update`, so both write actions
    are the exit. A read, a delete, another kind, or a name outside
    `phase:<state>` carries no signal."""
    if args.get("command") != "write" or args.get("action") == "delete":
        return None
    if args.get("kind") != PHASE_SUMMARY_KIND:
        return None
    name = args.get("note_name")
    if not isinstance(name, str) or not name.startswith(PHASE_NOTE_PREFIX):
        return None
    phase = name[len(PHASE_NOTE_PREFIX):]
    if phase not in NOTE_EXIT_PASSES:
        return None
    return {"kind": "phase_note", "phase": cast(HunterPass, phase)}


def _spec_set_signal(args: Mapping[str, Any]) -> PhaseSignal | None:
    """The exit signal of one `hunts_store` call (F-025).

    A one-spec `write` carrying a `hypothesised` draft is the GENERATE exit:
    it is the first persisted draft, and the hunter continues writing the
    remaining drafts in the next pass. A terminal one-spec write
    (`ratified`/`dropped`) is NOT the VERIFY-CLAIMS exit - the set is not
    closed until `finalize`, whose call is the one whole-set exit (S4 14.4).
    A statusless or malformed `spec` is no signal - the machine records only
    what the model signalled and never reads the spec bodies to guess."""
    command = args.get("command")
    if command == "finalize":
        return {"kind": "spec_set_finalize"}
    if command != "write":
        return None
    spec = args.get("spec")
    if not isinstance(spec, Mapping):
        return None
    status = spec.get("status")
    if status not in SPEC_STATUSES:
        return None
    if status == "hypothesised":
        return {"kind": "spec_set_write", "statuses": ["hypothesised"]}
    return None


def detect_phase_signal(tool_name: str, args: Any) -> PhaseSignal | None:
    """Map one observed tool call to its `PhaseSignal`, or None (S4 14.9).

    A pure function of the observed call verbatim (tool name + args): the
    harness reads it off the model's REAL tool call before the tool runs, so
    the machine observes what the model signalled and is never gated by the
    tool's acceptance (the no-block invariant). Never raises: garbage maps to
    None (no signal, no state move)."""
    if not isinstance(args, Mapping):
        return None
    try:
        if tool_name == "notes":
            return _phase_note_signal(args)
        if tool_name == "hunts_store":
            return _spec_set_signal(args)
        if tool_name == "kb_query":
            return {"kind": "kb_query"}
    except Exception:  # noqa: BLE001 - detection never breaks the turn
        logger.warning("hunter signal detection degraded on %r", tool_name)
    return None


# --- the signal-acceptance rule and the advance (S4 14.5) ---------------------


class AdvanceOutcome(TypedDict):
    """The expected exit fired: move to the successor pass."""

    kind: Literal["advance"]
    target: HunterPass


class ForwardJumpOutcome(TypedDict):
    """A later pass's signal: a reality-restoring forward jump (S4 14.5)."""

    kind: Literal["forward_jump"]
    target: HunterPass
    skipped: list[HunterPass]


class TrailOnlyOutcome(TypedDict):
    """An earlier pass's signal: trail material, never a state move."""

    kind: Literal["trail_only"]
    reason: str


class NoSignalOutcome(TypedDict):
    """No signal belongs to this drive: append nothing and stay."""

    kind: Literal["none"]


SignalOutcome = (
    AdvanceOutcome | ForwardJumpOutcome | TrailOnlyOutcome | NoSignalOutcome
)
"""What one observed signal does to the tracker (S4 14.5)."""


def next_pass(state: HunterPass) -> HunterPass:
    """The successor of `state` in the chain; `complete` is terminal."""
    index = PASS_SEQUENCE.index(state)
    return PASS_SEQUENCE[min(index + 1, len(PASS_SEQUENCE) - 1)]


def exit_signal_pass(signal: PhaseSignal | None) -> HunterPass | None:
    """The pass whose declared exit signal this is, or None (S4 14.4).

    A phase note is the named pass's exit; a one-spec `hypothesised` write is
    the GENERATE exit and a `finalize` call is the VERIFY-CLAIMS one (the set
    is closed there, not on any single terminal status write); a `kb_query` is
    never an exit (it carries the grounding rider only). A malformed signal is
    no signal (the tracker never raises)."""
    if not isinstance(signal, Mapping):
        return None
    kind = signal.get("kind")
    if kind == "phase_note":
        phase = signal.get("phase")
        return phase if phase in NOTE_EXIT_PASSES else None
    if kind == "spec_set_finalize":
        return "verify_claims"
    if kind == "spec_set_write":
        statuses = signal.get("statuses") or []
        if not statuses or any(st not in SPEC_STATUSES for st in statuses):
            return None
        if all(status == "hypothesised" for status in statuses):
            return "generate"
    return None


def detect_signal(state: HuntState, signal: PhaseSignal | None) -> SignalOutcome:
    """The acceptance rule (S4 14.5, Q50a): expected, forward, backward, none.

    The machine advances only on the pass's own declared exit signal; a later
    pass's signal still advances (a reality-restoring forward jump that records
    the skipped passes); an earlier pass's signal appends to the trail as a
    re-entry and never moves the state back. The state is monotonic by
    construction: no outcome ever names an earlier pass as its target. Never
    raises: an unreadable state or signal stays (a no-signal outcome)."""
    current = state.get("state") or "grounding"
    owning = exit_signal_pass(signal)
    if owning is None:
        return {"kind": "none"}
    try:
        current_index = PASS_SEQUENCE.index(current)
        owning_index = PASS_SEQUENCE.index(owning)
    except ValueError:  # noqa: PERF203 - an unknown literal stays put, loudly
        logger.warning("hunter tracker: unknown pass literal in %r / %r", current, owning)
        return {"kind": "none"}
    if owning_index == current_index:
        return {"kind": "advance", "target": next_pass(owning)}
    if owning_index > current_index:
        return {
            "kind": "forward_jump",
            "target": next_pass(owning),
            "skipped": list(PASS_SEQUENCE[current_index + 1:owning_index + 1]),
        }
    return {"kind": "trail_only", "reason": "reentry"}


# --- the injection constants (S4 14.7) ----------------------------------------

GROUNDING_HINT = (
    "The grounding summary is persisted. Define the failure-mode slice the "
    "loop opens."
)
"""Injected when the grounding exit fires: define the slice."""

SLICE_HINT = (
    "Write the slice note, then collect the discrimination-axis instances."
)
"""Injected when the slice exit fires: collect the instances."""

COLLECT_HINT = "Close the collection with the instances note, then discriminate."
"""Injected when the collection exit fires: discriminate."""

DISCRIMINATE_HINT = "Persist the discrimination outcome, then generate the spec set."
"""Injected when the discrimination exit fires: generate the set."""

GENERATE_HINT = (
    "The first spec is persisted as `hypothesised`. This is one spec, not the "
    "closed set: continue writing every remaining spec, one `spec` per call, "
    "then run the well-formedness check over the slice; the check absorbs the "
    "class-exhaustiveness question in its new form."
)
"""Injected when the first hypothesised one-spec write fires: keep drafting."""

WELL_FORMEDNESS_HINT = (
    "Well-formedness is confirmed. Record the drops and merges, then verify "
    "the claims."
)
"""Injected when the well-formedness note fires: verify the claims."""

VERIFY_CLAIMS_HINT = (
    "The spec set is finalized. The hunt is complete; the pod dispatch and "
    "its verdict belong to the harness."
)
"""Injected when the finalize call fires: the set is closed."""

TRANSITION_HINTS: dict[HunterPass, str] = {
    "grounding": GROUNDING_HINT,
    "slice": SLICE_HINT,
    "collect": COLLECT_HINT,
    "discriminate": DISCRIMINATE_HINT,
    "generate": GENERATE_HINT,
    "well_formedness": WELL_FORMEDNESS_HINT,
    "verify_claims": VERIFY_CLAIMS_HINT,
}
"""The single-sourced hint per transition gate, keyed by the EXITED pass.

The hint is injected in the signal's tool response - a constant, never the
system prompt (S4 14.7). `complete` is terminal: it exits nothing and carries
no hint."""

GROUNDING_KB_HINT = (
    "The kb_query retrieval is folded in. Did it close the gap that triggered "
    "it? Yes -> proceed to SLICE; no -> record the residual uncertainty and "
    "proceed on weaker grounding."
)
"""The grounding retrieval-gap rider (S4 14.7/Q53).

Separate from `TRANSITION_HINTS`: it rides a `kb_query` call while the state
is `GROUNDING` and is never a transition - the grounding exit remains the
phase-summary note. It replaces the retired `D3_HINT`."""


# --- the passive advance (S4 14.5) --------------------------------------------


def trail_entry(
    signal: PhaseSignal | None,
    outcome: AdvanceOutcome | ForwardJumpOutcome | TrailOnlyOutcome,
    previous: HunterPass,
    moved: HunterPass,
) -> dict:
    """The trajectory record for one observed signal (S4 14.5).

    It records the signal, the outcome, and the state move; a forward jump
    additionally records the skipped passes. The trail is append-only and
    replay-only - never authoritative state."""
    entry = {
        "signal": signal,
        "outcome": outcome["kind"],
        "from": previous,
        "to": moved,
    }
    if outcome["kind"] == "forward_jump":
        entry["skipped"] = list(outcome["skipped"])
    return entry


def advance_state(
    state: HuntState,
    outcome: SignalOutcome,
    signal: PhaseSignal | None = None,
) -> tuple[HuntState, str | None, dict | None]:
    """Return the NEW state, the injected hint, and the trail entry (S4 14.5).

    The passive mover: an advance or forward jump moves the `state` channel to
    the outcome's target and injects the exited pass's constant; a trail-only
    outcome (an earlier pass's signal) only appends its entry and never moves
    the state; a no-signal outcome returns the state unchanged with no hint and
    no entry. The `specs` channel rides through untouched (last-write). Nothing
    here is ever gated: the machine records what the model signalled and never
    rejects a transition. `signal` feeds the trail entry's signal slot; a
    caller that omits it still gets the state move and the hint (the exited
    pass then reads off the current state)."""
    previous = state.get("state") or "grounding"
    new_state = dict(state)
    new_state["state"] = previous
    kind = outcome.get("kind") if outcome else "none"
    if kind in ("advance", "forward_jump"):
        moved = outcome["target"]
        new_state["state"] = moved
        exited = exit_signal_pass(signal) or previous
        return (
            new_state,
            TRANSITION_HINTS.get(exited),
            trail_entry(signal, outcome, previous, moved),
        )
    if kind == "trail_only":
        return new_state, None, trail_entry(signal, outcome, previous, previous)
    return new_state, None, None


__all__ = [
    "HunterPass",
    "PASS_SEQUENCE",
    "COMPLETE",
    "SpecStatus",
    "SPEC_STATUSES",
    "PHASE_SUMMARY_KIND",
    "PHASE_NOTE_PREFIX",
    "NOTE_EXIT_PASSES",
    "phase_note_name",
    "SpecItem",
    "HuntState",
    "PhaseSignal",
    "PhaseNoteSignal",
    "SpecSetWriteSignal",
    "SpecSetFinalizeSignal",
    "KbQuerySignal",
    "detect_phase_signal",
    "SignalOutcome",
    "AdvanceOutcome",
    "ForwardJumpOutcome",
    "TrailOnlyOutcome",
    "NoSignalOutcome",
    "next_pass",
    "exit_signal_pass",
    "detect_signal",
    "GROUNDING_HINT",
    "SLICE_HINT",
    "COLLECT_HINT",
    "DISCRIMINATE_HINT",
    "GENERATE_HINT",
    "WELL_FORMEDNESS_HINT",
    "VERIFY_CLAIMS_HINT",
    "TRANSITION_HINTS",
    "GROUNDING_KB_HINT",
    "trail_entry",
    "advance_state",
]
