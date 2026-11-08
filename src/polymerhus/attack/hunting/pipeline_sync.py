"""The hunting pipeline sync policy (`hunting_pipeline_sync`, ADR
`docs/design/hunting-pipeline-sync-adr.md`, 2026-10-22; amended 2026-10-31 for
the CVSS 4.0 risk score and the GLOBAL threat queue).

The project-level mode governs WHEN the pipeline phases may dispatch:

- `parallel` - the historical behaviour: every produced item the mover finds is
  dispatched as it appears (the S1 7.3 interleave stays live);
- `batched` - phase barriers only: the modeller pass settles first, then the
  run's GLOBAL threat queue is worked in risk order - the current threat's
  hunter, then its pods once the hunter is terminal, in fixed blocks of
  `pod_batch_size` threats;
- `serial` - the same global queue strictly one agent at a time: hunter N+1
  after hunter N completed AND every one of its pods reached a terminal export,
  and the pods of one hunt one at a time in file-stem order.

The queue is per-THREAT and global (spec 8): promoted threats ordered by `risk`
descending, then the unit intake position, then the threat rank, then the
dispatch id. It is not the unit model sum and there is no per-unit cap. The unit
model sum stays in the run record for the budget and the audit.

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

# The dispatch queue's intake-position fallback: a unit the run record has not
# named (a recovered spec-only unit) sorts after every recorded unit. The
# dispatch id then breaks the tie deterministically.
UNKNOWN_INTAKE_POSITION = 1_000_000

# The rank fallback for a dispatch id whose threat id is not `threat-<n>` (a
# malformed or foreign key): it sorts after every ranked hunt and never crashes
# the decision.
UNRANKED = 1 << 30
# An unknown blocked threat sorts ahead of every scored threat: without a
# readable spec body the gate cannot prove its identity or risk, so it fails
# closed and holds the queue instead of silently skipping the stale hunt.
BLOCKED_RISK = float("inf")


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


def _float_at_least(
    value: Any, minimum: float, *, setting: str,
) -> float | None:
    """One stored numeric candidate as a float, or None when it is malformed or
    below the documented floor. A boolean, a non-numeric value, or a negative
    value is malformed: the settings are DB-stored numbers and the API writes
    only numbers. An int stored by a pre-v5 settings blob reads as a float. A
    malformed value warns once and falls through."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        logger.warning(
            "hunting: %s=%r is not a number; falling back", setting, value)
        return None
    if value < minimum:
        logger.warning(
            "hunting: %s=%r is below %r; falling back", setting, value, minimum)
        return None
    return float(value)


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
) -> float | None:
    """The run's frozen promotion threshold: the run record first (an explicit
    null is a frozen "no filter"), then the project setting, then None. A
    malformed recorded candidate warns and falls through to the setting; a
    malformed setting warns and falls back to no filter. The threshold is a
    float on the CVSS 4.0 scale; an int stored by a pre-v5 blob reads as one."""
    if recorded_present:
        if recorded is None:
            return None
        value = _float_at_least(recorded, 0.0, setting="promotion_risk_threshold")
        if value is not None:
            return value
    return _float_at_least(
        (settings or {}).get("promotion_risk_threshold"), 0.0,
        setting="promotion_risk_threshold")


def risk_is_promoted(risk: float, threshold: float | None) -> bool:
    """The ONE promotion comparison: inclusive; None or 0 means no filter."""
    return threshold is None or threshold <= 0 or risk >= threshold


def threat_is_promoted(
    record: Mapping[str, Any], threshold: float | None,
) -> bool:
    """Whether one stored threat file is promoted to a hunter. A threat whose
    risk is unreadable is never promoted."""
    risk = threat_risk(record)
    return risk is not None and risk_is_promoted(risk, threshold)


