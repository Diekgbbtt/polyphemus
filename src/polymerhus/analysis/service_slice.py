"""The per-Service slice builder and loop (T5, ADR D12-D20, D38-D40).

The service-sourced pipeline's unit is the business Service, not the recon job's
surface. This module owns the two halves of stage 2:

  - `build_service_slices` - the PURE builder. Given an injected read seam (the
    live L1 Service inventory, the Service->L0 aggregation view, and the settled
    L0 surface) it produces one `Chunk` per Service, sorted by
    `business_function_slug`, PLUS one residual unit carrying the surface no
    Service aggregates (ADR D14, D20). A Service slice is a `Chunk` whose
    `chunk_id` is the Service slug, sanitised for use as a thread-id / session
    header segment (ADR D18, D39).
  - `run_service_loop` - the per-unit loop. For each unit it runs mechanism_typist
    then data_modeller through the supervisor graph (reusing `build_supervisor_graph`
    / `_make_proposer` / `_chunked_write_fn` unchanged, ADR D38/D40), one
    `(service-slice, role)` dispatch pair per unit. It is fail-open per unit with a
    BOUNDED per-unit retry (ADR D15, D16): a unit whose first attempt degraded is
    retried up to `attempts`; a unit that stays degraded is recorded and the loop
    continues. A unit with no surface yields an explicit `no_surface` outcome,
    never a silent skip. The loop checks an injected `stop_fn` between units, so a
    long pass is interruptible at a Service boundary (ADR D42).

Every collaborator is injectable, so the whole module is unit-testable with no
Neo4j, no LLM and no database. Importing it performs no I/O (CODING_STANDARD 6).
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from functools import partial
from typing import Callable

from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.messages import StepReceipt, WriteCounts

logger = logging.getLogger(__name__)

# The residual unit's chunk_id: the unaggregated / stale surface no Service
# aggregates (ADR D20). Deliberately unlike a Service slug so it can never collide
# with a real Service's unit.
RESIDUAL_UNIT = "__residual__"

# The per-unit role order (ADR D12, D13): the typist types the Service's Systems
# BEFORE the data-modeller joins its Parameters/Headers to them.
SERVICE_ROLES: tuple[str, ...] = ("mechanism_typist", "data_modeller")

# The bounded per-unit retry (ADR D16): one attempt with no recovery would lose
# the Service's Systems and DataItems for the whole run.
DEFAULT_UNIT_ATTEMPTS = 2

# The thread-id / session-header segment length cap, mirroring
# `session_address._MAX_SEGMENT`; an over-long LLM-authored slug is hashed so the
# address stays bounded without losing uniqueness (ADR D18).
_MAX_SLUG = 80
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitise_slug(slug: str) -> str:
    """A Service slug made safe as a thread-id / session-header segment (ADR D18).

    `business_function_slug` is LLM-authored and unvalidated beyond non-empty;
    before it becomes a `thread_id` segment, a `dispatch_id` segment and a
    provider session header it must not carry the address separator or any other
    boundary-breaking character. An ordinary lower-hyphen slug is unchanged, so
    the unit's `chunk_id` IS the Service slug; a pathological one is normalised,
    and an over-long one is replaced by a stable short hash so the address stays
    bounded (the same rule `session_address._seg` applies)."""
    raw = str(slug or "").strip()
    cleaned = _UNSAFE.sub("-", raw).strip("-.")
    if not cleaned:
        cleaned = "unit"
    if len(cleaned) > _MAX_SLUG:
        return "h" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return cleaned


def _read_live(project_id: str) -> tuple[list[str], list[dict], list]:
    """The live read seam: the L1 Service inventory, the Service->L0 aggregation
    view, and the settled L0 surface. Each reader is itself fail-open, so a graph
    blip degrades to an empty surface rather than raising into the builder."""
    from polymerhus.analysis.l0_stream import read_l0_assets
    from polymerhus.analysis.l1_inventory import read_l1_inventory
    from polymerhus.analysis.l1_read import read_service_aggregations

    inventory = read_l1_inventory(project_id) or {}
    return (
        list(inventory.get("services") or []),
        read_service_aggregations(project_id),
        read_l0_assets(project_id),
    )


def _matches(asset, row: dict) -> bool:
    """True when an aggregation row describes `asset`: the L0 label is present and
    every identity key/value of the asset appears on the row's props. The same
    bounded subset-match `mechanism_typist._identity_matches` uses, so the two
    cannot disagree about which surface a Service aggregates."""
    if asset.type not in (row.get("labels") or []):
        return False
    props = row.get("props") or {}
    return all(str(props.get(k)) == str(v) for k, v in (asset.identity or {}).items())


def build_service_slices(
    project_id: str, *, read_fn: Callable[[str], tuple] | None = None
) -> list[Chunk]:
    """PURE builder over an injected read seam (ADR D14, D20, D39).

    `read_fn(project_id) -> (services, aggregations, assets)`. Services are
    deduped and sorted by `business_function_slug`; each becomes a `Chunk` whose
    `chunk_id` is the sanitised Service slug and whose assets are the settled L0
    surface that Service aggregates. One residual unit (chunk_id `RESIDUAL_UNIT`)
    carries the surface no Service aggregates, appended LAST; it is omitted when
    there is no residual surface. A Service with no aggregated surface still gets
    a unit (an empty one), so the loop can record an explicit `no_surface`
    outcome instead of silently skipping it (ADR D15). A read failure degrades to
    no units and never raises."""
    read_fn = read_fn or _read_live
    try:
        services, aggregations, assets = read_fn(project_id)
    except Exception:  # a read blip degrades to no units, never crashes the pass
        logger.warning("service_slice: read failed; no units this pass", exc_info=True)
        return []

    service_slugs = sorted({s for s in (services or []) if s})
    rows = list(aggregations or [])
    surface = list(assets or [])

    matched: set[int] = set()
    units: list[Chunk] = []
    for slug in service_slugs:
        owned: list = []
        slug_rows = [r for r in rows if r.get("slug") == slug]
        for i, asset in enumerate(surface):
            if any(_matches(asset, r) for r in slug_rows):
                owned.append(asset)
                matched.add(i)
        units.append(Chunk(
            chunk_id=sanitise_slug(slug), source_job=f"service:{slug}",
            assets=tuple(owned),
        ))

    residual = tuple(a for i, a in enumerate(surface) if i not in matched)
    if residual:
        units.append(Chunk(chunk_id=RESIDUAL_UNIT, source_job="residual", assets=residual))
    return units


# --- the loop -----------------------------------------------------------------


@dataclass(frozen=True)
class UnitOutcome:
    """What one (unit, role) pair did (ADR D15): `written` / `empty` / `degraded`
    from the receipt, or `no_surface` when the unit carried no aggregated surface
    and was deliberately not dispatched. This is the explicit per-unit record that
    makes a skip impossible to mistake for a silent one."""

    unit: str
    role: str
    status: str
    attempts: int = 1
    error: str | None = None
    written: WriteCounts | None = None


@dataclass(frozen=True)
class ServiceLoopResult:
    """The per-Service loop's terminal record."""

    units: tuple[str, ...] = ()
    outcomes: tuple[UnitOutcome, ...] = ()
    receipts: tuple[StepReceipt, ...] = ()
    stopped: bool = False
    aggregates_written: int = 0
    systems_written: int = 0
    data_items_written: int = 0

    @property
    def wrote(self) -> bool:
        """The WRITE-BASED drained signal (ADR D41): at least one step was written.
        Dispatch count is deliberately NOT the signal - a run where every Service
        degraded must not be reported drained."""
        return any(r.status == "written" for r in self.receipts)


