"""The inbox-surfer mover: the produced->consumed at-least-once delivery
protocol over the hunting memory topology (tracker #172; ADR #169 Q3/Q11/Q13;
spec #169 "The inbox surfer semantics"; the per-loop dispatch is T4 #377, S2 8).

One module, two layers (CODING_STANDARD s3 - pure logic and impure
orchestration in different functions, one file like the curators):

- PURE - `ProducedItem` / `ThreatLoopItem` / `TestSpecItem` /
  `DispatchFeedback` / `DeliveryPlan` / `ProducedInbox`, the loop validity
  predicate (`threat_loop_item`), the dispatch sequencing (`sequence_dispatch`),
  `deduce_delivery` - the deduction `(produced set, session registry state,
  dispatch feedback) -> (to dispatch, to move, to retry)` - and the ADR Q13
  session-id builders (`threat_modeller_session_id` / `hunter_session_id` /
  `pod_session_id`). No I/O, no clock, deterministic under equal inputs.
- IMPURE - `run_delivery_tick`: reads the produced inboxes from the memory
  stores, calls the pure deduction, drives the delivery against a control
  plane (the T2 shared `RuntimeManager.schedule` with the session-id-as-name
  rule - `RuntimeControlPlane`, injectable per s6), and applies the
  produced->consumed moves through the stores' single-owner primitives
  (`ThreatModelStore.consume_loop` / `HunterMemoryStore.consume_spec` and -
  while the config family retires - `HuntStore.consume_config`). It does NO
  reasoning of its own - every decision is in the deduction.

The dispatch grain is the LOOP FILE (S2 8.4): one produced loop file is one
`ThreatLoopItem`, whose `message_id` IS the store-derived dispatch id
`<unit_name>__<loop_id>` and whose session id is the per-loop hunter id
(`hunting:<run_id>:hunt:<dispatch_id>`, S3 8.9). The loop file's move to
`consumed/` IS the admission marker, and the store moves the unit's model
document with its LAST loop file; a zero-loop produced COMPLETED valid model is
consumed by the mover without a dispatch.

The at-least-once protocol (Q3):

- A produced item not yet dispatched -> `to_dispatch`.
- An item whose dispatch was admitted and confirmed (the schedule call did
  not raise `ModuleAdmissionRefused`) -> `to_move`: the produced->consumed
  move IS the at-least-once marker.
- A refused dispatch (gate full -> `ModuleAdmissionRefused`, module paused /
  draining) - a `coro_for` that raised, or a `coro_for` that answered
  `None` (the item is not dispatchable this tick - a stopped role, a loop file
  whose model cannot be read, a draft config/spec) - -> `to_retry`, REMAINING
  in produced for the next tick: at-least-once, never dropped, never moved.
- An item whose session id is ALREADY LIVE in the registry is considered
  dispatched (Q12: session id = registry run name) - never re-dispatched
  (the double-dispatch defense at the deduction level) - and its move lands:
  this is what closes the R3 crash window between dispatch and move without
  extra markers (the registry state is the confirmation; the operator ruling
  Q3/R3 accepts the window as negligible, this just also completes it).

The mover owns NO scheduling (the runtime owns the loop), NEVER gates
admission (the shared gate is the control plane's, Q15), and knows no
producer/consumer coroutine (those are injected per tick as `coro_for`,
wired by the run bootstrap - `attack/hunting/surfer.py`).

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6): the active runtime resolves lazily on first control-plane use.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import AbstractSet, Any, Callable, Iterable, Mapping, Protocol, Sequence

from polymerhus.attack.hunting.threat_model import Likelihood, UnitKind
from polymerhus.attack.hunting.threat_model_store import dispatch_id, is_loop_id
from polymerhus.app.runtime import ModuleAdmissionRefused

logger = logging.getLogger(__name__)


def _close_coro(coro: Any) -> None:
    """Close a never-run coroutine best-effort: a bare coroutine has a
    `close()` (no await needed); a non-coroutine awaitable (a task/future)
    has nothing to reap. Never raises."""
    close = getattr(coro, "close", None)
    if close is not None:
        try:
            close()
        except Exception:  # noqa: BLE001 - reaping is best-effort
            pass


# --- the ADR Q13 session-id scheme (pure) ---------------------------------------

# The renamed session segment (S1 4.1, impact map section 6): the modeller's
# session id segment; the legacy segment stays accepted for one window. THIS is
# the ONE home of the segment vocabulary - `threat_modeller_session_id` and
# `orchestrator_session_id` below build from it, and the classifier
# (`surfer.derive_thread_role`) reads `THREAT_MODELLER_SEGMENTS`. The role tag it
# classifies as (`surfer.THREAT_MODELLER_ROLE`) is a DIFFERENT vocabulary.
MODELLER_SESSION_SEGMENT = "threat-modeller"
MODELLER_SESSION_SEGMENT_LEGACY = "orchestrator"
THREAT_MODELLER_SEGMENTS = (
    MODELLER_SESSION_SEGMENT, MODELLER_SESSION_SEGMENT_LEGACY,
)


def threat_modeller_session_id(run_id: str) -> str:
    """The ADR Q13 modeller session id, renamed in place (S1 4.1):
    `hunting:<run_id>:threat-modeller`. The registry run name the run bootstrap
    registers its ONE modeller pass under (session id = coroutine id = registry
    run name, Q12)."""
    _require_non_empty(run_id, "run_id")
    return f"hunting:{run_id}:{MODELLER_SESSION_SEGMENT}"


def orchestrator_session_id(run_id: str) -> str:
    """The LEGACY ADR Q13 session id: `hunting:<run_id>:orchestrator`.

    Kept for one change window (S1 4.1): an interrupted run recorded before the
    rename is addressed under this id, and its live session is classified as the
    modeller role. New runs use `threat_modeller_session_id`; the helper retires
    with the alias."""
    _require_non_empty(run_id, "run_id")
    return f"hunting:{run_id}:{MODELLER_SESSION_SEGMENT_LEGACY}"


def hunter_session_id(run_id: str, dispatch_id: str) -> str:
    """The ADR Q13 hunter session id: `hunting:<run_id>:hunt:<dispatch_id>`.
    `dispatch_id` is the loop file's dispatch identity `<unit_name>__<loop_id>`
    (S2 8.1, S3 8.9): the loop file IS the dispatch grain, so the session id
    embeds the loop's own identity - never a config key."""
    _require_non_empty(run_id, "run_id")
    _require_non_empty(dispatch_id, "dispatch_id")
    return f"hunting:{run_id}:hunt:{dispatch_id}"


