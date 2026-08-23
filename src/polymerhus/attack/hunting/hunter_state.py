"""The hunter's state vocabulary (#164): the pure state-machine module.

The single source of truth for the state-graph hunter's state tracking (GP4,
spec 2.3): the authoritative fault lifecycle, the `HuntState` channels, the
item shapes, and the passive detect/push transition logic. The model's
verbatim `{hypothesised, verified, dropped, specified}` is authoritative and
replaces in full the SKILL.md working-set `{open, dispatched, closed, dropped,
confirmed}`.

This module is PURE by construction (R4, GP8c): it imports no driver,
performs no I/O at import, and holds no side effects (CODING_STANDARD section
6). The state machine is PASSIVE - the harness observes the model's tool
calls, `detect_transition` maps a status verbatim to a transition name, and
`push_transition` moves the fault between the semantic lists. It NEVER gates
a tool call on the current state and never rejects an illegal transition:
the graph records what the model signalled (the no-block invariant). The
deterministic surface is exactly the state machine (the list moves plus the
injected phase-transition constants) and the item shapes (spec 2.4);
`derive_verdict`, the record appends, and the terminal assembly live
elsewhere.
"""
from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

# --- the lifecycle verbatim (GP4, spec 2.3) ----------------------------------

FaultStatus = Literal["hypothesised", "verified", "dropped", "specified"]
"""The authoritative fault lifecycle verbatim (GP4, spec 2.3).

The model's verbatim `{hypothesised, verified, dropped, specified}` is
authoritative and replaces in full the SKILL.md working-set `{open,
dispatched, closed, dropped, confirmed}`."""

FAULT_STATUSES: tuple[FaultStatus, ...] = (
    "hypothesised",
    "verified",
    "dropped",
    "specified",
)
"""The four lifecycle statuses in canonical order."""

HuntPhase = Literal["grounding", "hypothesised", "evaluating", "concluded"]
"""The outer hunt phase flag (spec 3): last-write on `HuntState.phase`."""

TransitionName = Literal["hypothesise", "verify", "drop", "specify", "none"]
"""The transition names the detector maps a status verbatim to."""

# --- the item shapes (spec 3) ------------------------------------------------

_FAULT_FIELDS = ("fault_id", "mechanism", "supports", "conflicts", "test", "status")
"""The fault-draft fields, used to separate the fault content from the
spec-fields when a `specified` write carries both."""


class FaultItem(TypedDict):
    """The fault-draft content (spec 3): one candidate hypothesis slot.

    `supports` / `conflicts` are the evidence grounding that backs or argues
    against the mechanism; `test` is the minimal discriminating experiment."""

    fault_id: str
    mechanism: str
    supports: list[str]
    conflicts: list[str]
    test: str
    status: FaultStatus


class SpecItem(TypedDict):
    """The ratified spec (spec 3): the completed, commit-specification spec.

    `spec_ref` links the produced spec file and `experiment_ref` the pod
    result (spec 6), both other stores."""

    spec_id: str
    fault_key: str
    fault: FaultItem
    strategy: str
    status: FaultStatus
    spec_ref: str
    experiment_ref: str


class HuntState(TypedDict, total=False):
    """The graph's channels (spec 3).

    Every channel is last-write EXCEPT `trail` (the `operator.add` trajectory
    record, replay only, never authoritative). There is deliberately NO
    `messages` channel: the ReAct turns own their message history in the
    per-hunt session checkpointer. The read-only `config` / `tools` driver
    assemblies (spec 3) are not part of this pure vocabulary; they ride the
    compiled graph when the driver wires it."""

    phase: HuntPhase
    hypothesised_faults: list[FaultItem]
    verified_faults: list[FaultItem]
    dropped_faults: list[FaultItem]
    ratified_specs: list[SpecItem]
    current_fault: FaultItem | None
    injected_constant: str | None
    trail: Annotated[list[dict], operator.add]


# --- the detect/push transition logic (R4, GP8c) ------------------------------

