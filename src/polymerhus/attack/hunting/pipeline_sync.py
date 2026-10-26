"""The hunting pipeline sync policy (`hunting_pipeline_sync`, ADR
`docs/design/hunting-pipeline-sync-adr.md`, 2026-10-22).

The project-level mode governs WHEN the pipeline phases may dispatch:

- `parallel` - the historical behaviour: every produced item the mover finds is
  dispatched as it appears (the S1 7.3 interleave stays live);
- `batched` - phase barriers only: the modeller pass settles first, then one
  unit at a time in risk order, its whole hunter batch concurrently, then its
  pods one hunt at a time in threat-rank order (every spec of the current hunt
  concurrently), then the next unit;
- `serial` - the same queue strictly one agent at a time: hunter N+1 after
  hunter N completed AND every one of its pods reached a terminal export, and
  the pods of one hunt one at a time in file-stem order.

This module holds the PURE surface (`SyncMode`, the unit metadata, the fact
snapshot, the ordering and the per-mode `decide`). The impure adapter that
gathers the facts from the stores and the session registry is
`RunSyncGate`, built by the run bootstrap and consulted by the surfer's mover
tick.

Purity: `decide` has no I/O, no clock and no mutable state; equal inputs yield
equal outputs. Every terminal fact is storage-backed (the spec files, the
durable PodExport records) or registry-backed (the hunts still in their graph,
the live pod sessions), so a resumed run re-derives the same decision.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from polymerhus.attack.hunting.mover import (
    SPEC_DISPATCH_STATUS,
    ProducedItem,
    TestSpecItem,
    ThreatItem,
    threat_modeller_session_id,
    threat_risk,
)
from polymerhus.attack.hunting.threat_model import RISK_WEIGHTS, Likelihood

# The dispatch queue's intake-position fallback: a unit the run record has not
# named (a recovered spec-only unit) sorts after every recorded unit. The name
# then breaks the tie deterministically.
UNKNOWN_INTAKE_POSITION = 1_000_000

# The rank fallback for a dispatch id whose threat id is not `threat-<n>` (a
# malformed or foreign key): it sorts after every ranked hunt and never crashes
# the decision.
UNRANKED = 1 << 30
# An unknown blocked unit sorts ahead of every known unit: without a readable
# spec body the gate cannot prove its identity or risk, so it fails closed and
# holds the queue instead of silently skipping the stale hunt.
BLOCKED_RISK = 1 << 30


class SyncMode(StrEnum):
    """The project-level pipeline synchronisation mode (`hunting_pipeline_sync`)."""

    SERIAL = "serial"
    BATCHED = "batched"
    PARALLEL = "parallel"


DEFAULT_SYNC_MODE = SyncMode.BATCHED
DEFAULT_POD_BATCH_SIZE = 1

logger = logging.getLogger(__name__)


def _int_at_least(value: Any, minimum: int, *, setting: str) -> int | None:
    """One stored integer candidate, or None when it is malformed or below the
    documented floor. A boolean, a float, a numeric string, or a negative value
    is malformed: the settings are DB-stored integers, and the API writes only
    strict integers. A malformed value warns once and falls through."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        logger.warning(
            "hunting: %s=%r is not an integer; falling back", setting, value)
        return None
    if value < minimum:
        logger.warning(
            "hunting: %s=%d is below %d; falling back", setting, value, minimum)
        return None
    return value


def resolve_pod_batch_size(
    recorded: Any,
    settings: Mapping[str, Any] | None,
) -> int:
    """The run's frozen pod batch size: the run record first (a resume keeps
    the width the run booted with), then the project setting, then 1. A
    malformed candidate warns and falls through rather than failing the run."""
    for candidate in (recorded, (settings or {}).get("pod_batch_size")):
        value = _int_at_least(candidate, 1, setting="pod_batch_size")
        if value is not None:
            return value
    return DEFAULT_POD_BATCH_SIZE


def resolve_promotion_risk_threshold(
    recorded: Any,
    settings: Mapping[str, Any] | None,
    *,
    recorded_present: bool = False,
) -> int | None:
    """The run's frozen promotion threshold: the run record first (an explicit
    null is a frozen "no filter"), then the project setting, then None. A
    malformed recorded candidate warns and falls through to the setting; a
    malformed setting warns and falls back to no filter."""
    if recorded_present:
        if recorded is None:
            return None
        value = _int_at_least(recorded, 0, setting="promotion_risk_threshold")
        if value is not None:
            return value
    return _int_at_least(
        (settings or {}).get("promotion_risk_threshold"), 0,
        setting="promotion_risk_threshold")


def risk_is_promoted(risk: int, threshold: int | None) -> bool:
    """The ONE promotion comparison: inclusive; None or 0 means no filter."""
    return threshold is None or threshold <= 0 or risk >= threshold


def threat_is_promoted(
    record: Mapping[str, Any], threshold: int | None,
) -> bool:
    """Whether one stored threat file is promoted to a hunter. A threat whose
    combined risk is unreadable is never promoted."""
    risk = threat_risk(record)
    return risk is not None and risk_is_promoted(risk, threshold)


def threat_is_demoted(
    record: Mapping[str, Any], threshold: int | None,
) -> bool:
    """Whether one stored threat is DEMOTED: a readable, positive risk below an
    active floor. An unreadable risk is a refusal, never a demotion, so the
    audit still sees the corrupt artifact."""
    if threshold is None or threshold <= 0:
        return False
    risk = threat_risk(record)
    return risk is not None and risk > 0 and risk < threshold


@dataclass(frozen=True)
class UnitMeta:
    """One unit's queue metadata: the risk contribution orders the queue, the
    intake position breaks risk ties, the unit name breaks intake ties."""

    unit_name: str
    unit_id: str = ""
    risk: int = 0
    intake_position: int = UNKNOWN_INTAKE_POSITION


