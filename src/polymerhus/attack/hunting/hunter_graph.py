"""The state-graph hunter's StateGraph topology (#164, S4 14.10): the pass tracker.

The graph does NOT navigate the decision tree (S4 2.1): the ReAct engine does.
This graph is the state-tracking and trajectory-boundary layer over it - a
PASSIVE detection-and-push machine (the no-block invariant): it observes the
signal the harness reads off the model's tool call, applies the pure
acceptance rule, and pushes the state move plus the injected transition
constant. It NEVER gates a tool call on the current state and never rejects a
signal - the graph records what the model signalled. The harness is the sole
writer: it drives one compiled graph per hunt (no graph-level checkpointer)
with each observation and reads the moved state back.

Topology (S4 14.10):

```
  START -> supervise
  supervise --signal pending--> detect
  supervise --state complete--> END
  detect    --advance/forward_jump--> advance
  detect    --trail_only/none--> supervise
  advance   -> supervise                       (static: the next drive is ready)
  supervise --no signal--> supervise (stay; the turn carries no signal)
```

The graph holds no model. Routing originates ONLY from `supervise` (the sole
entry: a pending signal vs the terminal `complete` vs the stay) and `detect`
(the deterministic dispatcher over the pure acceptance rule); `advance` returns
to `supervise` on a static edge, so the loop restarts naturally per drive.

The stay carries no destination at all: the drive returns with the channels
untouched (`Command(goto=[])`) instead of claiming END, because END means the
chain is over - and the chain is over only on `complete`. Reaching END
mid-chain would let the ReAct host stop driving the tracker, which is exactly
the wedged state the forward-jump rule exists to prevent.

The channels are `hunter_state.HuntState` (every field last-write EXCEPT
`trail`, the `operator.add` trajectory record, replay only, never
authoritative) plus the TRANSIENT per-drive inputs (`observed_signal` /
`observed_outcome`) the harness hands each `ainvoke`. There is NO `messages`
channel: the ReAct turns own their message history in the per-hunt session
checkpointer.

This module builds (never compiles) the graph; `build_hunter_graph` takes
injectable node closures so a pass compiles IN-MEMORY and the harness supplies
the default passive nodes. No driver and no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .hunter_state import (
    COMPLETE,
    HuntState,
    PhaseSignal,
    SignalOutcome,
    advance_state,
    detect_signal,
)

logger = logging.getLogger(__name__)

# Stable node names (routed by the sole-entry tracker / the deterministic
# dispatcher).
_SUPERVISE = "supervise"
_DETECT = "detect"
_ADVANCE = "advance"


class HunterGraphState(HuntState, total=False):
    """The compiled graph's channels: `HuntState` plus the per-drive inputs.

    Every `HuntState` field is last-write EXCEPT `trail` (the `operator.add`
    trajectory record). `observed_signal` is the TRANSIENT observation the
    harness hands each `ainvoke` (one signal per drive) and `observed_outcome`
    the pure acceptance rule's answer riding `detect -> advance`; both are
    consumed by the drive. Neither belongs to the pure `HuntState` vocabulary
    (`hunter_state.py`): they exist only on the compiled graph."""

    observed_signal: PhaseSignal | None
    observed_outcome: SignalOutcome


def route_supervise(state: HunterGraphState) -> str | None:
    """The sole-entry state tracker's route (S4 14.10), as a pure function.

    - `complete` -> END: the chain is over (the terminal spec-set write landed).
    - a signal is pending -> `detect`.
    - otherwise -> None: the turn carries no signal. Nothing moves and the
      drive returns; END is deliberately NOT claimed mid-chain."""
    if (state.get("state") or "grounding") == COMPLETE:
        return END
    if state.get("observed_signal") is not None:
        return _DETECT
    return None


def _supervise(state: HunterGraphState) -> Command:
    """The state tracker: routing ONLY (DP-5, a single `Command`). The stay
    carries no destination, so the drive returns with the channels untouched."""
    return Command(goto=route_supervise(state) or [])


def _detect(state: HunterGraphState) -> Command:
    """The deterministic dispatcher over the pure acceptance rule (S4 14.5).

    An advance or forward jump hands the outcome to `advance`; a trail-only
    signal (an earlier pass's signal) appends its entry here and returns to the
    tracker, because it never moves the state; a no-signal outcome consumes the
    observation and returns with nothing appended. The machine never rejects a
    signal and never raises."""
    signal = state.get("observed_signal")
    outcome = detect_signal(state, signal)
    if outcome["kind"] in ("advance", "forward_jump"):
        return Command(goto=_ADVANCE, update={"observed_outcome": outcome})
    if outcome["kind"] == "trail_only":
        _, _, entry = advance_state(state, outcome, signal)
        return Command(
            goto=_SUPERVISE,
            update={"observed_signal": None, "trail": [entry]},
        )
    return Command(goto=_SUPERVISE, update={"observed_signal": None})


def _advance(state: HunterGraphState) -> dict:
    """The push: `hunter_state.advance_state` moves the state, the node injects
    the exited pass's constant (a constant, never the system prompt) and
    records the trail entry, then consumes the observation. The trail is
    `operator.add`: only the fresh entry returns, so the accumulated trajectory
    is never re-appended. The `specs` channel is last-write and untouched -
    the spec-store write remains authoritative for the set."""
    signal = state.get("observed_signal")
    outcome = state.get("observed_outcome") or {"kind": "none"}
    new_state, hint, entry = advance_state(state, outcome, signal)
    return {
        "state": new_state["state"],
        "injected_constant": hint,
        "trail": [entry] if entry is not None else [],
        "observed_signal": None,
        "observed_outcome": None,
    }


def build_hunter_graph(
    *,
    supervise_node: Callable[[HunterGraphState], Any] | None = None,
    detect_node: Callable[[HunterGraphState], Any] | None = None,
    advance_node: Callable[[HunterGraphState], Any] | None = None,
) -> StateGraph:
    """Build (do NOT compile) the state-graph hunter's graph. Injectable node
    closures mirror `build_hunting_graph`; each default node is the PASSIVE
    pass tracker above (a raising injected body degrades the drive, never
    aborts the hunt - the harness's fail-open canon). Routing originates ONLY
    from `supervise` and `detect` via `Command(goto=...)`; `advance` returns to
    `supervise` on a static edge, so the loop restarts naturally per drive."""
    g = StateGraph(HunterGraphState)
    g.add_node(_SUPERVISE, supervise_node or _supervise)
    g.add_node(_DETECT, detect_node or _detect)
    g.add_node(_ADVANCE, advance_node or _advance)
    g.add_edge(START, _SUPERVISE)
    g.add_edge(_ADVANCE, _SUPERVISE)  # static: the next drive is ready
    return g


__all__ = [
    "HunterGraphState",
    "_SUPERVISE",
    "_DETECT",
    "_ADVANCE",
    "route_supervise",
    "build_hunter_graph",
    "_supervise",
    "_detect",
    "_advance",
]
