"""Unit tier: the run intake freeze and the ordering algorithm (S1 7.1-7.2,
S2 9.3; ticket T3 #376).

The ordering is a pure function over a frozen per-unit snapshot; the freeze is
the exclusion pass over the project's threat model store families and the
producing runs' statuses. No live Neo4j, no live PG: the L1 read seam is a
fake, the store is a real temp-root `ThreatModelStore`.
"""
from __future__ import annotations

from polymerhus.attack.hunting.unit_intake import (
    LIVE_L1_FAMILIES,
    IntakeUnit,
    freeze_intake,
    intake_units_from_rows,
    order_intake,
    read_intake,
)


def _unit(unit_id: str, *, live_edges: int = 0, endpoints: int = 0) -> IntakeUnit:
    return IntakeUnit(
        unit_id=unit_id,
        live_edge_count=live_edges,
        endpoint_count=endpoints,
    )


def test_order_intake_sorts_by_live_edge_count_descending():
    """S1 7.2: the first sort key is the live L1 edge count, descending."""
    units = [
        _unit("Service:a", live_edges=1),
        _unit("GraphQLApi", live_edges=7),
        _unit("Service:b", live_edges=3),
    ]

    assert [unit.unit_id for unit in order_intake(units)] == [
        "GraphQLApi", "Service:b", "Service:a",
    ]


def test_intake_rows_count_only_the_live_edge_families():
    """S1 7.2: the count ranges over the live L1 edge families only. A retired
    family (RENDERED_BY) and the L0-facing `AGGREGATES` hinge never count as L1
    edges, in EITHER direction."""
    rows = [{
        "labels": ["L1Service"],
        "props": {"business_function_slug": "a"},
        "edge_families": [
            "EXPOSED_VIA", "RENDERED_BY", "AGGREGATES", "DEPENDS_ON", None,
        ],
        "endpoints": 4,
    }]

    assert intake_units_from_rows(rows, []) == (
        IntakeUnit(unit_id="Service:a", live_edge_count=2, endpoint_count=4),
    )


def test_order_intake_tie_breaks_by_endpoints_then_unit_id():
    """S1 7.2: equal live edge counts break by aggregated endpoint count
    descending, then by unit id ascending lexicographic."""
    units = [
        _unit("Service:b", live_edges=2, endpoints=1),
        _unit("Service:a", live_edges=2, endpoints=3),
        _unit("Service:c", live_edges=2, endpoints=1),
        _unit("Service:d", live_edges=3),
    ]

    assert [unit.unit_id for unit in order_intake(units)] == [
        "Service:d", "Service:a", "Service:b", "Service:c",
    ]


def test_a_system_endpoint_count_sums_its_distinct_connected_services():
    """S1 7.2: a System's aggregated endpoint count is the sum of the
    `AGGREGATES` out-degree of the Services connected to it by a live L1 edge.
    The Services are deduplicated by unit id, so several live edges between the
    same System and Service count that Service once."""
    unit_rows = [{
        "labels": ["L1System"],
        "props": {"kind": "GraphQLApi", "discriminator": "__singleton__"},
        "edge_families": ["EXPOSED_VIA", "ROUTED_BY"],
        "endpoints": 0,
    }]
    service_rows = [
        {"kind": "GraphQLApi", "disc": "__singleton__", "slug": "s1", "endpoints": 3},
        {"kind": "GraphQLApi", "disc": "__singleton__", "slug": "s1", "endpoints": 3},
        {"kind": "GraphQLApi", "disc": "__singleton__", "slug": "s2", "endpoints": 5},
    ]

    assert intake_units_from_rows(unit_rows, service_rows) == (
        IntakeUnit(unit_id="GraphQLApi",
                   live_edge_count=2, endpoint_count=8),
    )


PROJECT = "intake-proj"


def test_read_intake_counts_every_l1_edge_in_both_directions():
    """S1 7.2: the read ranges over the L1 units and their edges in BOTH
    directions (an undirected hop over the live families), so an inbound
    `EXPOSED_VIA` from a Service counts for the System it fronts."""
    seen: list[tuple[str, dict]] = []

    def read(cypher, params):
        seen.append((cypher, dict(params or {})))
        if "L1TestableUnit" in cypher:
            return [{
                "labels": ["L1Service"],
                "props": {"business_function_slug": "a"},
                "edge_families": ["EXPOSED_VIA", "DEPENDS_ON", "RENDERED_BY"],
                "endpoints": 2,
            }]
        return []

    units = read_intake(PROJECT, read_fn=read)

    assert units == (IntakeUnit(unit_id="Service:a", live_edge_count=2,
                                endpoint_count=2),)
    cypher, params = seen[0]
    assert "-[r]-(:L1TestableUnit)" in cypher, "the L1 hop must be undirected"
    assert params["families"] == sorted(LIVE_L1_FAMILIES)
    assert params["project_id"] == PROJECT