@dataclass(frozen=True)
class SyncFacts:
    """The storage- and registry-backed snapshot one decision ranges over.

    `modeller_live` is the first gate (the whole risk budget is consumed
    before any downstream dispatch). `hunts_in_graph` is the mid-graph signal -
    an idle hunter (graph ended) authors nothing more and does not hold the
    queue. `live_pod_hunts` are pods still executing (a consumed spec with no
    export yet). `spec_stems` maps a hunt key to ALL its spec stems (produced
    plus consumed, file-stem order) and `terminal_specs` is the exported set -
    the two facts the serial pod cursor reads.
    """

    modeller_live: bool = False
    hunts_in_graph: frozenset[str] = frozenset()
    live_pod_hunts: frozenset[str] = frozenset()
    spec_stems: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    terminal_specs: frozenset[tuple[str, str]] = frozenset()
    # The spec-lifecycle facts. `pending_spec_stems` are produced/ ratified
    # specs awaiting pod admission; `consumed_spec_stems` are the completion
    # set the pod exports must cover. `terminal_hunts` carries the hunter's
    # durable terminal marker for THIS run; `blocked_hunts` carries a stale
    # hypothesised, malformed, or un-finalized spec set that must not be
    # silently skipped.
    pending_spec_stems: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    consumed_spec_stems: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    terminal_hunts: frozenset[str] = frozenset()
    blocked_hunts: frozenset[str] = frozenset()
    # The hunts this run demotes by the promotion floor. A demoted hunt is
    # evidence, not work: its leftover spec folder is excluded from the pod
    # block and the spec inbox.
    demoted_hunts: frozenset[str] = frozenset()
    # The current unit's FULL rank-ordered hunt list, including hunts whose
    # threat files are already consumed. The fixed pod block needs the original
    # positions, so a done hunt cannot slide the next hunt into its place.
    unit_hunts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchState:
    """The derived per-unit phase snapshot (the ledger's cursor view).

    `phase` is `hunt` while the unit's hunter batch is still running,
    `pod` once the batch is terminal and one hunt's pod set is current
    (batched), `serial` for the strict cursor view, and `done` once every
    member is finished. `hunts` is the unit's hunt order (by threat rank) and
    `cursor` the first hunt that is not fully done; `pods`/`pod_cursor` are the
    cursor hunt's spec stems and the first stem without a durable export.
    """

    unit_name: str
    phase: str
    hunts: tuple[str, ...] = ()
    cursor: str | None = None
    # The current `batched` pod block: the fixed slice of rank-ordered hunts
    # whose pod sets dispatch together. Its first unfinished hunt is `cursor`.
    pod_batch: tuple[str, ...] = ()
    pods: tuple[str, ...] = ()
    pod_cursor: str | None = None


@dataclass
class PipelineSyncState:
    """The run-local sync ledger: the frozen mode, the intake-order source and
    the per-unit metadata cache. It holds NO durable state - the decision is
    re-derived from the stores every tick, so a resume rebuilds the queue and
    lands the cursor on the first unfinished phase."""

    mode: SyncMode
    intake_order: Sequence[str] | Callable[[], Sequence[str]] | None = None
    pod_batch_size: int = DEFAULT_POD_BATCH_SIZE
    _metas: dict[str, UnitMeta] = field(default_factory=dict)

    def intake_position(self, unit_id: str) -> int:
        """The unit's 1-based intake position, or the documented fallback for a
        unit the run record has not named."""
        order = self.intake_order
        if callable(order):
            try:
                order = order()
            except Exception:  # noqa: BLE001 - fail-open: unknown position
                return UNKNOWN_INTAKE_POSITION
        for position, candidate in enumerate(order or (), start=1):
            if candidate == unit_id:
                return position
        return UNKNOWN_INTAKE_POSITION

    def meta_for(self, unit_name: str, unit_id: str, *, risk: int) -> UnitMeta:
        """The cached unit metadata (the models freeze once the modeller
        settles, so the risk is computed once per unit)."""
        cached = self._metas.get(unit_name)
        meta = UnitMeta(
            unit_name=unit_name,
            unit_id=unit_id or (cached.unit_id if cached else ""),
            risk=risk,
            intake_position=self.intake_position(unit_id),
        )
        self._metas[unit_name] = meta
        return meta

    def cached(self, unit_name: str) -> UnitMeta | None:
        return self._metas.get(unit_name)


def unit_of_dispatch(dispatch_id: str) -> str:
    """The unit directory a dispatch id belongs to: `<unit_name>__<threat_id>` ->
    `<unit_name>`. The dispatch id is the store's own join, so the last `__`
    split is the exact inverse; a key without the separator is returned as-is
    (a foreign key never crashes the queue)."""
    head, separator, _tail = dispatch_id.rpartition("__")
    return head if separator else dispatch_id


def unit_of_item(item: ProducedItem) -> str | None:
    """The unit a produced item belongs to (the queue key). A threat item carries
    its unit name directly; a spec item's hunt key (the threat dispatch id) is one
    level down from the unit."""
    if isinstance(item, ThreatItem):
        return item.unit_name
    if isinstance(item, TestSpecItem):
        return unit_of_dispatch(item.hunt_key)
    return None


def hunt_rank(dispatch_id: str) -> int:
    """The threat rank of a dispatch id (`<unit>__threat-<n>` -> n); unranked keys
    sort last."""
    threat_id = dispatch_id.rpartition("__")[2]
    if threat_id.startswith("threat-"):
        try:
            return int(threat_id[len("threat-"):])
        except ValueError:
            return UNRANKED
    return UNRANKED


def order_units(units: Iterable[UnitMeta]) -> tuple[UnitMeta, ...]:
    """The dispatch queue order: risk contribution DESC, intake position ASC,
    unit name ASC (deterministic on every input)."""
    return tuple(sorted(
        units, key=lambda unit: (
            -unit.risk, unit.intake_position, unit.unit_name)))


def resolve_mode(
    recorded: str | None,
    settings: Mapping[str, Any] | None,
) -> SyncMode:
    """The run's frozen sync mode: the run record's own value first (a resume
    keeps the mode the run booted with), then the project setting, then the
    `batched` default. An unknown stored value falls through rather than
    failing the run."""
    values = {mode.value for mode in SyncMode}
    for candidate in (recorded, (settings or {}).get("pipeline_sync")):
        if isinstance(candidate, str) and candidate in values:
            return SyncMode(candidate)
    return DEFAULT_SYNC_MODE


def _queue_units(
    units: Sequence[UnitMeta], items: Sequence[ProducedItem],
) -> tuple[UnitMeta, ...]:
    """The ordered unit metas, with a default meta for every item unit the
    caller did not describe (fail-open: an unknown unit still queues)."""
    metas = {unit.unit_name: unit for unit in units}
    for item in items:
        name = unit_of_item(item)
        if name is not None and name not in metas:
            metas[name] = UnitMeta(unit_name=name)
    return order_units(metas.values())