def pod_session_id(run_id: str, dispatch_id: str, spec_id: str) -> str:
    """The ADR Q13 pod session id:
    `hunting:<run_id>:pod:<dispatch_id>:<spec_id>` (S3 8.7).
    `spec_id` is the semantic spec file name `<fault>_<strategy>` (164 spec 6).
    `dispatch_id` is the spec's parent hunt key - the spec's own memory-item key
    (the folder the spec lives under, S3 8.9), so the mover derives the pod
    session from the spec's own keys, on the fly (Q13: session addresses derive
    from the memory-item keys)."""
    _require_non_empty(run_id, "run_id")
    _require_non_empty(dispatch_id, "dispatch_id")
    _require_non_empty(spec_id, "spec_id")
    return f"hunting:{run_id}:pod:{dispatch_id}:{spec_id}"


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
class ThreatLoopItem(ProducedItem):
    """ONE produced loop file - the dispatch record (S2 8.1, S3 8.9). `message_id`
    IS the loop file's `dispatch_id` (`<unit_name>__<loop_id>`, the store-owned
    derived symbol) and the session id is the per-loop hunter id. `record` is the
    loop file's body verbatim: the payload materialisation reads it at dispatch
    time (S2 8.2), so the mover carries the dispatch record itself - never a
    config.

    `unit_name` is the on-disk unit directory name (the store's derived symbol,
    collision-suffixed when two unit ids sanitise alike), which is the move
    target's directory; `unit_id` is the authoritative model identity."""

    unit_id: str
    unit_name: str
    loop_id: str
    dispatch_id: str
    likelihood: str
    record: Mapping[str, Any]