def test_the_endpoint_count_ranges_over_every_aggregates_out_edge():
    """S1 7.2: the tie-break reads the unit's `AGGREGATES` OUT-edges, so the
    count must not narrow the target to the L0 `:Endpoint` label (the repo's
    other aggregate reads range over the family alone)."""
    seen: list[str] = []

    def read(cypher, params):
        seen.append(cypher)
        return []

    read_intake(PROJECT, read_fn=read)

    assert len(seen) == 2                 # the unit read and the adjacency read
    for cypher in seen:
        assert "AGGREGATES" in cypher
        assert ":Endpoint" not in cypher, (
            "the AGGREGATES count must not narrow the target label"
        )


def test_the_system_adjacency_read_is_filtered_by_the_live_families():
    """S1 7.2: a System's endpoint count sums the Services connected by a LIVE L1
    edge - the adjacency read carries the family filter in its cypher AND the
    live family set as its parameter (a retired family must never contribute)."""
    seen: list[tuple[str, dict]] = []

    def read(cypher, params):
        seen.append((cypher, dict(params or {})))
        return []

    read_intake(PROJECT, read_fn=read)

    adjacency_cypher, adjacency_params = seen[1]
    assert "s:L1Service" in adjacency_cypher
    assert "type(r) IN $families" in adjacency_cypher
    assert adjacency_params["families"] == sorted(LIVE_L1_FAMILIES)


def test_read_intake_fails_open_to_an_empty_intake():
    """S1 5.7 / the read contract: a degraded L1 read degrades the intake to the
    empty set with a warning, never a raise into the run."""
    def read(cypher, params):
        raise OSError("neo4j down (fixture)")

    assert read_intake(PROJECT, read_fn=read) == ()


def test_order_intake_keeps_one_snapshot_entry_per_unit_id():
    """S1 7.1: the unit SET is a set - a duplicated snapshot row never orders a
    unit twice."""
    units = [_unit("Service:a", live_edges=1), _unit("Service:a", live_edges=9)]

    assert [unit.unit_id for unit in order_intake(units)] == ["Service:a"]


def test_a_row_without_a_derivable_identity_is_skipped():
    """S1 7.1: the intake never fabricates an identity - an L1 row with no slug /
    kind contributes no unit (a `Service:None` would address no model)."""
    rows = [
        {"labels": ["L1Service"], "props": {}, "edge_families": [],
         "endpoints": 0},
        {"labels": ["L1System"], "props": {"kind": ""}, "edge_families": [],
         "endpoints": 0},
        {"labels": ["L1Service"], "props": {"business_function_slug": "a"},
         "edge_families": ["EXPOSED_VIA"], "endpoints": 1},
    ]

    assert [unit.unit_id for unit in intake_units_from_rows(rows)] == [
        "Service:a"]


def test_freeze_intake_excludes_completed_and_in_flight_units():
    """S2 9.3: a unit whose model is already COMPLETED in `consumed/` is
    excluded (`completed`), and a unit whose model is in flight in `produced/`
    while its producing run is live is skipped (`in-flight`) - the sole-writer
    guard. Every exclusion is recorded with its reason, in intake order."""
    units = [
        _unit("Service:a", live_edges=3),
        _unit("Service:b", live_edges=2),
        _unit("Service:c", live_edges=1),
        _unit("Service:d"),
    ]

    plan = freeze_intake(
        units,
        completed_ids=["Service:b"],
        produced=[
            {"unit_id": "Service:c", "run_id": "run-1"},
            {"unit_id": "Service:d", "run_id": "run-2"},
        ],
        run_statuses={"run-1": "running", "run-2": "interrupted"},
    )

    assert plan.order == ("Service:a",)
    assert [(entry.unit_id, entry.reason) for entry in plan.excluded] == [
        ("Service:b", "completed"),
        ("Service:c", "in-flight"),
        ("Service:d", "in-flight"),
    ]
    assert plan.archived == ()


def test_a_failed_stale_archive_records_the_unit_as_stale_excluded():
    """S2 9.2 / S1 7.1: a unit whose stale produced model could NOT be archived
    (the store refuses, or `os.replace` fails) is neither modelled nor silently
    dropped: it is recorded in `intake_excluded` with the reason `stale`, so the
    run record names every unit the freeze removed and why."""
    def _explode(unit_id, reason):
        raise OSError("disk full (fixture)")

    plan = freeze_intake(
        [_unit("Service:a", live_edges=2)],
        produced=[{"unit_id": "Service:a", "run_id": "dead-run"}],
        run_statuses={"dead-run": "complete"},
        archive_fn=_explode,
    )

    assert plan.order == ()            # never modelled into a stale model
    assert plan.archived == ()
    assert [(entry.unit_id, entry.reason) for entry in plan.excluded] == [
        ("Service:a", "stale")]