def _pending_units(
    items: Sequence[ProducedItem], facts: SyncFacts,
) -> set[str]:
    """The units with live work: an item to dispatch, a hunt still mid-graph,
    or a pod still executing. An idle hunter is NOT here (it authors nothing
    more) and an already-terminal export is not either (the mover wrote it)."""
    pending = {unit_of_item(item) for item in items}
    pending |= {unit_of_dispatch(hunt) for hunt in facts.hunts_in_graph}
    pending |= {unit_of_dispatch(hunt) for hunt in facts.live_pod_hunts}
    pending |= {unit_of_dispatch(hunt) for hunt in facts.blocked_hunts}
    pending.discard(None)
    return pending


def decide(
    mode: SyncMode,
    items: Sequence[ProducedItem],
    units: Sequence[UnitMeta],
    facts: SyncFacts,
    *,
    pod_batch_size: int = DEFAULT_POD_BATCH_SIZE,
) -> frozenset[str]:
    """The items admissible NOW, as `message_id`s (the pure policy decision).

    `parallel` admits every item. `batched`/`serial` hold everything while the
    modeller pass is live, then work the queue one unit at a time:
    `batched` admits the current unit's whole hunter batch, and its pods only
    once no threat file and no mid-graph hunt remains; the pods dispatch in
    fixed blocks of `pod_batch_size` hunts in rank order. `serial` admits only
    the cursor hunt (or, once it is terminal, its next pod in stem order), and
    only after every earlier hunt is fully done (terminal AND all its pods
    exported).
    """
    items = tuple(items)
    if not items:
        return frozenset()
    if mode is SyncMode.PARALLEL:
        return frozenset(item.message_id for item in items)
    if facts.modeller_live:
        return frozenset()

    current = current_unit(items, units, facts)
    if current is None:
        return frozenset()

    if mode is SyncMode.SERIAL:
        return _decide_serial(
            items, current, facts, pod_batch_size=pod_batch_size)
    return _decide_batched(
        items, current, facts, pod_batch_size=pod_batch_size)


