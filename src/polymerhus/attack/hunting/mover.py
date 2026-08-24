"""The inbox-surfer mover: the produced->consumed at-least-once delivery
protocol over the hunting memory topology (tracker #172; ADR #169 Q3/Q11/Q13;
spec #169 "The inbox surfer semantics").

One module, two layers (CODING_STANDARD s3 - pure logic and impure
orchestration in different functions, one file like the curators):

- PURE - `ProducedItem` / `DispatchFeedback` / `DeliveryPlan`,
  `deduce_delivery` - the deduction `(produced set, session registry state,
  dispatch feedback) -> (to dispatch, to move, to retry)` - and the ADR Q13
  session-id builders (`orchestrator_session_id` / `hunter_session_id` /
  `pod_session_id`). No I/O, no clock, deterministic under equal inputs.
- IMPURE - `run_delivery_tick`: reads the produced inboxes from the memory
  stores, calls the pure deduction, drives the delivery against a control
  plane (the T2 shared `RuntimeManager.schedule` with the session-id-as-name
  rule - `RuntimeControlPlane`, injectable per s6), and applies the
  produced->consumed moves through the stores' single-owner primitives
  (`HuntStore.consume_config`, `HunterMemoryStore.consume_spec`). It does NO
  reasoning of its own - every decision is in the deduction.

The at-least-once protocol (Q3):

- A produced item not yet dispatched -> `to_dispatch`.
- An item whose dispatch was admitted and confirmed (the schedule call did
  not raise `ModuleAdmissionRefused`) -> `to_move`: the produced->consumed
  move IS the at-least-once marker.
- A refused dispatch (gate full -> `ModuleAdmissionRefused`, module paused /
  draining) - or a missing dispatch coroutine (the T4-designed-not-built seam)
  - -> `to_retry`, REMAINING in produced for the next tick: at-least-once,
  never dropped, never moved.
- An item whose session id is ALREADY LIVE in the registry is considered
  dispatched (Q12: session id = registry run name) - never re-dispatched
  (the double-dispatch defense at the deduction level) - and its move lands:
  this is what closes the R3 crash window between dispatch and move without
  extra markers (the registry state is the confirmation; the operator ruling
  Q3/R3 accepts the window as negligible, this just also completes it).

The mover owns NO scheduling (the runtime owns the loop), NEVER gates
admission (the shared gate is the control plane's, Q15), and knows no
producer/consumer coroutine (those are injected per tick as `coro_for`,
wired by the run bootstrap - T4). The pod family's experiment-log
consumption rides the hunter's idle loop (T4): the pod session scheme and the
generic item model below are the structured surface it will operate on;
nothing here dispatches `arun_pod` or reads the pod tree yet.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6): the active runtime resolves lazily on first control-plane use.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import AbstractSet, Any, Callable, Mapping, Protocol, Sequence

from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.app.runtime import ModuleAdmissionRefused

logger = logging.getLogger(__name__)


# --- the ADR Q13 session-id scheme (pure) ---------------------------------------

def orchestrator_session_id(run_id: str) -> str:
    """The ADR Q13 orchestrator session id: `hunting:<run_id>:orchestrator`.
    The registry run name the run bootstrap registers its ONE orchestrator
    session under (session id = coroutine id = registry run name, Q12)."""
    _require_non_empty(run_id, "run_id")
    return f"hunting:{run_id}:orchestrator"


def hunter_session_id(run_id: str, config_id: str) -> str:
    """The ADR Q13 hunter session id: `hunting:<run_id>:hunt:<config_id>`.
    `config_id` is the semantic hunt-config file name `<unit>_<CWE>_<class>`
    (memory-system G4) - the produced config's file-name stem the mover reads
    the inbox from."""
    _require_non_empty(run_id, "run_id")
    _require_non_empty(config_id, "config_id")
    return f"hunting:{run_id}:hunt:{config_id}"


def pod_session_id(run_id: str, config_id: str, spec_id: str) -> str:
    """The ADR Q13 pod session id: `hunting:<run_id>:pod:<config_id>:<spec_id>`.
    `spec_id` is the semantic spec file name `<fault>_<strategy>` (164 spec 6).
    `config_id` is the spec's parent config identity - for a produced spec the
    memory-item key the spec lives under IS its config key (the
    `<unit>::<fault>` `fault_key` folder), so the mover derives the pod
    session from the spec's own keys, on the fly (Q13: session addresses
    derive from the memory-item keys)."""
    _require_non_empty(run_id, "run_id")
    _require_non_empty(config_id, "config_id")
    _require_non_empty(spec_id, "spec_id")
    return f"hunting:{run_id}:pod:{config_id}:{spec_id}"


def _require_non_empty(value: str, what: str) -> None:
    if not value:
        raise ValueError(f"{what} must be a non-empty string; got {value!r}")


# --- the pure item model ---------------------------------------------------------

@dataclass(frozen=True)
class ProducedItem:
    """One produced message on the mover's inbox surface: the item's memory
    identity (`message_id`) and the ADR Q13 session id its dispatch maps to.
    The pure deduction reads ONLY these two fields (the family subclasses
    carry the store move addresses for the shell)."""

    message_id: str
    session_id: str


@dataclass(frozen=True)
class HuntConfigItem(ProducedItem):
    """A produced hunt config (orchestrator -> hunter dispatch). `config_key`
    is the config's semantic key - the identity the single-owner
    `HuntStore.consume_config` move targets. `message_id` IS the config key."""

    config_key: str


@dataclass(frozen=True)
class TestSpecItem(ProducedItem):
    """A produced test-implementation spec (hunter -> pod dispatch). `fault_key`
    is the config key the spec lives under, `spec_file` the `<fault>_<strategy>`
    file-name stem - the two together address the single-owner
    `HunterMemoryStore.consume_spec` move (and the pod session id)."""

    fault_key: str
    spec_file: str


class DispatchFeedback(Enum):
    """The per-item dispatch feedback the deduction consumes: `ADMITTED` (the
    control plane scheduled the session, no `ModuleAdmissionRefused` was
    raised) or `REFUSED` (gate full, module paused/draining, or no dispatch
    coroutine) - the two outcomes the protocol's "correct dispatch feedback"
    names."""

    ADMITTED = "admitted"
    REFUSED = "refused"


@dataclass(frozen=True)
class DeliveryPlan:
    """The deduction's output (s5 - typed, covering every delivery semantics):
    what to dispatch, what to move produced->consumed, and what to retry.
    The three are pairwise disjoint. Items appear in the produced-set order."""

    to_dispatch: tuple[ProducedItem, ...] = ()
    to_move: tuple[ProducedItem, ...] = ()
    to_retry: tuple[ProducedItem, ...] = ()


def deduce_delivery(
    produced: Sequence[ProducedItem],
    live_session_ids: AbstractSet[str] = frozenset(),
    feedback: Mapping[str, DispatchFeedback] | None = None,
) -> DeliveryPlan:
    """The pure mover deduction (tracker #172): given the produced set, the
    session registry state, and the dispatch feedback for this tick, return
    what to dispatch, what to move produced->consumed, and what to retry.

    Per item, in produced order:

    - session id already live in the registry -> `to_move`: considered
      dispatched (the registry is the confirmation record, Q12), so never
      re-dispatched; the produced->consumed marker lands (R3 crash-window
      completion without extra markers).
    - feedback ADMITTED -> `to_move` (the at-least-once marker).
    - feedback REFUSED -> `to_retry`: REMAINS in produced for the next tick -
      never dropped, never moved.
    - otherwise -> `to_dispatch`.

    Pure by construction: no I/O, no clock, no side effects; equal inputs ->
    equal outputs. A feedback entry for a message id absent from `produced` is
    ignored; a feedback value outside `DispatchFeedback` is rejected (typed
    contract, s5)."""
    by_item = feedback or {}
    for value in by_item.values():
        if not isinstance(value, DispatchFeedback):
            raise ValueError(
                f"dispatch feedback must map message ids to DispatchFeedback; "
                f"got {value!r}"
            )
    to_dispatch: list[ProducedItem] = []
    to_move: list[ProducedItem] = []
    to_retry: list[ProducedItem] = []
    for item in produced:
        if item.session_id in live_session_ids:
            to_move.append(item)
            continue
        outcome = by_item.get(item.message_id)
        if outcome is DispatchFeedback.ADMITTED:
            to_move.append(item)
        elif outcome is DispatchFeedback.REFUSED:
            to_retry.append(item)
        else:
            to_dispatch.append(item)
    return DeliveryPlan(
        to_dispatch=tuple(to_dispatch),
        to_move=tuple(to_move),
        to_retry=tuple(to_retry),
    )


# --- the impure shell -------------------------------------------------------------

@dataclass(frozen=True)
class TickReport:
    """One mover tick's outcome (s5 - total delivery semantics): every path
    counted. `dispatched` = this lap's delivery attempts (admitted + refused;
    a refused attempt - by control-plane admission or a missing dispatch
    coroutine - stays produced for the next tick); `moved` = records renamed
    produced->consumed; `move_failed` = records the move could not complete
    (missing record or a storage failure - warned and counted, never
    aborting the tick)."""

    produced: int
    dispatched: int
    admitted: int
    refused: int
    moved: int
    move_failed: int


class DispatchControlPlane(Protocol):
    """The control-plane seam the mover drives (s6 - injectable). The real
    body is `RuntimeControlPlane` over the T2 shared runtime manager."""

    def live_session_ids(self) -> AbstractSet[str]:
        """The session ids currently live in the registry (Q12: the run-name
        set of the hunting module)."""
        ...

    def dispatch(self, session_id: str, coro: Any) -> bool:
        """Schedule `coro` as the run named `session_id`. True = admitted
        (the control plane accepted the dispatch); False = refused (the item
        must stay in produced and be retried - at-least-once)."""
        ...


class RuntimeControlPlane:
    """The real control-plane seam (ADR #169 Q12): the SHARED runtime
    manager's run registry + `schedule(module, coro, name=session_id)`.

    Resolves the active manager lazily on first call (s6 - construction does
    no I/O). `ModuleAdmissionRefused` (gate full, module paused/draining) is
    THE refusal signal - returned as refused. A manager that is absent or a
    schedule that raises outside admission degrades FAIL-OPEN to refused too
    (warned): the item stays in produced for the next tick, never dropped -
    the at-least-once ring over the control plane. `runtime` may be injected
    (tests) or None (the process's active manager)."""

    def __init__(self, runtime: Any = None, module: str = "hunting"):
        self._runtime = runtime
        self._module = module

    def _manager(self) -> Any:
        if self._runtime is not None:
            return self._runtime
        from polymerhus.app.runtime import get_active_runtime  # noqa: PLC0415
        return get_active_runtime()

    def live_session_ids(self) -> AbstractSet[str]:
        manager = self._manager()
        if manager is None:
            return frozenset()
        try:
            return frozenset(manager.run_ids(self._module))
        except Exception as exc:  # noqa: BLE001 - fail-open read
            logger.warning(
                "mover: registry read of module %s failed (%s); "
                "treating the registry as empty (fail-open)",
                self._module, exc,
            )
            return frozenset()

    def dispatch(self, session_id: str, coro: Any) -> bool:
        manager = self._manager()
        if manager is None:
            logger.warning(
                "mover: no active runtime to dispatch %s; "
                "retried next tick (fail-open)", session_id,
            )
            return False
        try:
            manager.schedule(self._module, coro, name=session_id)
        except ModuleAdmissionRefused:
            # gate full / module paused / draining: not admitted - retry
            return False
        except Exception as exc:  # noqa: BLE001 - never drop the item
            logger.warning(
                "mover: dispatch of %s failed (%s); "
                "retried next tick (fail-open)", session_id, exc,
            )
            return False
        return True


def run_delivery_tick(
    project_id: str,
    run_id: str,
    *,
    hunt_store: HuntStore,
    hunter_store: HunterMemoryStore,
    control: DispatchControlPlane,
    coro_for: Callable[[ProducedItem], Any],
) -> TickReport:
    """One impure mover tick: reads the produced inboxes, calls the pure
    deduction, drives the delivery against the control plane, and applies the
    produced->consumed moves. No reasoning of its own - every decision is in
    `deduce_delivery`.

    Protocol per lap:
    1. Read the produced inbox (hunt configs + test specs) and the live
       registry session ids.
    2. Deduce with empty feedback -> the items `to_dispatch` this lap.
    3. Dispatch each: build its coroutine via `coro_for` (the T4 seam; a
       failing builder degrades to refused, never a raise into the tick) and
       hand it to the control plane under the item's Q13 session id. Record
       the admitted/refused feedback.
    4. Deduce again with that feedback -> `to_move` (admitted this lap +
       registry-live items) and `to_retry` (refused - left in produced).
    5. Apply the moves through the stores' single-owner primitives, fail-open
       per record (a failed move warns and counts, never aborts the tick).

    Returns the `TickReport`. This function is synchronous: the runtime owns
    the loop (Q11); the mover never awaits, the control plane schedules."""
    produced = read_produced_inbox(
        project_id, run_id, hunt_store=hunt_store, hunter_store=hunter_store,
    )
    live = control.live_session_ids()

    plan = deduce_delivery(produced, live)
    feedback: dict[str, DispatchFeedback] = {}
    admitted = 0
    refused = 0
    for item in plan.to_dispatch:
        try:
            coro = coro_for(item)
        except Exception as exc:  # noqa: BLE001 - the T4 seam is absent
            logger.warning(
                "mover: no dispatch coroutine for %s (%s); "
                "retried next tick (fail-open)", item.message_id, exc,
            )
            feedback[item.message_id] = DispatchFeedback.REFUSED
            refused += 1
            continue
        if control.dispatch(item.session_id, coro):
            feedback[item.message_id] = DispatchFeedback.ADMITTED
            admitted += 1
        else:
            feedback[item.message_id] = DispatchFeedback.REFUSED
            refused += 1

    plan = deduce_delivery(produced, live, feedback)
    moved = 0
    move_failed = 0
    for item in plan.to_move:
        try:
            done = _apply_move(
                project_id, item, hunt_store=hunt_store, hunter_store=hunter_store,
            )
        except Exception as exc:  # noqa: BLE001 - fail-open per record
            logger.warning(
                "mover: move of %s failed (%s); counted, tick continues",
                item.message_id, exc,
            )
            done = False
        if done:
            moved += 1
        else:
            move_failed += 1

    return TickReport(
        produced=len(produced),
        dispatched=admitted + refused,
        admitted=admitted,
        refused=refused,
        moved=moved,
        move_failed=move_failed,
    )


def read_produced_inbox(
    project_id: str,
    run_id: str,
    *,
    hunt_store: HuntStore,
    hunter_store: HunterMemoryStore,
) -> list[ProducedItem]:
    """The produced inbox set for one tick: every produced hunt config
    (configs first, file-name order) and produced test spec (fault-key order,
    file-name order within). Each item carries its Q13 session id derived on
    the fly from the memory-item keys (Q13; ADR #169)."""
    items: list[ProducedItem] = []
    for config_key, file_name in hunt_store.read_produced_configs(project_id):
        config_id = Path(file_name).stem
        items.append(HuntConfigItem(
            message_id=config_key,
            session_id=hunter_session_id(run_id, config_id),
            config_key=config_key,
        ))
    for fault_key in hunter_store.list_fault_keys(project_id):
        for spec_file in hunter_store.produced_spec_files(project_id, fault_key):
            items.append(TestSpecItem(
                message_id=f"{fault_key}/{spec_file}",
                session_id=pod_session_id(run_id, fault_key, spec_file),
                fault_key=fault_key,
                spec_file=spec_file,
            ))
    return items


def _apply_move(
    project_id: str,
    item: ProducedItem,
    *,
    hunt_store: HuntStore,
    hunter_store: HunterMemoryStore,
) -> bool:
    """Route one `to_move` item to its store's single-owner move primitive.
    The ONLY caller of the move primitives (the single-owner rename, #172 AC):
    the impure shell applies what the deduction decided, nothing else renames
    produced->consumed."""
    if isinstance(item, HuntConfigItem):
        return hunt_store.consume_config(project_id, item.config_key)
    if isinstance(item, TestSpecItem):
        return hunter_store.consume_spec(project_id, item.fault_key, item.spec_file)
    raise TypeError(
        f"mover: no move primitive for item {item.message_id!r} "
        f"({type(item).__name__})"
    )


__all__ = [
    "DeliveryPlan",
    "DispatchControlPlane",
    "DispatchFeedback",
    "HuntConfigItem",
    "ProducedItem",
    "RuntimeControlPlane",
    "TestSpecItem",
    "TickReport",
    "deduce_delivery",
    "hunter_session_id",
    "orchestrator_session_id",
    "pod_session_id",
    "read_produced_inbox",
    "run_delivery_tick",
]