_STATUS_TO_TRANSITION: dict[str, TransitionName] = {
    "hypothesised": "hypothesise",
    "verified": "verify",
    "dropped": "drop",
    "specified": "specify",
}


def detect_transition(
    state: HuntState,
    observed_status: str | None,
) -> TransitionName:
    """Map a status verbatim observed on a tool-call write to a transition name.

    A lifecycle status maps to its transition; any other observation - an
    append, a read, another tool call, an absent status - maps to "none" (no
    state move). The detector is a pure function of the observed status
    verbatim: it never consults the current state, because the GP8c passive
    machine never gates a transition on the state. The `state` argument is
    accepted for signature symmetry with `push_transition` and as the slot an
    active enforcement pass (deferred under GP8c) would read."""
    if observed_status is None:
        return "none"
    return _STATUS_TO_TRANSITION.get(observed_status, "none")


def _upsert_by_id(entries: list[dict], item: dict, key: str) -> list[dict]:
    """Return a NEW list with `item` upserted by `key`.

    Re-authoring the same identity replaces the existing entry in place (the
    G5 re-author discipline mirrored on the state lists) instead of
    duplicating it; a new identity appends."""
    out = list(entries)
    marker = item.get(key)
    for i, entry in enumerate(out):
        if entry.get(key) == marker:
            out[i] = item
            return out
    out.append(item)
    return out


def _move(
    state: HuntState,
    source_keys: tuple[str, ...],
    target_key: str,
    item: FaultItem,
) -> HuntState:
    """Move the fault (by `fault_id`) from the source lists to the target list.

    Returns a NEW state, never mutating the input. The moved entry carries
    the existing source content merged with the observed write payload. Never
    rejects (the no-block invariant): when the fault is not found in any
    source list it is still recorded on the target list - the machine records
    what the model signalled."""
    new_state = dict(state)
    sources = {key: list(state.get(key) or []) for key in source_keys}
    existing: FaultItem | None = None
    for key in source_keys:
        for entry in sources[key]:
            if entry.get("fault_id") == item.get("fault_id"):
                existing = entry
                break
        if existing is not None:
            break
    moved = dict(item)
    if existing is not None:
        moved = {**existing, **dict(item)}
    for key in source_keys:
        new_state[key] = [
            entry for entry in sources[key] if entry.get("fault_id") != item.get("fault_id")
        ]
    new_state[target_key] = _upsert_by_id(
        list(state.get(target_key) or []), moved, "fault_id",
    )
    return new_state


def _with_specified(state: HuntState, item: FaultItem) -> HuntState:
    """Move the fault (by `fault_id`) to `ratified_specs` as a `SpecItem`.

    Returns a NEW state, never mutating the input. The `spec_id` rides the
    observed write (the model authors the spec, GP2(c)); when the write
    carries none it falls back to the `fault_id` so the passive machine still
    records the signal. Never rejects (the no-block invariant): a `specified`
    verbatim is pushed even when the fault is not in `verified_faults`."""
    new_state = dict(state)
    verified = list(state.get("verified_faults") or [])
    fault_id = item.get("fault_id")
    existing = next(
        (entry for entry in verified if entry.get("fault_id") == fault_id),
        None,
    )
    payload = dict(item)
    fault_content = dict(existing or {})
    fault_content.update({k: v for k, v in payload.items() if k in _FAULT_FIELDS})
    fault_item: FaultItem = {**fault_content, "status": "specified"}
    spec_item: SpecItem = {
        "spec_id": str(payload.get("spec_id") or fault_id or ""),
        "fault_key": str(payload.get("fault_key") or ""),
        "fault": fault_item,
        "strategy": str(payload.get("strategy") or ""),
        "status": "specified",
        "spec_ref": str(payload.get("spec_ref") or ""),
        "experiment_ref": str(payload.get("experiment_ref") or ""),
    }
    new_state["verified_faults"] = [
        entry for entry in verified if entry.get("fault_id") != fault_id
    ]
    new_state["ratified_specs"] = _upsert_by_id(
        list(state.get("ratified_specs") or []), spec_item, "spec_id",
    )
    return new_state