def _any_degraded(receipts) -> bool:
    return any(getattr(r, "status", None) == "degraded" for r in (receipts or []))


def _build_bodies(
    *, memory, invoke_fns, inventory_fn, aggregations_fn, first_definer: bool,
) -> dict:
    """Build the two role bodies for the service-sourced loop, threading the
    per-project memory store and the unit slug (ADR D31; the deferred T3 wiring).
    The typist gets `first_definer=True` so it never re-compounds an already-defined
    System's description over N Services (ADR D19); the streamed default does not."""
    from polymerhus.analysis.data_modeller import make_data_modeller_body
    from polymerhus.analysis.mechanism_typist import mechanism_typist_body

    typist = partial(
        mechanism_typist_body, invoke_fn=(invoke_fns or {}).get("mechanism_typist"),
        read_inventory=inventory_fn, read_aggregations=aggregations_fn,
        first_definer=first_definer, memory=memory,
    )
    data = make_data_modeller_body(
        invoke_fn=(invoke_fns or {}).get("data_modeller"),
        inventory_fn=inventory_fn, aggregations_fn=aggregations_fn, memory=memory,
    )
    return {"mechanism_typist": typist, "data_modeller": data}


async def _run_unit(
    builder, unit: Chunk, *, project_id: str, run_id: str, attempts: int,
    checkpointer, store, observe: bool,
) -> tuple[dict, int]:
    """Run one unit's (typist, data_modeller) dispatch pair, retrying the whole pair
    while any receipt is `degraded`, up to `attempts` (ADR D16). Returns the last
    supervisor state and the attempt count actually spent."""
    from polymerhus.analysis.supervisor import build_schedule, run_supervisor

    schedule = build_schedule([unit], run_id, roles=SERVICE_ROLES, phase="A1")
    state: dict = {}
    used = 0
    for attempt in range(1, attempts + 1):
        used = attempt
        state = await run_supervisor(
            project_id, run_id, schedule, builder=builder,
            checkpointer=checkpointer, store=store, observe=observe,
            observe_metadata=_unit_metadata(unit, run_id, attempt),
        )
        if not _any_degraded(state.get("receipts")):
            break
        logger.warning(
            "service_slice: unit %s degraded on attempt %d/%d; retrying",
            unit.chunk_id, attempt, attempts,
        )
    return state, used