def threat_is_demoted(
    record: Mapping[str, Any], threshold: float | None,
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
    """One unit's queue metadata: the intake position breaks a risk tie between
    two threats of different units. The unit model sum is NOT here - it stays in
    the run record for the budget and the audit and never orders the queue."""

    unit_name: str
    unit_id: str = ""
    intake_position: int = UNKNOWN_INTAKE_POSITION


@dataclass(frozen=True)
class ThreatMeta:
    """One threat's queue metadata (the dispatch queue is a global list of
    promoted threats, spec 8): the score orders the queue, the unit intake
    position and the threat rank break its ties, and the dispatch id is the
    final deterministic key."""

    dispatch_id: str
    unit_name: str = ""
    risk: float = 0.0
    intake_position: int = UNKNOWN_INTAKE_POSITION
    rank: int = UNRANKED


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
    # The run's GLOBAL threat queue metadata: every promoted, observable hunt
    # with its score, its unit's intake position, and its rank. `decide` and
    # `batch_state` re-derive the order through `order_threats`, so the queue is
    # deterministic on every input. A hunt visible only through an item carries
    # its own metadata; one with no known score sorts last.
    threats: tuple[ThreatMeta, ...] = ()


@dataclass(frozen=True)
class BatchState:
    """The derived phase snapshot of the ONE current threat (the ledger's
    cursor view).

    `phase` is `hunt` while the current threat's hunter is still running,
    `pod` once the hunter is terminal and the current pod block is not fully
    exported (batched), `serial` for the strict cursor view, and `done` when the
    threat is finished. `current` is the current threat's
    dispatch id; `hunts` is the ordered threat list in scope for this phase (the
    block for `batched`, the whole queue for `serial`); `cursor` the first
    threat that is not fully done; `pods`/`pod_cursor` are the cursor threat's
    spec stems and the first stem without a durable export.
    """

    current: str
    phase: str
    hunts: tuple[str, ...] = ()
    cursor: str | None = None
    # The current `batched` pod block: the fixed slice of risk-ordered threats
    # whose pod sets dispatch together. Its first unfinished threat is `cursor`.
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

    def meta_for(self, unit_name: str, unit_id: str) -> UnitMeta:
        """The unit metadata: the unit identity is cached for the run's
        lifetime, while the intake position is RE-READ on every call. The intake
        order lands on the run record before dispatch, so a unit first seen
        earlier must not stay at the unknown fallback."""
        cached = self._metas.get(unit_name)
        resolved = unit_id or (cached.unit_id if cached else "")
        meta = UnitMeta(
            unit_name=unit_name,
            unit_id=resolved,
            intake_position=self.intake_position(resolved),
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


def order_threats(threats: Iterable[ThreatMeta]) -> tuple[ThreatMeta, ...]:
    """The dispatch queue order (spec 8): risk DESC, then the unit intake
    position ASC, then the threat rank ASC, then the dispatch id ASC - a total
    order, so a tie is deterministic on every input."""
    return tuple(sorted(
        threats, key=lambda threat: (
            -threat.risk,
            threat.intake_position,
            threat.rank,
            threat.dispatch_id,
        )))


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


def _threat_hunts(items: Sequence[ProducedItem]) -> set[str]:
    """The hunts that still carry a produced threat item (the hunter is not
    admitted yet)."""
    return {
        item.dispatch_id for item in items if isinstance(item, ThreatItem)
    }


def _visible_hunts(
    items: Sequence[ProducedItem], facts: SyncFacts,
) -> set[str]:
    """Every hunt the facts or the items name: the pods' and hunters' keys, the
    graph and pod sessions, the blocked hunts, and the spec stems."""
    hunts = set(facts.spec_stems) | set(facts.pending_spec_stems)
    hunts |= set(facts.consumed_spec_stems)
    hunts |= set(facts.hunts_in_graph) | set(facts.live_pod_hunts)
    hunts |= set(facts.blocked_hunts)
    for item in items:
        if isinstance(item, ThreatItem):
            hunts.add(item.dispatch_id)
        elif isinstance(item, TestSpecItem):
            hunts.add(item.hunt_key)
    return hunts


def threat_queue(
    items: Sequence[ProducedItem],
    units: Sequence[UnitMeta],
    facts: SyncFacts,
) -> tuple[ThreatMeta, ...]:
    """The run's GLOBAL dispatch queue: the ordered threat metadata (spec 8).

    The gate's `facts.threats` carry the authoritative metadata (the score, the
    unit intake position, the rank). A hunt visible only through an item or a
    spec stem still queues: an item supplies its own score, and a hunt with no
    known score sorts last (fail-open, never dropped from the queue). A demoted
    hunt never queues.
    """
    intake = {unit.unit_name: unit.intake_position for unit in units}
    metas: dict[str, ThreatMeta] = {
        meta.dispatch_id: meta for meta in facts.threats
        if meta.dispatch_id not in facts.demoted_hunts
    }
    for item in items:
        if not isinstance(item, ThreatItem):
            continue
        if item.dispatch_id in metas or item.dispatch_id in facts.demoted_hunts:
            continue
        metas[item.dispatch_id] = ThreatMeta(
            dispatch_id=item.dispatch_id,
            unit_name=item.unit_name,
            risk=float(item.risk or 0.0),
            intake_position=intake.get(item.unit_name, UNKNOWN_INTAKE_POSITION),
            rank=hunt_rank(item.dispatch_id),
        )
    for hunt in sorted(_visible_hunts(items, facts)):
        if hunt in metas or hunt in facts.demoted_hunts:
            continue
        unit_name = unit_of_dispatch(hunt)
        metas[hunt] = ThreatMeta(
            dispatch_id=hunt,
            unit_name=unit_name,
            risk=0.0,
            intake_position=intake.get(unit_name, UNKNOWN_INTAKE_POSITION),
            rank=hunt_rank(hunt),
        )
    return order_threats(metas.values())


def current_threat(
    queue: Sequence[ThreatMeta],
    items: Sequence[ProducedItem],
    facts: SyncFacts,
) -> ThreatMeta | None:
    """The queue's current threat: the first threat in risk order that is not
    fully done (a produced threat file, a mid-graph hunter, a live pod, a
    blocked hunt, or an un-exported pod set). None when the queue is drained."""
    threat_hunts = _threat_hunts(items)
    return next(
        (meta for meta in queue
         if not _hunt_done(meta.dispatch_id, threat_hunts, facts)),
        None,
    )


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
    modeller pass is live, then work the GLOBAL threat queue in risk order:
    `batched` admits the current threat's hunter, and its pods once the hunter
    is terminal (in fixed blocks of `pod_batch_size` threats); `serial` admits
    only the current threat's hunter, or its next pod in stem order once the
    hunter is terminal, and only after every earlier threat is fully done.
    There is no per-unit cap: a unit boundary never holds another unit's threat.
    """
    items = tuple(items)
    if not items:
        return frozenset()
    if mode is SyncMode.PARALLEL:
        return frozenset(item.message_id for item in items)
    if facts.modeller_live:
        return frozenset()

    queue = threat_queue(items, units, facts)
    current = current_threat(queue, items, facts)
    if current is None:
        return frozenset()

    if mode is SyncMode.SERIAL:
        return _decide_serial(items, current.dispatch_id, facts)
    return _decide_batched(
        items, queue, current.dispatch_id, facts, pod_batch_size=pod_batch_size)


def batch_state(
    mode: SyncMode,
    current: str,
    items: Sequence[ProducedItem],
    facts: SyncFacts,
    *,
    pod_batch_size: int = DEFAULT_POD_BATCH_SIZE,
) -> BatchState:
    """The current threat's derived phase state: `hunt` while its hunter is
    unfinished, `pod` for its fixed block of `pod_batch_size` threats whose pod
    set is not fully exported, `serial` for the strict cursor view, `done` when
    the threat is finished. `current` is a threat dispatch id - the unit
    boundary no longer bounds a dispatch.

    The queue is rebuilt from the facts alone. The live decision passes its
    unit-aware queue to `_batch_state` directly, so a tie broken by the unit
    intake position lands on the same block boundary in both paths."""
    return _batch_state(
        mode, threat_queue(items, (), facts), current, items, facts,
        pod_batch_size=pod_batch_size,
    )


def _batch_state(
    mode: SyncMode,
    queue: Sequence[ThreatMeta],
    current: str,
    items: Sequence[ProducedItem],
    facts: SyncFacts,
    *,
    pod_batch_size: int = DEFAULT_POD_BATCH_SIZE,
) -> BatchState:
    hunts = tuple(meta.dispatch_id for meta in queue)
    threat_hunts = _threat_hunts(items)
    if current not in hunts:
        return BatchState(current=current, phase="done", hunts=hunts)
    if _hunt_done(current, threat_hunts, facts):
        return BatchState(current=current, phase="done", hunts=hunts)
    if mode is SyncMode.SERIAL:
        pods = tuple(facts.spec_stems.get(current, ()))
        pod_cursor = next(
            (stem for stem in pods
             if (current, stem) not in facts.terminal_specs),
            None,
        )
        return BatchState(
            current=current, phase="serial", hunts=hunts, cursor=current,
            pods=pods, pod_cursor=pod_cursor,
        )
    if not _hunter_terminal(current, threat_hunts, facts):
        return BatchState(current=current, phase="hunt", hunts=hunts)

    size = max(1, int(pod_batch_size))
    index = hunts.index(current)
    start = (index // size) * size
    pod_batch = hunts[start:start + size]
    cursor = next(
        (hunt for hunt in pod_batch
         if not _hunt_done(hunt, threat_hunts, facts)),
        current,
    )
    pods = tuple(facts.spec_stems.get(cursor, ()))
    pod_cursor = next(
        (stem for stem in pods if (cursor, stem) not in facts.terminal_specs),
        None,
    )
    return BatchState(
        current=current, phase="pod", hunts=pod_batch, cursor=cursor,
        pod_batch=pod_batch, pods=pods, pod_cursor=pod_cursor,
    )


def _hunter_terminal(
    hunt: str, threat_hunts: set[str], facts: SyncFacts,
) -> bool:
    """A hunt's hunter phase is terminal: no produced threat file, no live
    graph, no blocked hunt, and a durable terminal marker for THIS run. The pod
    phase may only start behind a terminal hunter."""
    if hunt in threat_hunts:
        return False
    if hunt in facts.hunts_in_graph:
        return False
    if hunt in facts.blocked_hunts:
        return False
    return hunt in facts.terminal_hunts


def _decide_batched(
    items: Sequence[ProducedItem],
    queue: Sequence[ThreatMeta],
    current: str,
    facts: SyncFacts,
    *,
    pod_batch_size: int = DEFAULT_POD_BATCH_SIZE,
) -> frozenset[str]:
    """The current threat's phase: its hunter while the hunt phase is active,
    then the current fixed block's pod sets. The next threat's hunter starts
    only once the current threat's pods carry a durable export, so the block is
    a block of THREATS, never of units."""
    state = _batch_state(
        SyncMode.BATCHED, queue, current, items, facts,
        pod_batch_size=pod_batch_size,
    )
    if state.phase == "hunt":
        return frozenset(
            item.message_id for item in items
            if isinstance(item, ThreatItem) and item.dispatch_id == current)
    if state.phase != "pod" or not state.pod_batch:
        return frozenset()
    threat_hunts = _threat_hunts(items)
    block = frozenset(state.pod_batch)
    # Only a TERMINAL hunter's pods belong to the block: a later threat in the
    # same span has not been hunted yet, so it contributes nothing and can
    # never hold the block.
    return frozenset(
        item.message_id for item in items
        if isinstance(item, TestSpecItem)
        and item.hunt_key in block
        and _hunter_terminal(item.hunt_key, threat_hunts, facts)
        and (item.hunt_key, item.spec_file) not in facts.terminal_specs
    )


def _decide_serial(
    items: Sequence[ProducedItem],
    current: str,
    facts: SyncFacts,
) -> frozenset[str]:
    """The cursor: the current threat's produced file is the hunter; once that
    threat's hunter is terminal, its next pod in stem order; a hunt still
    mid-graph admits nothing. The batch size is ignored: serial stays one agent
    at a time."""
    state = batch_state(SyncMode.SERIAL, current, items, facts)
    if state.phase != "serial" or state.cursor is None:
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


def _model_threat_risk(threat: Any) -> float:
    """One model threat's CVSS 4.0 score.

    The persisted threat carries the store-derived float `risk`. A model without
    it (a foreign or pre-v5 document that a live run never dispatches) scores
    nothing: never a crash - the queue still runs and the threat sorts last."""
    if not isinstance(threat, Mapping):
        return 0.0
    raw = threat.get("risk")
    if raw is None or isinstance(raw, bool):
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


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
    caller-supplied live-session set, builds the GLOBAL threat queue metadata
    (each promoted threat's score, its unit's intake position, its rank), and
    applies the pure `decide`. It keeps only the model and unit-metadata caches
    (the models are frozen once the modeller settles); every gate decision
    itself is re-derived, so a resumed run rebuilds the same queue with no
    persisted ledger.
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
        promotion_risk_threshold: float | None = None,
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
        # item, so it must stay current and block a silent skip. Both batched
        # and serial read the per-hunt pod cursor from the same facts.
        facts = self._lifecycle_facts(facts)
        units = self._units(items, facts)
        facts = self._queue_facts(items, units, facts)
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
        finds no produced item for it). The metadata (the unit identity and its
        intake position) is cached for the run's lifetime, and a session-only
        unit's unit id is recovered from its stored spec body."""
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
                metas[name] = self.state.meta_for(name, cached.unit_id)
                continue
            unit_id = self._unit_id_for_hunt(hunt)
            metas[name] = self.state.meta_for(name, unit_id)
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
        return self.state.meta_for(
            unit_name, unit_id or (cached.unit_id if cached else ""))

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

    def _queue_facts(
        self,
        items: Sequence[ProducedItem],
        units: Sequence[UnitMeta],
        facts: SyncFacts,
    ) -> SyncFacts:
        """The GLOBAL queue metadata plus the per-hunt pod cursor facts.

        The queue is built from every OBSERVABLE hunt of this run's units (an
        item, a spec folder, a graph or pod session, a blocked hunt, or a
        terminal marker) with the model-derived score and the unit intake
        position. A model threat with no artifact never queues: a zero-risk
        threat has no threat file (S2 8.3) and a refused threat has no
        observable artifact, so neither can hold the phase.

        The pod facts (produced and consumed stems, the durable exports) are
        read only for the hunts that can carry pods - a terminal hunter, a
        produced spec item, or a live pod - so the tick keeps reading one small
        per-hunt set instead of the whole store.
        """
        by_name = {unit.unit_name: unit for unit in units}
        metas: dict[str, ThreatMeta] = {}
        observed: set[str] = set()
        if self.hunter_store is not None:
            try:
                hunt_keys = self.hunter_store.list_hunt_keys(self.project_id)
            except Exception:  # noqa: BLE001 - a read failure is not a false done
                hunt_keys = ()
            observed |= {
                hunt for hunt in hunt_keys
                if unit_of_dispatch(hunt) in by_name
            }
        for item in items:
            if isinstance(item, ThreatItem):
                observed.add(item.dispatch_id)
            elif isinstance(item, TestSpecItem):
                observed.add(item.hunt_key)
        observed |= {
            hunt for hunt in facts.hunts_in_graph | facts.live_pod_hunts
            if unit_of_dispatch(hunt) in by_name
        }
        observed |= {
            hunt for hunt in facts.blocked_hunts
            if unit_of_dispatch(hunt) in by_name
        }
        observed -= set(facts.demoted_hunts)

        # The model-derived score per hunt. The models freeze once the modeller
        # settles, so the read is cached for the run's lifetime.
        risk_by_hunt: dict[str, float] = {}
        for unit_name, unit in by_name.items():
            if not unit.unit_id:
                continue
            model = self._read_model(unit.unit_id)
            if not isinstance(model, Mapping) or model.get("state") != "COMPLETED":
                continue
            for threat in model.get("threats") or ():
                if not isinstance(threat, Mapping):
                    continue
                threat_id = str(threat.get("id") or "")
                risk = _model_threat_risk(threat)
                if not threat_id or risk <= 0:
                    continue
                if not risk_is_promoted(risk, self.promotion_risk_threshold):
                    continue
                risk_by_hunt[f"{unit_name}__{threat_id}"] = risk

        for item in items:
            if not isinstance(item, ThreatItem):
                continue
            unit = by_name.get(item.unit_name)
            metas[item.dispatch_id] = ThreatMeta(
                dispatch_id=item.dispatch_id,
                unit_name=item.unit_name,
                risk=float(item.risk or 0.0),
                intake_position=(
                    unit.intake_position
                    if unit is not None else UNKNOWN_INTAKE_POSITION),
                rank=hunt_rank(item.dispatch_id),
            )
        for hunt in observed:
            if hunt in metas:
                continue
            unit_name = unit_of_dispatch(hunt)
            unit = by_name.get(unit_name)
            risk = risk_by_hunt.get(hunt, 0.0)
            if hunt in facts.blocked_hunts:
                # Fail closed: a hunt with no terminal marker and no live
                # session has no trustworthy state, so it heads the queue and
                # is surfaced, never silently skipped.
                risk = BLOCKED_RISK
            metas[hunt] = ThreatMeta(
                dispatch_id=hunt,
                unit_name=unit_name,
                risk=risk,
                intake_position=(
                    unit.intake_position
                    if unit is not None else UNKNOWN_INTAKE_POSITION),
                rank=hunt_rank(hunt),
            )

        pod_hunts: set[str] = {
            hunt for hunt in observed
            if hunt in facts.terminal_hunts and hunt not in facts.blocked_hunts
        }
        pod_hunts |= {
            item.hunt_key for item in items if isinstance(item, TestSpecItem)
        }
        stems: dict[str, tuple[str, ...]] = {}
        pending: dict[str, tuple[str, ...]] = {}
        consumed: dict[str, tuple[str, ...]] = {}
        terminal: set[tuple[str, str]] = set()
        for hunt in pod_hunts:
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
            threats=tuple(metas.values()),
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
    promotion_risk_threshold: float | None = None,
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
    "BLOCKED_RISK",
    "BatchState",
    "DEFAULT_POD_BATCH_SIZE",
    "DEFAULT_SYNC_MODE",
    "PipelineSyncState",
    "RunSyncGate",
    "SyncFacts",
    "SyncMode",
    "ThreatMeta",
    "UNRANKED",
    "UNKNOWN_INTAKE_POSITION",
    "UnitMeta",
    "batch_state",
    "current_threat",
    "decide",
    "hunt_rank",
    "hunting_artifacts_terminal",
    "make_sync_gate",
    "order_threats",
    "resolve_mode",
    "resolve_pod_batch_size",
    "resolve_promotion_risk_threshold",
    "risk_is_promoted",
    "threat_is_demoted",
    "threat_is_promoted",
    "threat_queue",
    "unit_of_dispatch",
    "unit_of_item",
]
