"""The hunting pipeline sync policy (`hunting_pipeline_sync`, ADR
`docs/design/hunting-pipeline-sync-adr.md`, 2026-10-22).

The project-level mode governs WHEN the pipeline phases may dispatch:

- `parallel` - the historical behaviour: every produced item the mover finds is
  dispatched as it appears (the S1 7.3 interleave stays live);
- `batched` - phase barriers only: the modeller pass settles first, then one
  unit at a time in risk order, its whole hunter batch concurrently, then its
  pods once every hunt of the unit left the graph, then the next unit;
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

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from polymerhus.attack.hunting.mover import (
    SPEC_DISPATCH_STATUS,
    ProducedItem,
    TestSpecItem,
    ThreatLoopItem,
    threat_modeller_session_id,
)
from polymerhus.attack.hunting.threat_model import RISK_WEIGHTS, Likelihood

# The dispatch queue's intake-position fallback: a unit the run record has not
# named (a recovered spec-only unit) sorts after every recorded unit. The name
# then breaks the tie deterministically.
UNKNOWN_INTAKE_POSITION = 1_000_000

# The rank fallback for a dispatch id whose loop id is not `loop-<n>` (a
# malformed or foreign key): it sorts after every ranked hunt and never crashes
# the decision.
UNRANKED = 1 << 30


class SyncMode(StrEnum):
    """The project-level pipeline synchronisation mode (`hunting_pipeline_sync`)."""

    SERIAL = "serial"
    BATCHED = "batched"
    PARALLEL = "parallel"


DEFAULT_SYNC_MODE = SyncMode.BATCHED


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


@dataclass(frozen=True)
class BatchState:
    """The derived per-unit phase snapshot (the ledger's cursor view).

    `phase` is `hunt` while the unit's hunter batch is still running,
    `pod` once the batch is terminal (batched), `serial` for the strict cursor
    view, and `done` once every member is finished. `hunts` is the unit's hunt
    order (by loop rank) and `cursor` the first hunt that is not fully done;
    `pods`/`pod_cursor` are the cursor hunt's spec stems and the first stem
    without a durable export.
    """

    unit_name: str
    phase: str
    hunts: tuple[str, ...] = ()
    cursor: str | None = None
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
    """The unit directory a dispatch id belongs to: `<unit_name>__<loop_id>` ->
    `<unit_name>`. The dispatch id is the store's own join, so the last `__`
    split is the exact inverse; a key without the separator is returned as-is
    (a foreign key never crashes the queue)."""
    head, separator, _tail = dispatch_id.rpartition("__")
    return head if separator else dispatch_id


def unit_of_item(item: ProducedItem) -> str | None:
    """The unit a produced item belongs to (the queue key). A loop item carries
    its unit name directly; a spec item's hunt key (the loop dispatch id) is one
    level down from the unit."""
    if isinstance(item, ThreatLoopItem):
        return item.unit_name
    if isinstance(item, TestSpecItem):
        return unit_of_dispatch(item.hunt_key)
    return None


def hunt_rank(dispatch_id: str) -> int:
    """The loop rank of a dispatch id (`<unit>__loop-<n>` -> n); unranked keys
    sort last."""
    loop_id = dispatch_id.rpartition("__")[2]
    if loop_id.startswith("loop-"):
        try:
            return int(loop_id[len("loop-"):])
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
    pending.discard(None)
    return pending


def decide(
    mode: SyncMode,
    items: Sequence[ProducedItem],
    units: Sequence[UnitMeta],
    facts: SyncFacts,
) -> frozenset[str]:
    """The items admissible NOW, as `message_id`s (the pure policy decision).

    `parallel` admits every item. `batched`/`serial` hold everything while the
    modeller pass is live, then work the queue one unit at a time:
    `batched` admits the current unit's whole hunter batch, and its pods only
    once no loop file and no mid-graph hunt remains; `serial` admits only the
    cursor hunt (or, once it is terminal, its next pod in stem order), and only
    after every earlier hunt is fully done (terminal AND all its pods
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
        return _decide_serial(items, current, facts)
    return _decide_batched(items, current, facts)


def batch_state(
    mode: SyncMode,
    current: str,
    items: Sequence[ProducedItem],
    facts: SyncFacts,
) -> BatchState:
    """The unit's derived phase state: `hunt`/`pod` for `batched`, the ordered
    hunts + cursor + pod cursor for `serial`, `done` when nothing is left."""
    unit_items = [item for item in items if unit_of_item(item) == current]
    if mode is SyncMode.BATCHED:
        hunts_pending = (
            any(isinstance(item, ThreatLoopItem) for item in unit_items)
            or any(
                unit_of_dispatch(hunt) == current
                for hunt in facts.hunts_in_graph)
        )
        hunts = tuple(sorted(
            (item.dispatch_id for item in unit_items
             if isinstance(item, ThreatLoopItem)),
            key=hunt_rank,
        ))
        return BatchState(
            unit_name=current,
            phase="hunt" if hunts_pending else "pod",
            hunts=hunts,
        )

    loop_hunts = {
        item.dispatch_id for item in unit_items
        if isinstance(item, ThreatLoopItem)
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
    hunts = tuple(sorted(
        loop_hunts | spec_hunts | graph_hunts | pod_hunts, key=hunt_rank))
    cursor = next(
        (hunt for hunt in hunts if not _hunt_done(hunt, loop_hunts, facts)),
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
    items: Sequence[ProducedItem], current: str, facts: SyncFacts,
) -> frozenset[str]:
    """One unit's phase at a time: the whole hunter batch while the hunt phase
    is active, then the unit's whole pod set."""
    state = batch_state(SyncMode.BATCHED, current, items, facts)
    unit_items = [item for item in items if unit_of_item(item) == current]
    if state.phase == "hunt":
        return frozenset(
            item.message_id for item in unit_items
            if isinstance(item, ThreatLoopItem))
    return frozenset(
        item.message_id for item in unit_items
        if isinstance(item, TestSpecItem))


def _decide_serial(
    items: Sequence[ProducedItem], current: str, facts: SyncFacts,
) -> frozenset[str]:
    """The cursor: the pending loop file of the cursor hunt is the hunter;
    once that hunt is terminal, its next pod in stem order; a hunt still
    mid-graph admits nothing."""
    state = batch_state(SyncMode.SERIAL, current, items, facts)
    if state.cursor is None:
        return frozenset()
    cursor = state.cursor
    loop_item = next(
        (item for item in items
         if isinstance(item, ThreatLoopItem) and item.dispatch_id == cursor),
        None,
    )
    if loop_item is not None:
        return frozenset({loop_item.message_id})
    if cursor in facts.hunts_in_graph:
        # The hunt is still authoring its spec set: no pod yet.
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
    hunt: str, loop_hunts: set[str], facts: SyncFacts,
) -> bool:
    """A hunt is fully done when it has no pending loop file, is not mid-graph,
    has no executing pod, and every one of its specs carries a terminal
    export. An empty spec set (a zero-spec hunt) is therefore done as soon as
    the hunt itself is terminal."""
    if hunt in loop_hunts:
        return False
    if hunt in facts.hunts_in_graph:
        return False
    if hunt in facts.live_pod_hunts:
        return False
    return all(
        (hunt, stem) in facts.terminal_specs
        for stem in facts.spec_stems.get(hunt, ())
    )


def _loop_weight(loop: Any) -> int:
    """One model loop's risk weight; an unknown likelihood contributes nothing
    (never a crash - the model is foreign or malformed, the queue still runs)."""
    value = loop.get("likelihood") if isinstance(loop, Mapping) else None
    try:
        return RISK_WEIGHTS[Likelihood(value)]
    except (ValueError, KeyError):
        return 0


def _spec_unit_id(body: Any) -> str:
    """The unit identity a stored spec body names (`target.unit_id`, falling
    back to `provenance.unit_id`); empty for an absent or untyped body."""
    if not isinstance(body, Mapping):
        return ""
    target = body.get("target")
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
    ) -> None:
        self.state = PipelineSyncState(
            mode=SyncMode(mode), intake_order=intake_order)
        self.project_id = project_id
        self.run_id = run_id
        self.threat_store = threat_store
        self.hunter_store = hunter_store
        self.pod_store = pod_store

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
        units = self._units(items, facts)
        if self.mode is SyncMode.SERIAL:
            facts = self._serial_facts(items, units, facts)
        admitted = decide(self.mode, items, units, facts)
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
        visible through a live pod or a mid-graph hunt (a consumed loop search
        finds no produced item for it). The per-unit metadata (risk) is cached
        for the run's lifetime - models freeze once the modeller settles - and
        a session-only unit's unit id is recovered from its stored spec body."""
        metas: dict[str, UnitMeta] = {}
        for item in items:
            name = unit_of_item(item)
            if name is None or name in metas:
                continue
            metas[name] = self._meta_for(item, name)
        session_hunts = set(facts.live_pod_hunts) | set(facts.hunts_in_graph)
        for hunt in session_hunts:
            name = unit_of_dispatch(hunt)
            if name in metas:
                continue
            cached = self.state.cached(name)
            if cached is not None:
                metas[name] = cached
                continue
            unit_id = self._unit_id_for_hunt(hunt)
            metas[name] = self.state.meta_for(
                name, unit_id, risk=self._risk(unit_id))
        return tuple(metas.values())

    def _unit_id_for_hunt(self, hunt_key: str) -> str:
        """The unit identity a hunt's stored spec body names, when the hunt is
        visible only through a session. Fail-open to the empty id."""
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
                    return unit_id
        return ""

    def _meta_for(self, item: ProducedItem, unit_name: str) -> UnitMeta:
        unit_id = (
            item.unit_id if isinstance(item, ThreatLoopItem)
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
        """The unit's risk contribution: the summed loop likelihood weights of
        its model document (the run record's `model_sum` figure). Fail-open:
        an unreadable or unknown model contributes zero."""
        if not unit_id or self.threat_store is None:
            return 0
        try:
            model = self.threat_store.read_model(self.project_id, unit_id)
        except Exception:  # noqa: BLE001 - fail-open: the queue still runs
            return 0
        loops = (model or {}).get("loops") or ()
        return sum(_loop_weight(loop) for loop in loops)

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

    def _serial_facts(
        self,
        items: Sequence[ProducedItem],
        units: Sequence[UnitMeta],
        facts: SyncFacts,
    ) -> SyncFacts:
        """The cursor facts: the current unit's spec stems (produced plus
        consumed) and the durable export set. No other unit needs them this
        tick."""
        current = current_unit(items, units, facts)
        if current is None:
            return facts
        hunts: set[str] = set()
        for item in items:
            if unit_of_item(item) != current:
                continue
            if isinstance(item, ThreatLoopItem):
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
        stems: dict[str, tuple[str, ...]] = {}
        terminal: set[tuple[str, str]] = set()
        for hunt in hunts:
            files = self._dispatchable_stems(hunt)
            stems[hunt] = files
            for stem in files:
                if self._export_exists(stem):
                    terminal.add((hunt, stem))
        return replace(
            facts, spec_stems=stems, terminal_specs=frozenset(terminal))

    def _stems(self, hunt_key: str) -> set[str]:
        stems: set[str] = set()
        if self.hunter_store is None:
            return stems
        for reader in (
            getattr(self.hunter_store, "produced_spec_files", None),
            getattr(self.hunter_store, "consumed_spec_files", None),
        ):
            if reader is None:
                continue
            try:
                stems.update(reader(self.project_id, hunt_key))
            except Exception:  # noqa: BLE001 - fail-open: a read never blocks
                continue
        return stems

    def _dispatchable_stems(self, hunt_key: str) -> tuple[str, ...]:
        """The cursor's spec stems: only bodies the pod can actually dispatch.

        A hunter may write a spec and mark it `dropped` (a declined variant).
        Such a spec has no pod and never gets a PodExport, so counting it in
        the serial cursor would wedge the hunt forever. A body that cannot be
        read is treated as dispatchable (fail-open): the mover's own produced
        read is the authority and an unreadable body must not silently skip a
        pod."""
        return tuple(
            stem for stem in sorted(self._stems(hunt_key))
            if self._spec_dispatchable(hunt_key, stem)
        )

    def _spec_dispatchable(self, hunt_key: str, spec_id: str) -> bool:
        """Whether the stored spec carries the pod dispatch status.

        Read produced first, then consumed. A readable non-ratified body is
        terminal-by-decision and is excluded; a body absent from both sides is
        treated as dispatchable so a transient read gap cannot skip a pod."""
        for side in ("produced", "consumed"):
            try:
                body = self.hunter_store.read_spec(
                    self.project_id, hunt_key, spec_id, side=side)
            except Exception:  # noqa: BLE001 - fail-open per record
                continue
            if body is not None:
                return body.get("status") == SPEC_DISPATCH_STATUS
        return True

    def _export_exists(self, spec_id: str) -> bool:
        if self.pod_store is None:
            return False
        try:
            return bool(self.pod_store.read_pod_export(spec_id, self.run_id))
        except Exception:  # noqa: BLE001 - fail-open: a corrupt export is not terminal
            return False


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
    "make_sync_gate",
    "order_units",
    "resolve_mode",
    "unit_of_dispatch",
    "unit_of_item",
]
