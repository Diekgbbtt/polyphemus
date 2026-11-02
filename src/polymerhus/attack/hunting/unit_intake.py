"""The run intake freeze and the ordering algorithm (S1 7.1-7.2, S2 9.3; T3 #376).

At run start the runtime reads the L1 inventory and FREEZES the unit set: the
freeze is a run-level snapshot, and the modeller never re-reads the inventory
(S1 7.1). The frozen set is ordered once, recorded in the run as `intake_order`,
and never re-sorted (S1 7.4, ordering-halt ADR decision 2).

The sort key (S1 7.2):

  1. live L1 edge count, descending - counted in BOTH directions, over the live
     edge families only (retired families and retired edges never count);
  2. aggregated endpoint count, descending;
  3. unit id, ascending lexicographic.

The aggregated endpoint count is the Service's own `AGGREGATES` out-degree, and
for a System the sum of the `AGGREGATES` out-degree of the Services connected to
it by any live L1 edge (distinct Services, so several edges between the same
pair count once). `AGGREGATES` and `EVIDENCED_BY` are the L0-facing families:
they feed the tie-break only, never the edge count.

The exclusions (S2 9.3) are separate from the sort: a unit whose model already
lives COMPLETED in `consumed/` is excluded (`completed`); a unit whose model is
in flight in `produced/` while its producing run is live or resumable is skipped
(`in-flight`, the sole-writer guard); a model in `abandoned/` is ignored and the
unit is retried; a produced model whose producing run is terminal and not
resumable is STALE - its unit directory moves to `abandoned/` and the unit is
retried, and when that archive does not land the unit is excluded `stale` (never
modelled into the stale model). Every removal is recorded with its reason.

An `interrupted` producing run's resumability is decided by the ONE resume
decision table (`attack/hunting/resume.py`, T11 #398): a transient throttle
(including one still inside its backoff window) keeps its model in flight, while
a consumed-quota or unknown-cause pause is terminal and its model is stale.
The operator verb `POST /projects/{id}/hunting/{run_id}/resume` is the ratified
trigger; the auto-resume background health checker remains a follow-up.

This module owns the pure ordering; the driver (`run_lifecycle`) owns the run
record and the accumulator. The read seam is injectable (CODING_STANDARD s6):
the tests drive the pure mapper with rows, the production default reads the live
read-only L1 view.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from polymerhus.analysis.l1_curator import SYSTEM_EDGE_RELS
from polymerhus.analysis.l1_types import elide_singleton

logger = logging.getLogger(__name__)

# The injectable seams (CODING_STANDARD s6), typed so the agreement is explicit:
# `L1ReadFn` is the raw read seam (the `neo4j_client.read` contract) and
# `ArchiveFn` the stale-archive seam (the store's `archive_unit`; it returns the
# path it MOVED, or None when it moved nothing).
L1ReadFn = Callable[[str, dict], list]
ArchiveFn = Callable[[str, str], "Path | None"]

# The live L1 edge families (S1 7.2), single-sourced from the L1 curator's
# §6 System-edge taxonomy: the ten families the ordering counts. A retired
# family (RENDERED_BY, or any other edge type) is never a live edge.
LIVE_L1_FAMILIES: frozenset[str] = frozenset(SYSTEM_EDGE_RELS)

# The L0-facing `AGGREGATES` hinge (S1 7.2): it is NOT an L1 edge - it feeds
# the aggregated-endpoint tie-break only, counted over the unit's `AGGREGATES`
# out-edges without narrowing the target label. The other L0-facing family,
# `EVIDENCED_BY`, is never an L1 hop and so never even reaches the count.
AGGREGATES_FAMILY = "AGGREGATES"


@dataclass(frozen=True)
class IntakeUnit:
    """One frozen unit of the run's intake snapshot.

    `live_edge_count` is the unit's live L1 edge count in both directions and
    `endpoint_count` the aggregated endpoint count the tie-break reads. The unit
    KIND is deliberately not carried: it is derived from the unit id wherever it
    is needed (`threat_model.unit_kind_from_unit_id`, and the threat file's
    `unit_kind`), so the snapshot holds no data nothing reads.
    """

    unit_id: str
    live_edge_count: int = 0
    endpoint_count: int = 0


def order_intake(units: Sequence[IntakeUnit]) -> tuple[IntakeUnit, ...]:
    """The frozen intake order (S1 7.2).

    Deduplicated by unit id (the first snapshot entry of a unit wins: the read
    produces one row per L1 node), then sorted by live L1 edge count descending,
    aggregated endpoint count descending, and unit id ascending. The order is
    the research-yield order AND the halt order, so it is computed once and
    never re-sorted (ordering-halt ADR 2).
    """
    seen: dict[str, IntakeUnit] = {}
    for unit in units:
        seen.setdefault(unit.unit_id, unit)
    return tuple(sorted(
        seen.values(),
        key=lambda unit: (-unit.live_edge_count, -unit.endpoint_count, unit.unit_id),
    ))


def count_live_edges(edge_families: Sequence[str | None]) -> int:
    """The live L1 edge count of ONE unit, both directions (S1 7.2).

    The read collects the unit's L1 edge types in both directions; this counts
    the live families among them. A retired family (`RENDERED_BY`, or any edge
    type outside the §6 taxonomy) contributes nothing.
    """
    return sum(1 for family in edge_families if family in LIVE_L1_FAMILIES)


def unit_id_of(kind: str, discriminator: str | None) -> str:
    """The kind-qualified L1 identity (the run record's and the model's unit id).

    A Service is `Service:<business_function_slug>`; a System is `<kind>` for a
    singleton (the internal `L1_SINGLETON` sentinel is elided, #279 follow-up)
    and `<kind>:<discriminator>` otherwise. The same convention the L1 inventory
    render and the projection reader use.
    """
    if kind == "Service":
        return f"Service:{discriminator}"
    rendered = elide_singleton(discriminator)
    return f"{kind}:{rendered}" if rendered else kind


def intake_units_from_rows(
    unit_rows: Sequence[Mapping[str, object]],
    service_rows: Sequence[Mapping[str, object]] = (),
) -> tuple[IntakeUnit, ...]:
    """The pure mapping of the intake reads into the frozen unit snapshot.

    `unit_rows` is one row per L1 unit: its labels, its properties, the edge
    families of its L1 hops in BOTH directions, and its own `AGGREGATES`
    out-degree. `service_rows` is the System-to-Service adjacency (one row per
    linked Service, carrying that Service's `AGGREGATES` out-degree).
    """
    linked: dict[str, dict[str, int]] = {}
    for row in service_rows:
        slug = row.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        system_id = unit_id_of(str(row.get("kind") or ""), row.get("disc"))
        linked.setdefault(system_id, {})[slug] = int(row.get("endpoints") or 0)

    units: list[IntakeUnit] = []
    for row in unit_rows:
        labels = [str(label) for label in (row.get("labels") or [])]
        props = dict(row.get("props") or {})
        if "L1Service" in labels:
            # a Service aggregates its OWN Endpoints; a System sums the ones its
            # connected Services aggregate (S1 7.2)
            slug = props.get("business_function_slug")
            unit_id = (
                unit_id_of("Service", slug)
                if isinstance(slug, str) and slug else ""
            )
            endpoints = int(row.get("endpoints") or 0)
        else:
            system_kind = props.get("kind")
            unit_id = (
                unit_id_of(str(system_kind), props.get("discriminator"))
                if system_kind else ""
            )
            endpoints = sum(linked.get(unit_id, {}).values())
        if not unit_id or unit_id.endswith(":"):
            logger.warning(
                "unit intake: skipping an L1 node with no derivable identity (%s)",
                props,
            )
            continue
        units.append(IntakeUnit(
            unit_id=unit_id,
            live_edge_count=count_live_edges(row.get("edge_families") or []),
            endpoint_count=endpoints,
        ))
    return tuple(units)


@dataclass(frozen=True)
class IntakeExclusion:
    """One excluded unit and the reason it was excluded (S2 9.2)."""

    unit_id: str
    reason: str


@dataclass(frozen=True)
class IntakePlan:
    """The frozen intake: the ordered units to model, the exclusions, and the
    stale produced models the freeze archived (S2 9.3)."""

    order: tuple[str, ...]
    excluded: tuple[IntakeExclusion, ...] = ()
    archived: tuple[str, ...] = ()


# The exclusion reasons the run record carries (S2 9.2): `completed` (a decided
# model in `consumed/`), `in-flight` (a produced model a live/resumable run still
# owns) and `stale` (a produced model of a terminal run whose archive did not
# land, so the unit must not be modelled into it - an implementation-time
# addition recorded in the artifact spec and the impact map).
COMPLETED_REASON = "completed"
IN_FLIGHT_REASON = "in-flight"
STALE_REASON = "stale"

# The producing-run statuses that still hold a produced model (S2 9.3): a
# `running` run is live, and `stopped` (the operator's deliberate end, which
# resumes from the persisted run record, S1 7.5) is RESUMABLE - the earlier run
# must be resumed to drain its produced threats, so its model is in flight, never
# stale. A status we cannot read (None) is treated as in flight too: the freeze
# never destroys a produced model it cannot attribute.
#
# `interrupted` is decided by the resume decision table (#331, T11 #398), not by
# the status alone: a transient throttle (resumable now, or after its
# `retry_after_s` window) keeps its model in flight, while consumed quota and a
# missing/unknown cause are terminal - their produced model is stale and is
# archived exactly like a `complete` / `failed` run's. The caller supplies that
# per-run answer in `run_resumability`; an absent entry is in flight (fail-open).
RESUMABLE_RUN_STATUSES: frozenset[str] = frozenset({"running", "stopped"})
INTERRUPTED_STATUS = "interrupted"


def freeze_intake(
    units: Sequence[IntakeUnit],
    *,
    completed_ids: Sequence[str] = (),
    produced: Sequence[Mapping[str, str]] = (),
    run_statuses: Mapping[str, str] | None = None,
    run_resumability: Mapping[str, bool] | None = None,
    archive_fn: ArchiveFn | None = None,
) -> IntakePlan:
    """Freeze the unit set: order it, then apply the exclusions (S2 9.3).

    - A unit with a COMPLETED, valid model in `consumed/` is excluded
      (`completed`): the model never evolves, so the run never re-models it.
    - A unit with a model in flight in `produced/` whose producing run is live
      or resumable is skipped (`in-flight`): a second writer would break the
      sole-writer invariant. A run with NO readable status is treated as
      in-flight too - the freeze never destroys a produced model it cannot
      attribute.
    - An `interrupted` producing run's resumability comes from
      `run_resumability` (the ONE resume decision table, T11 #398): True (a
      transient throttle, including one inside its backoff window) keeps the
      model in flight; False (consumed quota, or a missing/unknown cause) is
      terminal, so the model is STALE. A run with NO entry is in flight -
      fail-open, like an unreadable status.
    - A produced model whose producing run is terminal and not resumable is
      STALE: its unit directory moves to `abandoned/` (`archive_fn`) and the
      unit is retried. `archived` records ONLY the units that actually MOVED;
      an archive that did NOT land (a raise, or a store reporting nothing to
      move) leaves the stale model in place, so the unit is recorded `stale` in
      `excluded` and is NOT retried into it (a stale COMPLETED model would seed
      the retry's tracker and be re-counted as if the run had modelled it).
    - An `abandoned/` model is ignored and the unit retried: the freeze does not
      read that family at all.

    Every unit the freeze removes is recorded: the exclusions are written in the
    frozen (sorted) order, so the run record's `intake_excluded` reads in the
    intake's own order, and each carries its reason from `COMPLETED_REASON` /
    `IN_FLIGHT_REASON` / `STALE_REASON` (S1 7.1, S2 9.2).
    """
    statuses = dict(run_statuses or {})
    resumability = dict(run_resumability or {})
    completed = set(completed_ids)
    produced_run: dict[str, str] = {}
    for entry in produced:
        unit_id = entry.get("unit_id")
        if not unit_id:
            continue
        produced_run[unit_id] = str(entry.get("run_id") or "")

    excluded: list[IntakeExclusion] = []
    archived: list[str] = []
    kept: list[IntakeUnit] = []
    for unit in order_intake(units):
        if unit.unit_id in completed:
            excluded.append(IntakeExclusion(unit.unit_id, COMPLETED_REASON))
            continue
        run_id = produced_run.get(unit.unit_id)
        if run_id is None:
            kept.append(unit)
            continue
        status = statuses.get(run_id)
        in_flight = status is None or status in RESUMABLE_RUN_STATUSES
        if status == INTERRUPTED_STATUS:
            # the #331 resume decision (T11 #398): only a RESUMABLE throttle
            # still owns its produced model; a terminal/do-not-resume pause is
            # stale. No entry means the caller could not classify it: in flight.
            in_flight = resumability.get(run_id, True)
        if in_flight:
            excluded.append(IntakeExclusion(unit.unit_id, IN_FLIGHT_REASON))
            detail = (
                f"its producing run {run_id!r} is {status!r}" if run_id
                else "its producing run is unknown"
            )
            logger.warning(
                "unit intake: %s is in flight (%s); that run must be RESUMED "
                "(POST /projects/<project_id>/hunting/<run_id>/resume) to drain "
                "its produced model. The operator verb is the ratified trigger; "
                "the auto-resume health checker is a follow-up", unit.unit_id,
                detail,
            )
            continue
        reason = (
            f"stale produced model: its producing run {run_id} is {status!r}, "
            f"terminal and not resumable; the unit is retried"
        )
        destination = None
        if archive_fn is None:
            # No archive seam is bound: an injected/intake-only call, or a
            # caller with no produced family. The stale model is left in place
            # and the unit is retried; the production caller
            # (`runtime._freeze_intake`) always binds the store's
            # `archive_unit` when a produced family exists.
            logger.warning(
                "unit intake: %s (no archive seam bound; the stale produced "
                "model is left in place and the unit is retried)", reason,
            )
        else:
            try:
                destination = archive_fn(unit.unit_id, reason)
            except Exception as exc:  # noqa: BLE001 - the archive is best-effort
                logger.warning(
                    "unit intake: archiving the stale produced model of %s "
                    "failed (%s); the unit is recorded `stale` and NOT retried "
                    "this run (a stale model must never be modelled into)",
                    unit.unit_id, exc,
                )
                excluded.append(IntakeExclusion(unit.unit_id, STALE_REASON))
                continue
            if destination is None:
                # the archive reported nothing to move: the stale produced
                # directory is still there, so the unit takes the SAME handling
                # as a failed archive (M2) - recorded `stale`, never modelled
                logger.warning(
                    "unit intake: the archive of %s reported nothing to move; "
                    "the unit is recorded `stale` and NOT retried this run",
                    unit.unit_id,
                )
                excluded.append(IntakeExclusion(unit.unit_id, STALE_REASON))
                continue
            archived.append(unit.unit_id)
            logger.warning("unit intake: %s", reason)
        kept.append(unit)
    return IntakePlan(
        order=tuple(unit.unit_id for unit in kept),
        excluded=tuple(excluded),
        archived=tuple(archived),
    )


def read_intake(project_id: str, *, read_fn: L1ReadFn | None = None) -> tuple[IntakeUnit, ...]:
    """The intake read over the live L1 view (S1 7.1-7.2).

    Two reads: the project's L1 units with their edge families in both
    directions and their own `AGGREGATES` out-degree, then the System-to-Service
    adjacency carrying each linked Service's `AGGREGATES` out-degree. The pure
    mapper counts the live families and aggregates the endpoints.

    Fail-open: a read error degrades to the empty intake with a warning, never a
    raise into the run (the `read_l1_inventory` contract); the regression is then
    recorded as an empty `intake_order` in the run record.
    """
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client  # noqa: PLC0415

        read_fn = neo4j_client.read
    try:
        unit_rows = read_fn(
            "MATCH (u:L1TestableUnit) "
            "WHERE u.project_id = $project_id "
            "OPTIONAL MATCH (u)-[r]-(:L1TestableUnit) "
            "WHERE type(r) IN $families "
            "RETURN labels(u) AS labels, properties(u) AS props, "
            "collect(type(r)) AS edge_families, "
            f"COUNT {{ (u)-[:{AGGREGATES_FAMILY}]->(e) }} AS endpoints",
            {"project_id": project_id, "families": sorted(LIVE_L1_FAMILIES)},
        )
        service_rows = read_fn(
            "MATCH (u:L1System) "
            "WHERE u.project_id = $project_id "
            "OPTIONAL MATCH (u)-[r]-(s:L1Service) "
            "WHERE type(r) IN $families AND s.project_id = $project_id "
            "RETURN u.kind AS kind, u.discriminator AS disc, "
            "s.business_function_slug AS slug, "
            f"COUNT {{ (s)-[:{AGGREGATES_FAMILY}]->(e) }} AS endpoints",
            {"project_id": project_id, "families": sorted(LIVE_L1_FAMILIES)},
        )
        # the mapper runs INSIDE the guard: a malformed row degrades the whole
        # read to the empty intake, exactly like a failed read (fail-open)
        return intake_units_from_rows(unit_rows or [], service_rows or ())
    except Exception as exc:  # noqa: BLE001 - fail-open is the intake contract
        logger.warning(
            "unit intake read degraded for project %s; the intake is empty "
            "(fail-open): %s", project_id, exc,
        )
        return ()


__all__ = [
    "AGGREGATES_FAMILY",
    "COMPLETED_REASON",
    "IN_FLIGHT_REASON",
    "INTERRUPTED_STATUS",
    "STALE_REASON",
    "ArchiveFn",
    "IntakeExclusion",
    "IntakeUnit",
    "L1ReadFn",
    "IntakePlan",
    "LIVE_L1_FAMILIES",
    "RESUMABLE_RUN_STATUSES",
    "count_live_edges",
    "freeze_intake",
    "intake_units_from_rows",
    "order_intake",
    "read_intake",
    "unit_id_of",
]