@dataclass(frozen=True)
class HuntConfigItem(ProducedItem):
    """A produced hunt config (the retiring config family, T2b/T3 wiring).

    designed-for-removal -> T4b (#377): the loop file is the dispatch record
    (S2 8.2: no `HuntConfig`), so this family, its `HuntStore.consume_config`
    move, and the surfer's config branch retire with the T4b sweep. It stays
    until then ONLY because the surfer still dispatches the family; nothing new
    may consume it."""

    config_key: str


@dataclass(frozen=True)
class TestSpecItem(ProducedItem):
    """A produced test-implementation spec (hunter -> pod dispatch). The hunt
    key is the folder the spec lives under - the loop dispatch id
    `<unit_name>__<loop_id>` (S3 8.9) - and `spec_file` the `<fault>_<strategy>`
    file-name stem; the two together address the single-owner
    `HunterMemoryStore.consume_spec` move (and the pod session id, whose middle
    segment IS the spec's own hunt key). `spec` is the persisted body the
    produced read already fetched (the dispatch validity gate), so the pod
    branch dispatches exactly the body that was validated."""

    fault_key: str
    spec_file: str
    spec: Mapping[str, Any] | None = None


class DispatchFeedback(Enum):
    """The per-item dispatch feedback the deduction consumes: `ADMITTED` (the
    control plane scheduled the session, no `ModuleAdmissionRefused` was
    raised) or `REFUSED` (gate full, module paused/draining, or no dispatch
    coroutine) - the two outcomes the protocol's "correct dispatch feedback"
    names."""

    ADMITTED = "admitted"
    REFUSED = "refused"


# --- the loop dispatch record: the validity predicate + the sequencing ---------

# The sequencing's higher tiers (S2 8.3): a `low` loop file waits while one of
# these is produced or its hunter session is live.
HIGHER_TIERS: tuple[str, ...] = ("critical", "high", "medium")

# The likelihood values a loop FILE may carry: `none` has no file at all
# (S2 8.3), so a file carrying it is malformed, never work.
_DISPATCHABLE_LIKELIHOODS = tuple(
    level.value for level in Likelihood if level is not Likelihood.NONE
)
_UNIT_KINDS = tuple(kind.value for kind in UnitKind)