def batch_state(
    mode: SyncMode,
    current: str,
    items: Sequence[ProducedItem],
    facts: SyncFacts,
    *,
    pod_batch_size: int = DEFAULT_POD_BATCH_SIZE,
) -> BatchState:
    """The unit's derived phase state: `hunt` while the hunter batch is
    unfinished, `pod` for the first fixed block of hunts whose pod set is not
    fully exported, the ordered hunts + cursor + pod block for `batched`, the
    strict cursor view for `serial`, `done` when nothing is left."""
    unit_items = [item for item in items if unit_of_item(item) == current]
    size = max(1, int(pod_batch_size))
    if mode is SyncMode.BATCHED:
        threat_hunts = {
            item.dispatch_id for item in unit_items
            if isinstance(item, ThreatItem)
        }
        spec_hunts = {
            item.hunt_key for item in unit_items
            if isinstance(item, TestSpecItem)
        }
        graph_hunts = {
            hunt for hunt in facts.hunts_in_graph
            if unit_of_dispatch(hunt) == current
        }
        pod_hunts = {
            hunt for hunt in facts.live_pod_hunts
            if unit_of_dispatch(hunt) == current
        }
        blocked_hunts = {
            hunt for hunt in facts.blocked_hunts
            if unit_of_dispatch(hunt) == current
        }
        hunts = tuple(sorted(
            set(facts.unit_hunts.get(current, ()))
            | threat_hunts | spec_hunts | graph_hunts | pod_hunts | blocked_hunts,
            key=hunt_rank,
        ))
        hunts = tuple(
            hunt for hunt in hunts if hunt not in facts.demoted_hunts)
        # The hunter phase ends only when every hunt of the unit is terminal:
        # a produced threat file or a live graph is obvious work, and a hunt
        # that ended without a terminal marker is blocked, never a silent pass
        # to the pod phase.
        hunters_ready = (
            not threat_hunts
            and not graph_hunts
            and all(
                hunt in facts.terminal_hunts
                and hunt not in facts.blocked_hunts
                for hunt in hunts
            )
        )
        if not hunters_ready:
            return BatchState(unit_name=current, phase="hunt", hunts=hunts)
        pending = [
            index for index, hunt in enumerate(hunts)
            if not _hunt_done(hunt, threat_hunts, facts)
        ]
        if not pending:
            return BatchState(unit_name=current, phase="done", hunts=hunts)
        first = pending[0]
        start = (first // size) * size
        pod_batch = hunts[start:start + size]
        cursor = hunts[first]
        pods = tuple(facts.spec_stems.get(cursor, ()))
        pod_cursor = next(
            (stem for stem in pods if (cursor, stem) not in facts.terminal_specs),
            None,
        )
        return BatchState(
            unit_name=current, phase="pod", hunts=hunts, cursor=cursor,
            pod_batch=pod_batch, pods=pods, pod_cursor=pod_cursor,
        )

    threat_hunts = {
        item.dispatch_id for item in unit_items
        if isinstance(item, ThreatItem)
    }
    spec_hunts = {
        item.hunt_key for item in unit_items if isinstance(item, TestSpecItem)
    }
    graph_hunts = {
        hunt for hunt in facts.hunts_in_graph
        if unit_of_dispatch(hunt) == current
    }
    pod_hunts = {
        hunt for hunt in facts.live_pod_hunts
        if unit_of_dispatch(hunt) == current
    }
    blocked_hunts = {
        hunt for hunt in facts.blocked_hunts
        if unit_of_dispatch(hunt) == current
    }
    hunts = tuple(sorted(
        set(facts.unit_hunts.get(current, ()))
        | threat_hunts | spec_hunts | graph_hunts | pod_hunts | blocked_hunts,
        key=hunt_rank,
    ))
    hunts = tuple(
        hunt for hunt in hunts if hunt not in facts.demoted_hunts)
    cursor = next(
        (hunt for hunt in hunts if not _hunt_done(hunt, threat_hunts, facts)),
        None,
    )
    if cursor is None:
        return BatchState(unit_name=current, phase="done", hunts=hunts)
    pods = tuple(facts.spec_stems.get(cursor, ()))
    pod_cursor = next(
        (stem for stem in pods if (cursor, stem) not in facts.terminal_specs),
        None,
    )
    return BatchState(
        unit_name=current, phase="serial", hunts=hunts, cursor=cursor,
        pods=pods, pod_cursor=pod_cursor,
    )


def current_unit(
    items: Sequence[ProducedItem],
    units: Sequence[UnitMeta],
    facts: SyncFacts,
) -> str | None:
    """The queue's current unit: the first unit in risk order that still has
    live work (an item, a mid-graph hunt, or an executing pod). None when the
    queue is drained."""
    ordered = _queue_units(units, items)
    pending = _pending_units(items, facts)
    return next(
        (unit.unit_name for unit in ordered if unit.unit_name in pending), None)


def _decide_batched(
    items: Sequence[ProducedItem],
    current: str,
    facts: SyncFacts,
    *,
    pod_batch_size: int = DEFAULT_POD_BATCH_SIZE,
) -> frozenset[str]:
    """One unit's phase at a time: the whole hunter batch while the hunt phase
    is active, then the current fixed block's pod sets. The next block waits
    until every pod of every hunt in the current block carries a durable export.
    """
    state = batch_state(
        SyncMode.BATCHED, current, items, facts,
        pod_batch_size=pod_batch_size,
    )
    unit_items = [item for item in items if unit_of_item(item) == current]
    if state.phase == "hunt":
        return frozenset(
            item.message_id for item in unit_items
            if isinstance(item, ThreatItem))
    if state.phase != "pod" or not state.pod_batch:
        return frozenset()
    block = frozenset(state.pod_batch)
    return frozenset(
        item.message_id for item in unit_items
        if isinstance(item, TestSpecItem)
        and item.hunt_key in block
        and (item.hunt_key, item.spec_file) not in facts.terminal_specs
    )


def _decide_serial(
    items: Sequence[ProducedItem],
    current: str,
    facts: SyncFacts,
    *,
    pod_batch_size: int = DEFAULT_POD_BATCH_SIZE,
) -> frozenset[str]:
    """The cursor: the pending threat file of the cursor hunt is the hunter;
    once that hunt is terminal, its next pod in stem order; a hunt still
    mid-graph admits nothing. The batch size is ignored: serial stays one
    agent at a time."""
    state = batch_state(
        SyncMode.SERIAL, current, items, facts,
        pod_batch_size=pod_batch_size,
    )
    if state.cursor is None:
        return frozenset()
    cursor = state.cursor
    threat_item = next(
        (item for item in items
         if isinstance(item, ThreatItem) and item.dispatch_id == cursor),
        None,
    )
    if threat_item is not None:
        return frozenset({threat_item.message_id})
    if cursor in facts.hunts_in_graph:
        # The hunt is still authoring its spec set: no pod yet.
        return frozenset()
    if cursor not in facts.terminal_hunts:
        # The hunter has not closed its set. A pod must never start from a
        # draft or from an un-finalized hunt, even when the graph has ended.
        return frozenset()
    if state.pod_cursor is None:
        return frozenset()
    match = next(
        (item for item in items
         if isinstance(item, TestSpecItem)
         and item.hunt_key == cursor and item.spec_file == state.pod_cursor),
        None,
    )
    return frozenset({match.message_id}) if match is not None else frozenset()


def _hunt_done(
    hunt: str, threat_hunts: set[str], facts: SyncFacts,
) -> bool:
    """A hunt is fully done when it has no pending threat file, is not mid-graph,
    has no executing pod, and every one of its specs carries a terminal
    export. An empty spec set (a zero-spec hunt) is therefore done as soon as
    the hunt itself is terminal."""
    if hunt in threat_hunts:
        return False
    if hunt in facts.hunts_in_graph:
        return False
    if hunt in facts.live_pod_hunts:
        return False
    if hunt in facts.blocked_hunts:
        return False
    if hunt not in facts.terminal_hunts:
        return False
    if facts.pending_spec_stems.get(hunt):
        return False
    return all(
        (hunt, stem) in facts.terminal_specs
        for stem in facts.consumed_spec_stems.get(hunt, ())
    )


def _threat_weight(threat: Any) -> int:
    """One model threat's combined risk weight.

    The persisted threat carries the store-computed `risk`; a legacy or foreign
    model without it falls back to the likelihood weight. An unknown likelihood
    contributes nothing (never a crash - the queue still runs)."""
    if not isinstance(threat, Mapping):
        return 0
    raw = threat.get("risk")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    try:
        return RISK_WEIGHTS[Likelihood(threat.get("likelihood"))]
    except (ValueError, KeyError):
        return 0


def _spec_unit_id(body: Any) -> str:
    """The unit identity a stored spec body names.

    The live body carries `target_identity.unit_id`; the legacy/gate fixtures
    use `target.unit_id`; `provenance.unit_id` is the last fallback. Empty for
    an absent or untyped body."""
    if not isinstance(body, Mapping):
        return ""
    for key in ("target_identity", "target"):
        target = body.get(key)
        if isinstance(target, Mapping) and target.get("unit_id"):
            return str(target["unit_id"])
    provenance = body.get("provenance")
    if isinstance(provenance, Mapping) and provenance.get("unit_id"):
        return str(provenance["unit_id"])
    return ""


class RunSyncGate:
    """The impure adapter behind the sync policy: one per run, created by the
    run bootstrap and consulted by the mover tick.

    It gathers the storage-backed facts (`SyncFacts`) from the stores and the
    caller-supplied live-session set, orders the units (model risk contribution,
    run-record intake position), and applies the pure `decide`. It keeps only
    the per-unit metadata cache (the models are frozen once the modeller
    settles); every gate decision itself is re-derived, so a resumed run
    rebuilds the same queue with no persisted ledger.
    """

    def __init__(
        self,
        *,
        mode: SyncMode,
        project_id: str,
        run_id: str,
        threat_store: Any = None,
        hunter_store: Any = None,
        pod_store: Any = None,
        intake_order: Sequence[str] | Callable[[], Sequence[str]] | None = None,
        pod_batch_size: int = DEFAULT_POD_BATCH_SIZE,
        promotion_risk_threshold: int | None = None,
    ) -> None:
        self.state = PipelineSyncState(
            mode=SyncMode(mode), intake_order=intake_order,
            pod_batch_size=max(1, int(pod_batch_size)),
        )
        self.project_id = project_id
        self.run_id = run_id
        self.threat_store = threat_store
        self.hunter_store = hunter_store
        self.pod_store = pod_store
        self.promotion_risk_threshold = promotion_risk_threshold
        # The unit models freeze at COMPLETED, so one COMPLETED read per unit
        # per gate is enough. A pre-COMPLETED or transiently unreadable model is
        # not cached: the next call re-reads it.
        self._models: dict[str, Mapping[str, Any]] = {}
        self._unit_ids: dict[str, str] = {}

    def _read_model(self, unit_id: str) -> Mapping[str, Any] | None:
        cached = self._models.get(unit_id)
        if cached is not None:
            return cached
        if self.threat_store is None:
            return None
        try:
            model = self.threat_store.read_model(self.project_id, unit_id)
        except Exception:  # noqa: BLE001 - fail-open: the queue still runs
            return None
        if isinstance(model, Mapping) and model.get("state") == "COMPLETED":
            self._models[unit_id] = model
            return model
        return model if isinstance(model, Mapping) else None

    @property
    def mode(self) -> SyncMode:
        return self.state.mode

    def filter(
        self,
        items: Sequence[ProducedItem],
        *,
        live_session_ids: Iterable[str] = (),
        hunts_in_graph: Iterable[str] = (),
    ) -> tuple[ProducedItem, ...]:
        """The admissible subset of `items`, in their original order. A no-op
        for `parallel` (the historical behaviour)."""
        items = tuple(items)
        if not items or self.mode is SyncMode.PARALLEL:
            return items
        live = frozenset(live_session_ids)
        facts = self._base_facts(live, hunts_in_graph)
        # The lifecycle facts must land before the queue is built: a stale or
        # malformed hunt is pending work even when it contributes no produced
        # item, so its unit must stay current and block a silent skip. Both
        # batched and serial read the per-hunt pod cursor from the same facts.
        facts = self._lifecycle_facts(facts)
        units = self._units(items, facts)
        facts = self._pod_cursor_facts(items, units, facts)
        admitted = decide(
            self.mode, items, units, facts,
            pod_batch_size=self.state.pod_batch_size,
        )
        return tuple(item for item in items if item.message_id in admitted)

    # -- the fact reads ---------------------------------------------------------

    def _base_facts(
        self, live: frozenset[str], hunts_in_graph: Iterable[str],
    ) -> SyncFacts:
        prefix = f"hunting:{self.run_id}:pod:"
        pod_hunts: set[str] = set()
        for session_id in live:
            if not session_id.startswith(prefix):
                continue
            rest = session_id[len(prefix):]
            hunt = rest.rsplit(":", 1)[0] if ":" in rest else rest
            if hunt:
                pod_hunts.add(hunt)
        return SyncFacts(
            modeller_live=threat_modeller_session_id(self.run_id) in live,
            hunts_in_graph=frozenset(hunts_in_graph),
            live_pod_hunts=frozenset(pod_hunts),
        )

    def _units(
        self, items: Sequence[ProducedItem], facts: SyncFacts,
    ) -> tuple[UnitMeta, ...]:
        """The unit metas for the tick: the item units plus the units only
        visible through a live pod or a mid-graph hunt (a consumed threat search
        finds no produced item for it). The per-unit metadata (risk) is cached
        for the run's lifetime - models freeze once the modeller settles - and
        a session-only unit's unit id is recovered from its stored spec body."""
        metas: dict[str, UnitMeta] = {}
        for item in items:
            name = unit_of_item(item)
            if name is None or name in metas:
                continue
            metas[name] = self._meta_for(item, name)
        session_hunts = (
            set(facts.live_pod_hunts)
            | set(facts.hunts_in_graph)
            | set(facts.blocked_hunts)
        )
        for hunt in session_hunts:
            name = unit_of_dispatch(hunt)
            if name in metas:
                continue
            cached = self.state.cached(name)
            if cached is not None:
                metas[name] = cached
                continue
            unit_id = self._unit_id_for_hunt(hunt)
            risk = self._risk(unit_id)
            if hunt in facts.blocked_hunts and not unit_id:
                # Unknown identity or unreadable spec: fail closed. The unit
                # must stay current so the stale hunt is surfaced, never skipped.
                risk = BLOCKED_RISK
            metas[name] = self.state.meta_for(name, unit_id, risk=risk)
        return tuple(metas.values())

    def _unit_id_for_hunt(self, hunt_key: str) -> str:
        """The unit identity a hunt's stored spec body names, when the hunt is
        visible only through a session. Fail-open to the empty id. A resolved
        id is cached per gate: the spec body is immutable once written."""
        cached = self._unit_ids.get(hunt_key)
        if cached is not None:
            return cached
        if self.hunter_store is None:
            return ""
        for stem in sorted(self._stems(hunt_key)):
            for side in ("produced", "consumed"):
                try:
                    body = self.hunter_store.read_spec(
                        self.project_id, hunt_key, stem, side=side)
                except Exception:  # noqa: BLE001 - fail-open per record
                    body = None
                unit_id = _spec_unit_id(body)
                if unit_id:
                    self._unit_ids[hunt_key] = unit_id
                    return unit_id
        return ""

    def _meta_for(self, item: ProducedItem, unit_name: str) -> UnitMeta:
        unit_id = (
            item.unit_id if isinstance(item, ThreatItem)
            else _spec_unit_id(item.spec)
        )
        cached = self.state.cached(unit_name)
        if cached is not None and (cached.unit_id == unit_id or not unit_id):
            return cached
        return self.state.meta_for(
            unit_name,
            unit_id or (cached.unit_id if cached else ""),
            risk=cached.risk if cached and cached.unit_id == unit_id
            else self._risk(unit_id),
        )

    def _risk(self, unit_id: str) -> int:
        """The unit's risk contribution: the summed threat likelihood weights of
        its model document (the run record's `model_sum` figure). Fail-open:
        an unreadable or unknown model contributes zero."""
        if not unit_id or self.threat_store is None:
            return 0
        model = self._read_model(unit_id)
        threats = (model or {}).get("threats") or ()
        return sum(_threat_weight(threat) for threat in threats)

    def _intake_position(self, unit_id: str) -> int:
        order = self.intake_order
        if callable(order):
            try:
                order = order()
            except Exception:  # noqa: BLE001 - fail-open: unknown position
                return UNKNOWN_INTAKE_POSITION
        for position, candidate in enumerate(order or (), start=1):
            if candidate == unit_id:
                return position
        return UNKNOWN_INTAKE_POSITION

    def _lifecycle_facts(self, facts: SyncFacts) -> SyncFacts:
        """The hunter-side lifecycle facts for every hunt on disk.

        A hunt is terminal only when its durable terminal marker names THIS
        run. A hunt with no marker and no live graph or pod is stale: it is
        blocked, never skipped. A marker that records a status outside
        `ratified`/`dropped` is blocked too. This is the gate-side half of the
        lifecycle contract; the upstream controller ticket owns prevention and
        re-prompting of stale drafts.
        """
        terminal: set[str] = set()
        blocked: set[str] = set()
        if self.hunter_store is None:
            return facts
        try:
            hunt_keys = self.hunter_store.list_hunt_keys(self.project_id)
        except Exception:  # noqa: BLE001 - a read failure is not a false done
            return facts
        live = set(facts.hunts_in_graph) | set(facts.live_pod_hunts)
        demoted = set(self._demoted_hunts())
        for hunt in hunt_keys:
            marker = self._terminal_marker(hunt)
            if marker is not None:
                terminal.add(hunt)
                statuses = marker.get("spec_statuses") or {}
                if any(
                    status not in ("ratified", "dropped")
                    for status in statuses.values()
                ):
                    blocked.add(hunt)
                if self._spec_set_blocked(hunt):
                    blocked.add(hunt)
                continue
            if self._hunt_is_demoted(hunt, frozenset(demoted)):
                # A threat below the promotion floor is evidence, not work:
                # its stale spec folder must not block the promoted queue,
                # even after the unit model moved to consumed/.
                demoted.add(hunt)
                continue
            if hunt in live:
                continue
            blocked.add(hunt)
        return replace(
            facts,
            terminal_hunts=frozenset(terminal),
            blocked_hunts=frozenset(blocked),
            demoted_hunts=frozenset(demoted),
        )

    def _terminal_marker(self, hunt_key: str) -> dict | None:
        """The terminal marker for THIS run, or None.

        A marker from another run is not this run's completion proof. A corrupt
        marker is treated as absent by the caller, which marks the hunt
        blocked; it is never a false terminal."""
        reader = getattr(self.hunter_store, "read_terminal_set", None)
        if reader is None:
            return None
        try:
            marker = reader(self.project_id, hunt_key)
        except Exception:  # noqa: BLE001 - corrupt terminal is not completion
            return None
        if not isinstance(marker, Mapping):
            return None
        if str(marker.get("run_id") or "") != self.run_id:
            return None
        return dict(marker)

    def _demoted_hunts(self) -> frozenset[str]:
        """The produced hunts whose threat is below the frozen promotion floor.

        A demoted threat is evidence, not work. Its stale spec folder must not
        block the promoted queue or the completion audit. The read is
        run-scoped; a failed read demotes nothing (fail-open, the existing
        stale-hunt fail-closed rule still applies)."""
        threshold = self.promotion_risk_threshold
        if threshold is None or threshold <= 0 or self.threat_store is None:
            return frozenset()
        reader = getattr(self.threat_store, "read_produced_threats", None)
        if reader is None:
            return frozenset()
        try:
            entries = reader(self.project_id)
        except Exception:  # noqa: BLE001 - a read failure demotes nothing
            return frozenset()
        demoted: set[str] = set()
        for entry in entries:
            if entry.get("run_id") != self.run_id:
                continue
            unit_name = str(entry.get("unit_name") or "")
            for threat in entry.get("threats") or ():
                if not isinstance(threat, Mapping):
                    continue
                threat_id = str(threat.get("threat_id") or "")
                if not threat_id:
                    continue
                if threat_is_demoted(
                        threat.get("record") or {}, threshold):
                    demoted.add(f"{unit_name}__{threat_id}")
        return frozenset(demoted)

    def demoted_hunts(self) -> frozenset[str]:
        """Every hunt this run DEMOTES, including a hunt whose unit model has
        already moved to `consumed/`.

        The produced read covers a produced model. A leftover spec folder is
        resolved through `_hunt_is_demoted`, which reads the model from
        produced/ or consumed/. A demoted hunt's spec is evidence, not work;
        the mover drops it from the spec inbox and the gate excludes it from
        the pod block."""
        threshold = self.promotion_risk_threshold
        if threshold is None or threshold <= 0:
            return frozenset()
        demoted = set(self._demoted_hunts())
        if self.hunter_store is None:
            return frozenset(demoted)
        try:
            hunt_keys = self.hunter_store.list_hunt_keys(self.project_id)
        except Exception:  # noqa: BLE001 - a read failure demotes nothing extra
            return frozenset(demoted)
        for hunt in hunt_keys:
            if hunt in demoted:
                continue
            if self._hunt_is_demoted(hunt, frozenset(demoted)):
                demoted.add(hunt)
        return frozenset(demoted)

    def _hunt_is_demoted(
        self, hunt_key: str, demoted: frozenset[str],
    ) -> bool:
        """Whether ONE hunt is a demoted threat, even after its unit model moved
        to consumed/.

        The produced read cannot see a demoted file once the model document has
        moved, so the audit resolves the unit id from a leftover spec body (or
        the known unit metadata), reads the model from produced/ or consumed/,
        and checks the threat's risk. A model from another run never demotes
        this run's hunt."""
        if hunt_key in demoted:
            return True
        threshold = self.promotion_risk_threshold
        if threshold is None or threshold <= 0 or self.threat_store is None:
            return False
        unit_id = self._unit_id_for_hunt(hunt_key)
        if not unit_id:
            cached = self.state.cached(unit_of_dispatch(hunt_key))
            unit_id = cached.unit_id if cached is not None else ""
        if not unit_id:
            return False
        model = self._read_model(unit_id)
        if not isinstance(model, Mapping):
            return False
        if model.get("state") != "COMPLETED":
            return False
        if str(model.get("run_id") or "") != self.run_id:
            return False
        threat_id = hunt_key.rpartition("__")[2]
        for threat in model.get("threats") or ():
            if not isinstance(threat, Mapping):
                continue
            if str(threat.get("id") or "") == threat_id:
                return threat_is_demoted(threat, threshold)
        return False

    def _pod_cursor_facts(
        self,
        items: Sequence[ProducedItem],
        units: Sequence[UnitMeta],
        facts: SyncFacts,
    ) -> SyncFacts:
        """The per-hunt pod cursor facts: pending (produced) pod specs, the
        consumed completion set, and the durable exports. Batched reads them
        to gate one hunt's pod set at a time; serial reads them to gate one
        pod at a time. Only the current unit needs its per-spec facts this
        tick."""
        current = current_unit(items, units, facts)
        if current is None:
            return facts
        hunts: set[str] = set()
        for item in items:
            if unit_of_item(item) != current:
                continue
            if isinstance(item, ThreatItem):
                hunts.add(item.dispatch_id)
            elif isinstance(item, TestSpecItem):
                hunts.add(item.hunt_key)
        hunts |= {
            hunt for hunt in facts.hunts_in_graph
            if unit_of_dispatch(hunt) == current
        }
        hunts |= {
            hunt for hunt in facts.live_pod_hunts
            if unit_of_dispatch(hunt) == current
        }
        hunts -= set(facts.demoted_hunts)
        # The current unit's FULL promoted hunt order, including hunts whose
        # threat files are already consumed. The fixed pod block needs the
        # original positions, so a done hunt cannot slide the next hunt in.
        # Only a DISPATCHABLE threat is a hunt: a zero-risk threat has no
        # threat file (S2 8.3) and a threat the mover refused has no observable
        # artifact, so neither may hold the pod phase.
        unit_hunts: dict[str, tuple[str, ...]] = {}
        meta = next((unit for unit in units if unit.unit_name == current), None)
        if meta is not None and meta.unit_id and self.threat_store is not None:
            observed = (
                hunts
                | set(facts.terminal_hunts)
                | set(facts.blocked_hunts)
            )
            model = self._read_model(meta.unit_id)
            if (
                isinstance(model, Mapping)
                and model.get("state") == "COMPLETED"
            ):
                ranked: list[str] = []
                for threat in model.get("threats") or ():
                    if not isinstance(threat, Mapping):
                        continue
                    threat_id = str(threat.get("id") or "")
                    if not threat_id:
                        continue
                    risk = _threat_weight(threat)
                    if risk <= 0:
                        # A zero-risk threat is stored but never written as a
                        # threat file: it can never become a hunt.
                        continue
                    if not risk_is_promoted(
                            risk, self.promotion_risk_threshold):
                        continue
                    hunt_key = f"{current}__{threat_id}"
                    if hunt_key not in observed:
                        # A refused or otherwise unobservable threat is not a
                        # hunt and must not hold the pod phase.
                        continue
                    ranked.append(hunt_key)
                if ranked:
                    unit_hunts[current] = tuple(ranked)
                    hunts |= set(ranked)
        stems: dict[str, tuple[str, ...]] = {}
        pending: dict[str, tuple[str, ...]] = {}
        consumed: dict[str, tuple[str, ...]] = {}
        terminal: set[tuple[str, str]] = set()
        for hunt in hunts:
            produced = self._ratified_stems(hunt, "produced")
            consumed_stems = self._ratified_stems(hunt, "consumed")
            pending[hunt] = produced
            consumed[hunt] = consumed_stems
            # The dispatch cursor considers both sides: a produced ratified
            # spec is a pending pod move, a consumed one is the completion set.
            stems[hunt] = tuple(sorted(set(produced) | set(consumed_stems)))
            for stem in consumed_stems:
                if self._export_exists(stem):
                    terminal.add((hunt, stem))
        return replace(
            facts,
            spec_stems=stems,
            pending_spec_stems=pending,
            consumed_spec_stems=consumed,
            terminal_specs=frozenset(terminal),
            unit_hunts=unit_hunts,
        )

    def _side_stems(self, hunt_key: str, side: str) -> tuple[str, ...]:
        reader = getattr(self.hunter_store, f"{side}_spec_files", None)
        if reader is None:
            return ()
        try:
            return tuple(reader(self.project_id, hunt_key))
        except Exception:  # noqa: BLE001 - a read failure is not a false done
            return ()

    def _stems(self, hunt_key: str) -> set[str]:
        """Both sides' stems, used only for unit-id recovery."""
        return set(self._side_stems(hunt_key, "produced")) | set(
            self._side_stems(hunt_key, "consumed"))

    def _spec_set_blocked(self, hunt_key: str) -> bool:
        """Whether any stored spec is outside the terminal lifecycle shape.

        Produced `ratified` (pending admission) and produced `dropped`
        (terminal by decision) are valid. A produced `hypothesised` draft, any
        consumed non-ratified body, or an unreadable/missing body is blocked.
        This check runs even with a terminal marker: a late/direct write must
        not hide behind an older marker.
        """
        for side in ("produced", "consumed"):
            for stem in self._side_stems(hunt_key, side):
                status = self._spec_status(hunt_key, stem, side)
                if side == "consumed" and status == "malformed":
                    # The malformed fail-safe: a consumed unreadable body is
                    # terminal once the pod wrote its export. Without one it is
                    # a real stall and stays an anomaly.
                    if self._export_exists(stem):
                        continue
                    return True
                if status not in ("ratified", "dropped"):
                    return True
                if side == "consumed" and status == "dropped":
                    return True
        return False

    def _ratified_stems(self, hunt_key: str, side: str) -> tuple[str, ...]:
        """The dispatchable stems on one side.

        A produced `ratified` body is dispatchable, and so is a MALFORMED body:
        the malformed fail-safe dispatches it so the pod renders what it can and
        writes a PodExport, instead of leaving it produced to halt the queue. A
        non-ratified parseable body is a draft and is not dispatchable."""
        stems: list[str] = []
        for stem in self._side_stems(hunt_key, side):
            status = self._spec_status(hunt_key, stem, side)
            if status in (SPEC_DISPATCH_STATUS, "malformed"):
                stems.append(stem)
        return tuple(stems)

    def _spec_run_id(self, hunt_key: str, spec_id: str, side: str) -> str:
        """The run id a spec's typed provenance names, or empty."""
        try:
            body = self.hunter_store.read_spec(
                self.project_id, hunt_key, spec_id, side=side)
        except Exception:  # noqa: BLE001 - unattributable
            return ""
        if not isinstance(body, Mapping):
            return ""
        provenance = body.get("provenance")
        if not isinstance(provenance, Mapping):
            return ""
        return str(provenance.get("run_id") or "")

    def _spec_status(self, hunt_key: str, spec_id: str, side: str) -> str:
        """The persisted status, or a sentinel for a missing/malformed body.

        The surfer must be able to read the state. A missing or unreadable
        body is `malformed`, never silently treated as dispatchable; the
        upstream write gate owns prevention of this state.
        """
        try:
            body = self.hunter_store.read_spec(
                self.project_id, hunt_key, spec_id, side=side)
        except Exception:  # noqa: BLE001 - malformed body
            return "malformed"
        if not isinstance(body, Mapping):
            return "malformed"
        status = body.get("status")
        return str(status) if status else "malformed"

    def _export_exists(self, spec_id: str) -> bool:
        if self.pod_store is None:
            return False
        try:
            return bool(self.pod_store.read_pod_export(spec_id, self.run_id))
        except Exception:  # noqa: BLE001 - fail-open: a corrupt export is not terminal
            return False


def hunting_artifacts_terminal(
    project_id: str,
    run_id: str,
    *,
    hunter_store: Any,
    pod_store: Any,
    threat_store: Any = None,
    promotion_risk_threshold: int | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Hard completion audit over every CURRENT-RUN hunting artifact.

    This is the quiesce fail-safe. It does not ask the mover whether it has a
    dispatchable item; it asks whether any artifact of this run is still in a
    non-terminal lifecycle state. A malformed/unparsable body therefore blocks
    completion even though the mover cannot turn it into a produced item.

    Current-run attribution is explicit: a hunt belongs to the run when its
    terminal marker names the run, when one of its specs carries the run id, or
    when a threat-model threat of the run names its dispatch key. Foreign-run and
    legacy unattributed hunts are ignored, never treated as this run's work.
    """
    gate = RunSyncGate(
        mode=SyncMode.SERIAL,
        project_id=project_id,
        run_id=run_id,
        threat_store=threat_store,
        hunter_store=hunter_store,
        pod_store=pod_store,
        promotion_risk_threshold=promotion_risk_threshold,
    )
    reasons: list[str] = []
    current_hunts: set[str] = set()
    demoted = gate._demoted_hunts()

    if threat_store is not None:
        for reader_name, side in (
            ("read_produced_threats", "produced"),
            ("read_consumed_threats", "consumed"),
        ):
            reader = getattr(threat_store, reader_name, None)
            if reader is None:
                continue
            try:
                entries = reader(project_id)
            except Exception as exc:  # noqa: BLE001 - cannot prove completion
                reasons.append(f"threat {side} read failed: {exc}")
                continue
            for entry in entries:
                if str(entry.get("run_id") or "") != run_id:
                    continue
                unit_name = str(entry.get("unit_name") or "")
                for malformed in entry.get("malformed_threats") or ():
                    threat_id = str(malformed.get("threat_id") or "")
                    if not threat_id:
                        continue
                    hunt_key = f"{unit_name}__{threat_id}"
                    if side == "produced" and hunt_key in demoted:
                        continue
                    current_hunts.add(hunt_key)
                    reasons.append(
                        f"{hunt_key}: malformed threat body")
                for threat in entry.get("threats") or ():
                    threat_id = str(threat.get("threat_id") or "")
                    if not threat_id:
                        continue
                    hunt_key = f"{unit_name}__{threat_id}"
                    if side == "produced" and hunt_key in demoted:
                        continue
                    current_hunts.add(hunt_key)

    if hunter_store is None:
        return False, ("hunter store unavailable",)

    try:
        hunt_keys = hunter_store.list_hunt_keys(project_id)
    except Exception as exc:  # noqa: BLE001 - cannot prove completion
        return False, (f"hunt inventory read failed: {exc}",)

    for hunt in hunt_keys:
        if gate._hunt_is_demoted(hunt, demoted):
            # A demoted threat is evidence, not work: its stale spec folder
            # must not block the run terminal, even after the unit model moved.
            continue
        marker = gate._terminal_marker(hunt)
        if marker is not None:
            current_hunts.add(hunt)
        for side in ("produced", "consumed"):
            for stem in gate._side_stems(hunt, side):
                if gate._spec_run_id(hunt, stem, side) == run_id:
                    current_hunts.add(hunt)

    for hunt in sorted(current_hunts):
        marker = gate._terminal_marker(hunt)
        if marker is None:
            reasons.append(f"{hunt}: no terminal marker")
        else:
            for status in (marker.get("spec_statuses") or {}).values():
                if status not in ("ratified", "dropped"):
                    reasons.append(f"{hunt}: terminal marker carries {status!r}")
        for stem in gate._side_stems(hunt, "produced"):
            status = gate._spec_status(hunt, stem, "produced")
            if status == "dropped":
                continue
            if status == "ratified":
                reasons.append(f"{hunt}/{stem}: produced ratified spec pending")
            else:
                reasons.append(f"{hunt}/{stem}: produced {status} spec")
        for stem in gate._side_stems(hunt, "consumed"):
            status = gate._spec_status(hunt, stem, "consumed")
            if status == "malformed":
                # The malformed fail-safe: the export is the only completion
                # fact an unreadable consumed body can offer.
                if not gate._export_exists(stem):
                    reasons.append(
                        f"{hunt}/{stem}: consumed malformed spec has no PodExport")
                continue
            if status != "ratified":
                reasons.append(f"{hunt}/{stem}: consumed {status} spec")
                continue
            if not gate._export_exists(stem):
                reasons.append(f"{hunt}/{stem}: consumed spec has no PodExport")

    return (not reasons, tuple(reasons))


def make_sync_gate(
    mode: SyncMode, **kwargs: Any,
) -> RunSyncGate | None:
    """The run bootstrap's factory: a gate for the phase-serialising modes, and
    None for `parallel` (the mover keeps its historical behaviour byte for
    byte)."""
    if SyncMode(mode) is SyncMode.PARALLEL:
        return None
    return RunSyncGate(mode=mode, **kwargs)


__all__ = [
    "BatchState",
    "DEFAULT_POD_BATCH_SIZE",
    "DEFAULT_SYNC_MODE",
    "PipelineSyncState",
    "RunSyncGate",
    "SyncFacts",
    "SyncMode",
    "UNRANKED",
    "UNKNOWN_INTAKE_POSITION",
    "UnitMeta",
    "batch_state",
    "current_unit",
    "decide",
    "hunt_rank",
    "hunting_artifacts_terminal",
    "make_sync_gate",
    "order_units",
    "resolve_mode",
    "resolve_pod_batch_size",
    "resolve_promotion_risk_threshold",
    "risk_is_promoted",
    "threat_is_demoted",
    "threat_is_promoted",
    "unit_of_dispatch",
    "unit_of_item",
]
