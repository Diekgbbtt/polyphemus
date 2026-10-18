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
retried.

This module owns the pure ordering; the driver (`run_lifecycle`) owns the run
record and the accumulator. The read seam is injectable (CODING_STANDARD s6):
the tests drive the pure mapper with rows, the production default reads the live
read-only L1 view.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, Sequence

from polymerhus.analysis.l1_curator import SYSTEM_EDGE_RELS
from polymerhus.analysis.l1_types import elide_singleton

logger = logging.getLogger(__name__)

# The live L1 edge families (S1 7.2), single-sourced from the L1 curator's
# §6 System-edge taxonomy: the ten families the ordering counts. A retired
# family (RENDERED_BY, or any other edge type) is never a live edge.
LIVE_L1_FAMILIES: frozenset[str] = frozenset(SYSTEM_EDGE_RELS)

# The L0-facing `AGGREGATES` hinge (S1 7.2): it is NOT an L1 edge - it feeds
# the aggregated-endpoint tie-break only. The other L0-facing family,
# `EVIDENCED_BY`, is never an L1 hop and so never even reaches the count.
AGGREGATES_FAMILY = "AGGREGATES"


@dataclass(frozen=True)
class IntakeUnit:
    """One frozen unit of the run's intake snapshot.

    `live_edge_count` is the unit's live L1 edge count in both directions and
    `endpoint_count` the aggregated endpoint count the tie-break reads; `kind`
    is the unit kind (`service` / `system`) as the run record and the model
    schema spell it.
    """

    unit_id: str
    kind: str
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
            slug = props.get("business_function_slug")
            unit_id = (
                unit_id_of("Service", slug)
                if isinstance(slug, str) and slug else ""
            )
            kind = "service"
        else:
            system_kind = props.get("kind")
            unit_id = (
                unit_id_of(str(system_kind), props.get("discriminator"))
                if system_kind else ""
            )
            kind = "system"
        if not unit_id or unit_id.endswith(":"):
            logger.warning(
                "unit intake: skipping an L1 node with no derivable identity (%s)",
                props,
            )
            continue
        endpoints = (
            int(row.get("endpoints") or 0)
            if kind == "service"
            else sum(linked.get(unit_id, {}).values())
        )
        units.append(IntakeUnit(
            unit_id=unit_id,
            kind=kind,
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


# The producing-run statuses that still hold a produced model (S2 9.3): a
# `running` run is live, an `interrupted` run is the resumable terminal (#331 -
# the earlier run must be resumed to drain its produced loops). Every other
# status is terminal and not resumable, so its produced model is stale.
RESUMABLE_RUN_STATUSES: frozenset[str] = frozenset({"running", "interrupted"})


def freeze_intake(
    units: Sequence[IntakeUnit],
    *,
    completed_ids: Sequence[str] = (),
    produced: Sequence[Mapping[str, str]] = (),
    run_statuses: Mapping[str, str] | None = None,
    archive_fn=None,
) -> IntakePlan:
    """Freeze the unit set: order it, then apply the exclusions (S2 9.3).

    - A unit with a COMPLETED, valid model in `consumed/` is excluded
      (`completed`): the model never evolves, so the run never re-models it.
    - A unit with a model in flight in `produced/` whose producing run is live
      or resumable is skipped (`in-flight`): a second writer would break the
      sole-writer invariant. A run with NO readable status is treated as
      in-flight too - the freeze never destroys a produced model it cannot
      attribute.
    - A produced model whose producing run is terminal and not resumable is
      STALE: its unit directory moves to `abandoned/` (`archive_fn`) and the
      unit is retried.
    - An `abandoned/` model is ignored and the unit retried: the freeze does not
      read that family at all.

    The exclusions are recorded in the frozen (sorted) order, so the run record's
    `intake_excluded` reads in the intake's own order.
    """
    statuses = dict(run_statuses or {})
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
            excluded.append(IntakeExclusion(unit.unit_id, "completed"))
            continue
        run_id = produced_run.get(unit.unit_id)
        if run_id is None:
            kept.append(unit)
            continue
        status = statuses.get(run_id)
        if status is None or status in RESUMABLE_RUN_STATUSES:
            excluded.append(IntakeExclusion(unit.unit_id, "in-flight"))
            continue
        reason = (
            f"stale produced model: its producing run {run_id} is {status!r}, "
            f"terminal and not resumable; the unit is retried"
        )
        if archive_fn is not None:
            try:
                archive_fn(unit.unit_id, reason)
            except Exception as exc:  # noqa: BLE001 - the archive is best-effort
                logger.warning(
                    "unit intake: archiving the stale produced model of %s "
                    "failed (%s); the unit is still retried", unit.unit_id, exc,
                )
                continue
        archived.append(unit.unit_id)
        logger.warning("unit intake: %s", reason)
        kept.append(unit)
    return IntakePlan(
        order=tuple(unit.unit_id for unit in kept),
        excluded=tuple(excluded),
        archived=tuple(archived),
    )


def read_intake(project_id: str, *, read_fn=None) -> tuple[IntakeUnit, ...]:
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
            f"COUNT {{ (u)-[:{AGGREGATES_FAMILY}]->(:Endpoint) }} AS endpoints",
            {"project_id": project_id, "families": sorted(LIVE_L1_FAMILIES)},
        )
        service_rows = read_fn(
            "MATCH (u:L1System) "
            "WHERE u.project_id = $project_id "
            "OPTIONAL MATCH (u)-[r]-(s:L1Service) "
            "WHERE type(r) IN $families AND s.project_id = $project_id "
            "RETURN u.kind AS kind, u.discriminator AS disc, "
            "s.business_function_slug AS slug, "
            f"COUNT {{ (s)-[:{AGGREGATES_FAMILY}]->(:Endpoint) }} AS endpoints",
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
    "IntakeExclusion",
    "IntakeUnit",
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