def threat_loop_item(
    *,
    unit_id: str,
    unit_name: str,
    loop_id: str,
    record: Any,
    run_id: str,
) -> ThreatLoopItem | None:
    """The ONE loop validity predicate (S2 8.1, 8.4; T4 #377): the dispatch
    record for one produced loop file, or None when the file is refused.

    Both the run's work read (`run_work_remaining`) and its dispatch read
    (`build_run_dispatch`) build on this predicate through the ONE produced read
    (`read_produced_inbox`), so the quiesce predicate and the dispatch decision
    can never disagree: whatever is not an item is neither dispatched nor
    counted as pending work.

    Refused (None), each named by the file it contradicts:

    - a body that is not a mapping;
    - `run_id` of another run (S2 8.3: the sequencing is run-scoped - another
      run's loop file is left untouched, never dispatched by this run);
    - a `unit_id`/`unit_kind` that disagrees with the unit the file lives under;
    - a `loop_id` that is not the store-owned `loop-<rank>` form, does not match
      the file's own stem, or disagrees with the nested loop record's `id`;
    - a `dispatch_id` that is not the store-derived `<unit_name>__<loop_id>`
      (the session id derives from it, so an unverified one would address the
      wrong session);
    - a `likelihood` outside `{low, medium, high, critical}` (`none` has no
      file; anything else is a foreign or corrupt body);
    - a nested `loop` record that is not a mapping, or carries no
      `fault_ref`/`vulnerability_ref` - the payload's anchors.

    A refusal is logged ONCE per file: the mover retries the produced file every
    tick, so a per-tick log would flood the run log."""
    if not isinstance(record, Mapping):
        return _refuse_loop(run_id, unit_name, loop_id, "the body is not a mapping")
    if record.get("run_id") != run_id:
        return _refuse_loop(
            run_id, unit_name, loop_id,
            f"it belongs to run {record.get('run_id')!r}",
        )
    if record.get("unit_id") != unit_id or not unit_id:
        return _refuse_loop(
            run_id, unit_name, loop_id,
            f"its unit_id {record.get('unit_id')!r} disagrees with the unit "
            f"directory's {unit_id!r}",
        )
    if record.get("unit_kind") not in _UNIT_KINDS:
        return _refuse_loop(
            run_id, unit_name, loop_id,
            f"unknown unit_kind {record.get('unit_kind')!r}",
        )
    if not is_loop_id(loop_id) or record.get("loop_id") != loop_id:
        return _refuse_loop(
            run_id, unit_name, loop_id,
            f"the loop id {record.get('loop_id')!r} is not the file's "
            f"{loop_id!r} of the `loop-<rank>` form",
        )
    dispatch = dispatch_id(unit_name, loop_id)
    if record.get("dispatch_id") != dispatch:
        return _refuse_loop(
            run_id, unit_name, loop_id,
            f"its dispatch_id {record.get('dispatch_id')!r} is not the "
            f"store-derived {dispatch!r}",
        )
    likelihood = record.get("likelihood")
    if likelihood not in _DISPATCHABLE_LIKELIHOODS:
        return _refuse_loop(
            run_id, unit_name, loop_id,
            f"unknown or undispatchable likelihood {likelihood!r}",
        )
    loop = record.get("loop")
    if not isinstance(loop, Mapping) or not loop.get("fault_ref") \
            or not loop.get("vulnerability_ref") or loop.get("id") != loop_id:
        return _refuse_loop(
            run_id, unit_name, loop_id,
            "its loop record is missing or carries no fault_ref/"
            "vulnerability_ref/loop id",
        )
    return ThreatLoopItem(
        message_id=dispatch,
        session_id=hunter_session_id(run_id, dispatch),
        unit_id=unit_id,
        unit_name=unit_name,
        loop_id=loop_id,
        dispatch_id=dispatch,
        likelihood=str(likelihood),
        record=record,
    )


# The loop files already refused, so each malformed body is logged once (the
# mover re-reads the produced family every tick).
_REFUSED_LOOPS: set[str] = set()


def _refuse_loop(run_id: str, unit_name: str, loop_id: str, why: str) -> None:
    key = f"{run_id}/{unit_name}/{loop_id}"
    if key in _REFUSED_LOOPS:
        return None
    _REFUSED_LOOPS.add(key)
    logger.warning(
        "mover: produced loop file %s/%s refused - %s; never dispatched and "
        "not counted as work", unit_name, loop_id, why,
    )
    return None