def push_transition(
    state: HuntState,
    transition: TransitionName,
    fault: FaultItem,
) -> HuntState:
    """Return the NEW state with the lists moved (never mutate in place).

    The passive list mover (R4, GP8c): hypothesise appends to
    `hypothesised_faults`; verify moves from `hypothesised_faults` to
    `verified_faults`; drop moves from any fault list to `dropped_faults`
    (legal at any stage, incl. mid-specification); specify moves from
    `verified_faults` to `ratified_specs` as a `SpecItem` carrying a
    `spec_id`. A transition is NEVER gated on the current state: the machine
    records what the model signalled and never rejects (a `specified` verbatim
    is pushed even when the fault is not in `verified_faults`). "none" (and
    any unrecognised transition) returns an unchanged copy of the state."""
    if transition == "hypothesise":
        new_state = dict(state)
        new_state["hypothesised_faults"] = _upsert_by_id(
            list(state.get("hypothesised_faults") or []), dict(fault), "fault_id",
        )
        return new_state
    if transition == "verify":
        return _move(state, ("hypothesised_faults",), "verified_faults", fault)
    if transition == "drop":
        return _move(
            state, ("hypothesised_faults", "verified_faults"), "dropped_faults", fault,
        )
    if transition == "specify":
        return _with_specified(state, fault)
    return dict(state)


# --- the phase-transition constants (G9, spec 2.3) ----------------------------

D2_HINT = (
    "The hypothesised faults are persisted in write-time rank order. "
    "Critically evaluate the D2 coverage criterion - is the candidate set "
    "exhaustive over the specific faults of this class likely to apply to "
    "this system? - or address the first hypothesised fault: articulate its "
    "testable mechanism and its minimal discriminating experiment."
)
"""The injected hint after `hypothesised` (the D2 hint, spec 2.3 / G9)."""

COMMIT_SPECIFICATION_HINT = (
    "The fault is verified. Move on to commit-specification: author the "
    "TestImplementationSpec for it as the falsifiable experiment - one "
    "hypothesis, one falsifying outcome per spec - and persist it with "
    "status specified."
)
"""The injected hint after `verified` (the commit-specification hint, G9)."""

NEXT_FAULT_HINT = (
    "The fault is dropped, its reason recorded. Address the next candidate "
    "in rank order, or conclude the hunt when the candidate set is exhausted."
)
"""The injected hint after `dropped` (the next-fault hint, spec 4 / G9)."""

NEXT_ITERATION_HINT = (
    "The spec is ratified and persisted. Start the next loop iteration: pick "
    "the next candidate in rank order, or conclude the hunt when the "
    "candidate set is exhausted."
)
"""The injected hint after `specified` (the next-iteration hint, spec 2.3 / G9)."""

TRANSITION_HINTS: dict[TransitionName, str] = {
    "hypothesise": D2_HINT,
    "verify": COMMIT_SPECIFICATION_HINT,
    "drop": NEXT_FAULT_HINT,
    "specify": NEXT_ITERATION_HINT,
}
"""The phase-transition constants by transition.

The harness reads the constant for the pushed transition and writes it to
`injected_constant`, injected in the tool-call response with the same
mechanism as the orchestrator's - a constant, never the system prompt. "none"
carries no hint: appends, reads, and other tool calls inject nothing."""


__all__ = [
    "FaultStatus",
    "FAULT_STATUSES",
    "HuntPhase",
    "TransitionName",
    "FaultItem",
    "SpecItem",
    "HuntState",
    "D2_HINT",
    "COMMIT_SPECIFICATION_HINT",
    "NEXT_FAULT_HINT",
    "NEXT_ITERATION_HINT",
    "TRANSITION_HINTS",
    "detect_transition",
    "push_transition",
]