def test_a_stopped_producing_run_is_resumable_so_its_model_is_in_flight():
    """S1 7.5 / S2 9.3: a `stopped` run resumes from the persisted run record, so
    its produced model is IN FLIGHT - the new run skips the unit and never
    archives the stopped run's model. `complete` / `failed` stay terminal and
    not resumable, so only their stale models are archived."""
    archived: list[str] = []

    plan = freeze_intake(
        [_unit("Service:a", live_edges=2)],
        produced=[{"unit_id": "Service:a", "run_id": "stopped-run"}],
        run_statuses={"stopped-run": "stopped"},
        archive_fn=lambda unit_id, reason: archived.append(unit_id) or "moved",
    )

    assert plan.order == ()
    assert [(entry.unit_id, entry.reason) for entry in plan.excluded] == [
        ("Service:a", "in-flight")]
    assert plan.archived == ()
    assert archived == []


def test_an_in_flight_skip_names_the_producing_run_and_its_status(caplog):
    """I2 disposition: no production path re-enters a run yet (the resume
    trigger is the deferred #331 ticket), so the freeze must make a blocked unit
    diagnosable - the in-flight skip names the producing run and its status, and
    the exclusion keeps the fixed `in-flight` reason (S2 9.2)."""
    with caplog.at_level("WARNING",
                         logger="polymerhus.attack.hunting.unit_intake"):
        plan = freeze_intake(
            [_unit("Service:a", live_edges=1)],
            produced=[{"unit_id": "Service:a", "run_id": "stopped-run"}],
            run_statuses={"stopped-run": "stopped"},
        )

    assert [(entry.unit_id, entry.reason) for entry in plan.excluded] == [
        ("Service:a", "in-flight")]
    assert plan.order == ()
    line = next(record.message for record in caplog.records
                if "in flight" in record.message)
    assert "Service:a" in line
    assert "stopped-run" in line and "stopped" in line


def test_the_freeze_records_only_archives_that_actually_moved():
    """S2 9.3: `IntakePlan.archived` names the units whose stale produced model
    MOVED to `abandoned/`. A freeze with no archive seam keeps the unit (the
    caller owns the produced family), and an archive that reports NOTHING TO MOVE
    takes the same handling as a failed one: the stale directory is still there,
    so the unit must not be modelled into it."""
    units = [_unit("Service:a", live_edges=1)]
    produced = [{"unit_id": "Service:a", "run_id": "dead-run"}]
    statuses = {"dead-run": "complete"}

    no_seam = freeze_intake(units, produced=produced, run_statuses=statuses)
    assert no_seam.order == ("Service:a",)
    assert no_seam.archived == ()
    assert no_seam.excluded == ()

    nothing_moved = freeze_intake(
        units, produced=produced, run_statuses=statuses,
        archive_fn=lambda unit_id, reason: None)
    assert nothing_moved.order == ()
    assert nothing_moved.archived == ()
    assert [(entry.unit_id, entry.reason) for entry in nothing_moved.excluded] == [
        ("Service:a", "stale")]

    moved = freeze_intake(
        units, produced=produced, run_statuses=statuses,
        archive_fn=lambda unit_id, reason: f"abandoned/{unit_id}")
    assert moved.order == ("Service:a",)
    assert moved.archived == ("Service:a",)
    assert moved.excluded == ()



def test_a_stale_produced_model_of_a_terminal_run_is_archived_and_retried():
    """S2 9.3: when the producing run is terminal and not resumable, the intake
    moves the stale produced directory to `abandoned/` and retries the unit -
    the unit stays in the intake order."""
    archived: list[tuple[str, str]] = []

    def _archive(unit_id: str, reason: str) -> str:
        """The store's archive seam: it MOVED the directory (a non-None path)."""
        archived.append((unit_id, reason))
        return f"abandoned/{unit_id}"

    plan = freeze_intake(
        [_unit("Service:a", live_edges=2)],
        produced=[{"unit_id": "Service:a", "run_id": "old-run"}],
        run_statuses={"old-run": "complete"},
        archive_fn=_archive,
    )

    assert plan.order == ("Service:a",)
    assert plan.excluded == ()
    assert plan.archived == ("Service:a",)
    assert archived[0][0] == "Service:a"
    assert "old-run" in archived[0][1]