def sequence_dispatch(
    items: Sequence[ProducedItem],
    live_likelihoods: Mapping[str, str] | Iterable[str] = (),
) -> tuple[ProducedItem, ...]:
    """The dispatch sequencing filter (S2 8.3, S1 7.6): a `critical`, `high` or
    `medium` loop dispatches immediately; a `low` loop dispatches only when no
    higher-tier loop file is produced (`items`) and no higher-tier hunter session
    is live (`live_likelihoods`, the run's own dispatch state keyed by dispatch
    id).

    Pure: equal inputs -> equal outputs; the produced order survives. The
    sequencing ranks LOOPS only - every other produced item (the pod family's
    specs, S3 8.7) passes through untouched.

    `none` loops have no file at all, so they can never appear here. A session
    is "live" while its hunter is still working the loop: an idle hunter authors
    nothing more, so it cannot hold a later low loop (and holding quiesce on it
    would deadlock the run terminal's settle, S2 8.4)."""
    tiers = set(
        live_likelihoods.values()
        if isinstance(live_likelihoods, Mapping) else live_likelihoods
    ) | {
        item.likelihood for item in items if isinstance(item, ThreatLoopItem)
    }
    if not any(tier in HIGHER_TIERS for tier in tiers):
        return tuple(items)
    return tuple(
        item for item in items
        if not (isinstance(item, ThreatLoopItem) and item.likelihood == Likelihood.LOW.value)
    )


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
    coroutine - stays produced for the next tick); `paused` = the produced
    items the sequencing filter held back this tick (a `low` loop file behind a
    higher-tier loop, S2 8.3); `moved` = records renamed produced->consumed;
    `models_consumed` = produced model documents renamed to consumed/ (the
    zero-loop consume and the last-loop-file move, S2 8.4); `move_failed` =
    records the move could not complete (missing record or a storage failure -
    warned and counted, never aborting the tick)."""

    produced: int
    dispatched: int
    admitted: int
    refused: int
    moved: int
    move_failed: int
    paused: int = 0
    models_consumed: int = 0


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

    def gate(self) -> Any:
        """The module's dispatch gate (Q15), or None when no manager is
        bound. Accessed by the run bootstrap so the session coroutines it
        builds acquire the same gate the control plane's admission uses."""
        ...

    def role_gate(self, run_id: str, role: str) -> Any:
        """The run's per-role agent-sub-module gate (#317), or None when no
        manager is bound. Acquired by a dispatched role session around its
        active stretch so a stopped role holds its in-flight threads."""
        ...

    def role_running(self, run_id: str, role: str) -> bool:
        """True when the run's agent-sub-module for `role` is `RUNNING` (#317).
        The surfer's dispatch builder refuses (answers no coroutine) for a role
        that is not running. Fail-open True when no manager is bound."""
        ...

    def start_session(self, session_id: str, coro: Any) -> Any:
        """Schedule a run SESSION (the modeller pass, the run-scoped
        surfer) under its Q13 session id and return an awaitable of its
        outcome, or None when not admitted. The mover never calls this - the
        run bootstrap does, so it can await the sessions' settle."""
        ...

    def cancel_session(self, session_id: str) -> None:
        """Hard-cancel ONE registered session by id (the per-session stop
        verb, Q12). A no-op for a session that already settled."""
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
    (tests) or None (the process's active manager).

    The T4 session verbs (`start_session` / `cancel_session` / `gate`) are the
    run bootstrap's seam over the SAME manager the mover's dispatch uses, so
    the two always see one registry and one gate (Q12: session id = coroutine
    id = registry run name)."""

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

    def gate(self) -> Any:
        manager = self._manager()
        if manager is None:
            return None
        try:
            return manager.gate(self._module)
        except Exception as exc:  # noqa: BLE001 - fail-open: no gate, sessions run ungated
            logger.warning(
                "mover: gate read of module %s failed (%s); "
                "sessions run ungated (fail-open)", self._module, exc,
            )
            return None

    def role_gate(self, run_id: str, role: str) -> Any:
        """The run's agent-sub-module gate for `role` (#317), or None when no
        manager is bound (fail-open: the session runs ungated)."""
        manager = self._manager()
        if manager is None:
            return None
        try:
            return manager.agent_submodule_gate(self._module, run_id, role)
        except Exception as exc:  # noqa: BLE001 - fail-open: no role gate
            logger.warning(
                "mover: role gate read (%s/%s) failed (%s); session runs "
                "ungated (fail-open)", run_id, role, exc,
            )
            return None

    def role_running(self, run_id: str, role: str) -> bool:
        """True when the run's agent-sub-module for `role` is `RUNNING` (#317).
        Fail-open True when no manager is bound or the read fails, so a manager-less
        mover never wedges a run."""
        manager = self._manager()
        if manager is None:
            return True
        try:
            return manager.agent_submodule_running(self._module, run_id, role)
        except Exception as exc:  # noqa: BLE001 - fail-open: treat the role as up
            logger.warning(
                "mover: role state read (%s/%s) failed (%s); treating as "
                "running (fail-open)", run_id, role, exc,
            )
            return True

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

    def start_session(self, session_id: str, coro: Any) -> Any:
        manager = self._manager()
        if manager is None:
            logger.warning(
                "mover: no active runtime to start session %s; "
                "run degrades (fail-open)", session_id,
            )
            try:
                coro.close()  # the session is never scheduled on a manager-less plane
            except Exception:  # noqa: BLE001 - closing is best-effort
                pass
            return None
        try:
            return manager.schedule(self._module, coro, name=session_id)
        except Exception as exc:  # noqa: BLE001 - admission refusal is a degraded run
            logger.warning(
                "mover: session %s not admitted (%s); run degrades",
                session_id, exc,
            )
            try:
                coro.close()
            except Exception:  # noqa: BLE001 - closing is best-effort
                pass
            return None

    def cancel_session(self, session_id: str) -> None:
        manager = self._manager()
        if manager is None:
            return
        try:
            manager.cancel_run(self._module, session_id)
        except Exception:  # noqa: BLE001 - already settled is fine
            logger.warning(
                "mover: session %s had no live run to cancel (no-op)", session_id,
            )


@dataclass(frozen=True)
class ProducedInbox:
    """One tick's read of the produced families (the mover's inbox).

    `items` are the dispatchable-gram candidates: this run's produced loop files
    (the dispatch grain, S2 8.4) and the pod family's produced specs. Each family
    member already passed its own validity predicate, so nothing malformed and
    nothing from another run is in here. `finished_models` are the unit ids whose
    produced COMPLETED valid model carries NO loop file: the mover consumes the
    model document without a dispatch (S2 8.4)."""

    items: tuple[ProducedItem, ...] = ()
    finished_models: tuple[str, ...] = ()


def run_delivery_tick(
    project_id: str,
    run_id: str,
    *,
    hunt_store: HuntStore | None = None,
    threat_store: Any = None,
    hunter_store: HunterMemoryStore,
    control: DispatchControlPlane,
    coro_for: Callable[[ProducedItem], Any],
    live_loop_likelihoods: Mapping[str, str] | Iterable[str] = (),
) -> TickReport:
    """One impure mover tick: reads the produced inboxes, calls the pure
    deduction, drives the delivery against the control plane, and applies the
    produced->consumed moves. No reasoning of its own - every decision is in
    `deduce_delivery` / `sequence_dispatch`.

    Protocol per lap:
    1. Read the produced inbox (the threat model store's loop files, the hunter
       memory's test specs, and - until the config family retires - the hunt
       store's configs) plus the live registry session ids.
    2. Apply the sequencing filter: a `low` loop file waits while a higher-tier
       loop file is produced or a higher-tier hunter session is live (S2 8.3).
    3. Deduce with empty feedback -> the items `to_dispatch` this lap.
    4. Dispatch each: build its coroutine via `coro_for` (the T4 seam; a failing
       builder degrades to refused, never a raise into the tick) and hand it to
       the control plane under the item's Q13 session id. Record the
       admitted/refused feedback.
    5. Deduce again with that feedback -> `to_move` (admitted this lap +
       registry-live items) and `to_retry` (refused - left in produced).
    6. Apply the moves through the stores' single-owner primitives, fail-open
       per record (a failed move warns and counts, never aborts the tick).
    7. Consume the produced models whose loop files are all gone: a zero-loop
       produced COMPLETED valid model is consumed here without a dispatch, and
       `consume_loop` has already moved a model whose LAST loop file was
       admitted (S2 8.4 - the model document moves with its last loop).

    Returns the `TickReport`. This function is synchronous: the runtime owns
    the loop (Q11); the mover never awaits, the control plane schedules."""
    inbox = read_produced_inbox(
        project_id, run_id, hunt_store=hunt_store, threat_store=threat_store,
        hunter_store=hunter_store,
    )
    produced = inbox.items
    live = control.live_session_ids()
    dispatchable = sequence_dispatch(produced, live_loop_likelihoods)

    plan = deduce_delivery(dispatchable, live)
    feedback: dict[str, DispatchFeedback] = {}
    admitted = 0
    refused = 0
    for item in plan.to_dispatch:
        try:
            coro = coro_for(item)
        except Exception as exc:  # noqa: BLE001 - a raising builder is a refusal
            logger.warning(
                "mover: no dispatch coroutine for %s (%s); "
                "retried next tick (fail-open)", item.message_id, exc,
            )
            feedback[item.message_id] = DispatchFeedback.REFUSED
            refused += 1
            continue
        if coro is None:
            # The T4 seam answered "not dispatchable this tick" (a draft, a
            # dropped config): refused, at-least-once.
            feedback[item.message_id] = DispatchFeedback.REFUSED
            refused += 1
            continue
        if control.dispatch(item.session_id, coro):
            feedback[item.message_id] = DispatchFeedback.ADMITTED
            admitted += 1
        else:
            # The coroutine the seam built will never run this tick (the
            # at-least-once protocol retries the produced item, building a
            # FRESH coroutine next tick): close the refused one so it is never
            # left dangling (a bare coroutine warning / a never-started run).
            _close_coro(coro)
            feedback[item.message_id] = DispatchFeedback.REFUSED
            refused += 1

    plan = deduce_delivery(dispatchable, live, feedback)
    moved = 0
    move_failed = 0
    for item in plan.to_move:
        try:
            done = _apply_move(
                project_id, item, hunt_store=hunt_store, threat_store=threat_store,
                hunter_store=hunter_store,
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

    models_consumed = _consume_finished_models(
        project_id, run_id, threat_store, inbox.finished_models)

    return TickReport(
        produced=len(produced),
        dispatched=admitted + refused,
        admitted=admitted,
        refused=refused,
        paused=len(produced) - len(dispatchable),
        moved=moved,
        move_failed=move_failed,
        models_consumed=models_consumed,
    )


def _consume_finished_models(
    project_id: str,
    run_id: str,
    threat_store: Any,
    finished_models: Sequence[str],
) -> int:
    """Consume the run's produced models that carry no produced loop file left
    (S2 8.4): a zero-loop COMPLETED valid model is consumed on the mover's next
    tick without a dispatch, and a model whose last loop file this tick admitted
    is consumed by `consume_loop` itself. Run-scoped: another run's produced
    model is left for that run's own mover. The store re-checks consumability
    and the no-loop-file condition, so a model that gained a loop file between
    the read and the move is never consumed early. Fail-open per model."""
    if threat_store is None:
        return 0
    consumed = 0
    for unit_id in finished_models:
        try:
            done = threat_store.consume_model_if_done(project_id, unit_id)
        except Exception as exc:  # noqa: BLE001 - fail-open per model
            logger.warning(
                "mover: model consume of %s failed (%s); counted, tick continues",
                unit_id, exc,
            )
            done = False
        if done:
            consumed += 1
    return consumed


def produced_spec_body(
    hunter_store: Any,
    project_id: str,
    fault_key: str,
    spec_file: str,
) -> dict | None:
    """The produced spec's persisted body, or None (fail-open: a missing record
    or an unreadable one warns and degrades - O4). The `<fault>_<strategy>` stem
    splits on the single `_` separator (G3 keywords never contain `_`), so the
    classifier can read the file it names. The ONE spec-body read: the produced
    read (the dispatch validity gate) and the surfer's dispatch branch both use
    it, so the work read and the dispatch read can never disagree."""
    fault_keyword, sep, strategy_keyword = spec_file.partition("_")
    if not sep or not fault_keyword or not strategy_keyword:
        return None
    try:
        return hunter_store.read_spec(
            project_id, fault_key, fault_keyword, strategy_keyword,
            side="produced",
        )
    except Exception as exc:  # noqa: BLE001 - fail-open read (O4)
        logger.warning("mover: spec body read failed for %s (%s)", spec_file, exc)
        return None


# The pod family's dispatch status (the spec's OWN persisted status is the
# dispatch gate; S3 8.6's `ratified` terminal and the T6 award of the status
# vocabulary land there).
SPEC_DISPATCH_STATUS = "specified"


def read_produced_inbox(
    project_id: str,
    run_id: str,
    *,
    hunt_store: HuntStore | None = None,
    threat_store: Any = None,
    hunter_store: HunterMemoryStore,
) -> ProducedInbox:
    """The produced inbox set for one tick.

    - The threat model store's produced loop files: ONE `ThreatLoopItem` per loop
      file of THIS run (cross-unit - the surfer reads the run's produced loops,
      never only the current unit's; S2 8.3), plus the produced units whose
      consumable model carries no loop file (`finished_models`). A loop file
      whose body fails the validity predicate is refused here, so it is neither
      dispatched nor counted as work.
    - The hunter memory's produced test specs (the pod family, S3 8.7).
    - The hunt store's produced configs (the retiring config family: the T4b
      sweep removes this read with the config dispatch path).

    Each item carries its Q13 session id derived on the fly from the
    memory-item keys (Q13; ADR #169)."""
    items: list[ProducedItem] = []
    finished_models: list[str] = []
    if threat_store is not None:
        for entry in threat_store.read_produced_loops(project_id):
            unit_id = str(entry.get("unit_id") or "")
            unit_name = str(entry.get("unit_name") or "")
            if entry.get("run_id") != run_id:
                continue  # another run's model: its own mover dispatches it
            records = entry.get("loops") or ()
            if not records:
                finished_models.append(unit_id)
            for entry_loop in records:
                item = threat_loop_item(
                    unit_id=unit_id, unit_name=unit_name,
                    loop_id=str(entry_loop.get("loop_id") or ""),
                    record=entry_loop.get("record"), run_id=run_id,
                )
                if item is not None:
                    items.append(item)
    if hunt_store is not None:
        for config_key, file_name in hunt_store.read_produced_configs(project_id):
            config_id = Path(file_name).stem
            items.append(HuntConfigItem(
                message_id=config_key,
                session_id=hunter_session_id(run_id, config_id),
                config_key=config_key,
            ))
    for fault_key in hunter_store.list_fault_keys(project_id):
        for spec_file in hunter_store.produced_spec_files(project_id, fault_key):
            body = produced_spec_body(hunter_store, project_id, fault_key, spec_file)
            if not body or body.get("status") != SPEC_DISPATCH_STATUS:
                # a not-yet-committed draft is NOT work and NOT dispatchable -
                # the ONE gate both reads share (the never-disagree contract)
                continue
            items.append(TestSpecItem(
                message_id=f"{fault_key}/{spec_file}",
                session_id=pod_session_id(run_id, fault_key, spec_file),
                fault_key=fault_key,
                spec_file=spec_file,
                spec=body,
            ))
    return ProducedInbox(items=tuple(items), finished_models=tuple(finished_models))


def _apply_move(
    project_id: str,
    item: ProducedItem,
    *,
    hunt_store: HuntStore | None = None,
    threat_store: Any = None,
    hunter_store: HunterMemoryStore,
) -> bool:
    """Route one `to_move` item to its store's single-owner move primitive.
    The ONLY caller of the move primitives (the single-owner rename, #172 AC):
    the impure shell applies what the deduction decided, nothing else renames
    produced->consumed."""
    if isinstance(item, ThreatLoopItem):
        # The loop file's move IS the admission marker (S2 8.4); the store also
        # moves the model document when this was its last produced loop file.
        return threat_store.consume_loop(project_id, item.unit_id, item.loop_id)
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
    "HIGHER_TIERS",
    "HuntConfigItem",
    "ProducedInbox",
    "ProducedItem",
    "RuntimeControlPlane",
    "TestSpecItem",
    "ThreatLoopItem",
    "TickReport",
    "deduce_delivery",
    "hunter_session_id",
    "MODELLER_SESSION_SEGMENT",
    "MODELLER_SESSION_SEGMENT_LEGACY",
    "THREAT_MODELLER_SEGMENTS",
    "orchestrator_session_id",
    "threat_modeller_session_id",
    "pod_session_id",
    "read_produced_inbox",
    "run_delivery_tick",
    "sequence_dispatch",
    "threat_loop_item",
]