def _unit_metadata(unit: Chunk, run_id: str, attempt: int) -> dict:
    """The per-Service trace join (ADR D44): the run stays ONE session
    (`langfuse_session_id` = the recon run id), and the unit slug + attempt tag
    each span so a pass can be read Service by Service."""
    return {
        "langfuse_tags": ["analyser", "supervisor", "service_sourced", "service_loop"],
        "langfuse_session_id": run_id,
        "recon_run_id": run_id,
        "service_unit": unit.chunk_id,
        "service_assets": len(unit.assets),
        "attempt": attempt,
    }


async def run_service_loop(
    project_id: str,
    run_id: str,
    *,
    units: list[Chunk] | None = None,
    read_fn=None,
    memory=None,
    invoke_fns: dict | None = None,
    inventory_fn=None,
    aggregations_fn=None,
    write_fn=None,
    proposer_bodies: dict | None = None,
    checkpointer=None,
    store=None,
    session_checkpointer=None,
    stop_fn: Callable[[], bool] | None = None,
    attempts: int = DEFAULT_UNIT_ATTEMPTS,
    observe: bool = True,
) -> ServiceLoopResult:
    """The per-Service loop (ADR D12-D20, D38-D42): for each unit, for each role in
    (mechanism_typist, data_modeller), run the role's `ReasoningWorkflow` scoped to
    the unit, through the supervisor control plane. Fail-open per unit with a
    bounded retry; a no-surface unit yields an explicit outcome; the loop checks
    `stop_fn` between units so a stop is honoured at a Service boundary. Returns
    the loop's terminal record."""
    from polymerhus.analysis.supervisor import _chunked_write_fn, build_supervisor_graph

    if units is None:
        units = build_service_slices(project_id, read_fn=read_fn)

    if memory is None:
        try:
            from polymerhus.analysis.memory import AnalysisMemoryStore

            memory = AnalysisMemoryStore()
        except Exception:  # noqa: BLE001 - no store -> the backstop is inert, never fatal
            memory = None

    if proposer_bodies is None:
        session_cp = session_checkpointer
        if session_cp is None:
            from polymerhus.app.llm.checkpoints import get_session_checkpointer

            session_cp = get_session_checkpointer()
        invoke_fns = dict(invoke_fns or {})
        if invoke_fns.get("mechanism_typist") is None:
            from polymerhus.analysis.mechanism_typist import stateful_invoke_fn as _t

            invoke_fns["mechanism_typist"] = _t(run_id, session_cp, project_id)
        if invoke_fns.get("data_modeller") is None:
            from polymerhus.analysis.data_modeller import stateful_invoke_fn as _d

            invoke_fns["data_modeller"] = _d(run_id, session_cp, project_id)
        proposer_bodies = _build_bodies(
            memory=memory, invoke_fns=invoke_fns, inventory_fn=inventory_fn,
            aggregations_fn=aggregations_fn, first_definer=True,
        )

    write_fn = write_fn or _chunked_write_fn
    builder = build_supervisor_graph(proposer_bodies=proposer_bodies, write_fn=write_fn)

    visited: list[str] = []
    outcomes: list[UnitOutcome] = []
    receipts_by_id: dict[str, StepReceipt] = {}
    stopped = False

    for unit in units:
        if stop_fn is not None and stop_fn():
            stopped = True
            logger.info("service_slice: stop requested at unit boundary before %s", unit.chunk_id)
            break
        visited.append(unit.chunk_id)

        if not unit.assets:
            # ADR D15: an explicit outcome, never a silent skip. The per-unit
            # backstop still records the Service so its coverage is auditable (D31).
            for role in SERVICE_ROLES:
                outcomes.append(UnitOutcome(unit=unit.chunk_id, role=role, status="no_surface"))
            _backstop_note(memory, project_id, unit.chunk_id, run_id)
            continue

        try:
            state, used = await _run_unit(
                builder, unit, project_id=project_id, run_id=run_id, attempts=attempts,
                checkpointer=checkpointer, store=store, observe=observe,
            )
        except Exception as exc:  # noqa: BLE001 - fail-open per unit, the loop continues
            logger.warning("service_slice: unit %s failed; continuing", unit.chunk_id, exc_info=True)
            for role in SERVICE_ROLES:
                outcomes.append(UnitOutcome(
                    unit=unit.chunk_id, role=role, status="degraded", error=str(exc)))
            continue
        unit_receipts = list(state.get("receipts") or [])
        for receipt in unit_receipts:
            receipts_by_id[receipt.dispatch_id] = receipt
        for role in SERVICE_ROLES:
            receipt = next((r for r in unit_receipts if r.role == role), None)
            if receipt is None:
                outcomes.append(UnitOutcome(
                    unit=unit.chunk_id, role=role, status="degraded", attempts=used,
                    error="no receipt",
                ))
            else:
                outcomes.append(UnitOutcome(
                    unit=unit.chunk_id, role=role, status=receipt.status,
                    attempts=used, error=receipt.error, written=receipt.written,
                ))

    receipts = tuple(receipts_by_id.values())
    written = [r for r in receipts if r.status == "written"]
    result = ServiceLoopResult(
        units=tuple(visited), outcomes=tuple(outcomes), receipts=receipts,
        stopped=stopped,
        aggregates_written=sum(r.written.aggregates for r in written),
        systems_written=sum(r.written.systems for r in written),
        data_items_written=sum(r.written.enrichment for r in written),
    )
    logger.info(
        "service_slice loop run=%s units=%d wrote=%s stopped=%s receipts=%d",
        run_id, len(visited), result.wrote, stopped, len(receipts),
    )
    return result


def _backstop_note(memory, project_id: str, unit: str, run_id: str) -> None:
    """The per-unit coverage backstop for a unit whose roles were not dispatched
    (no surface). Inert when no store is bound; fail-open always."""
    if memory is None or not unit:
        return
    try:
        from polymerhus.analysis.memory import ensure_unit_note

        ensure_unit_note(memory, project_id, unit, run_id=run_id)
    except Exception:  # noqa: BLE001 - the backstop is fail-open, never into the run
        logger.warning("service_slice: backstop note for %s failed; continuing", unit, exc_info=True)
