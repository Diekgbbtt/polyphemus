"""Unit tier for the per-Service slice builder and loop (T5, ADR D12-D20, D38-D40).

The builder is PURE over an injected read seam: the live L1 Service inventory,
the Service->L0 aggregation view, and the settled L0 surface. It groups the
surface into one `Chunk` per Service (chunk_id = the sanitised Service slug) plus
one residual unit for unaggregated surface. The loop visits the units in order,
runs mechanism_typist then data_modeller per unit through the supervisor graph,
is fail-open per unit with a bounded retry, and records per-unit outcomes and
receipts.

Everything is injected (read_fn / proposer_bodies / write_fn / stop_fn), so the
whole tier runs with no Neo4j, no LLM and no database.
"""
import asyncio

from polymerhus.analysis.analyser_types import AggregatesProposal, L1DeltaBatch
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.service_slice import (
    RESIDUAL_UNIT,
    build_service_slices,
    run_service_loop,
    sanitise_slug,
)
from polymerhus.recon.domain.types import AssetDelta


def _run(coro):
    return asyncio.run(coro)


def _endpoint(path, baseurl="https://s"):
    return AssetDelta(type="Endpoint", identity={"path": path, "method": "GET", "baseurl": baseurl})


def _row(slug, path, baseurl="https://s"):
    return {"slug": slug, "labels": ["Endpoint"],
            "props": {"path": path, "method": "GET", "baseurl": baseurl}}


# --- the pure builder ---------------------------------------------------------

def test_builds_one_unit_per_service_sorted_and_the_residual_last():
    read = lambda pid: (
        ["fulfilment", "checkout"],                       # inventory (unsorted)
        [_row("checkout", "/orders"), _row("fulfilment", "/ship")],
        [_endpoint("/orders"), _endpoint("/ship"), _endpoint("/health")],
    )
    units = build_service_slices("p1", read_fn=read)

    assert [u.chunk_id for u in units] == ["checkout", "fulfilment", RESIDUAL_UNIT]
    owned = {u.chunk_id: {a.identity["path"] for a in u.assets} for u in units}
    assert owned["checkout"] == {"/orders"}
    assert owned["fulfilment"] == {"/ship"}
    # the residual carries the unaggregated surface
    assert owned[RESIDUAL_UNIT] == {"/health"}


def test_no_residual_unit_when_everything_is_aggregated():
    read = lambda pid: (
        ["checkout"], [_row("checkout", "/a")], [_endpoint("/a")],
    )
    units = build_service_slices("p1", read_fn=read)
    assert [u.chunk_id for u in units] == ["checkout"]


def test_a_service_with_no_aggregated_surface_still_yields_a_unit():
    """ADR D15: a Service with no aggregated surface is visited, never silently
    skipped, so its absence of surface is an explicit outcome."""
    read = lambda pid: (
        ["checkout", "empty-svc"], [_row("checkout", "/a")], [_endpoint("/a")],
    )
    units = build_service_slices("p1", read_fn=read)
    by_id = {u.chunk_id: u for u in units}
    assert by_id["empty-svc"].assets == ()


def test_builder_is_deterministic_for_a_permuted_inventory():
    assets = [_endpoint("/a"), _endpoint("/b")]
    aggs = [_row("checkout", "/a"), _row("fulfilment", "/b")]
    a = build_service_slices("p1", read_fn=lambda pid: (["checkout", "fulfilment"], aggs, assets))
    b = build_service_slices("p1", read_fn=lambda pid: (["fulfilment", "checkout"], aggs, assets))
    assert [u.chunk_id for u in a] == [u.chunk_id for u in b]


def test_read_failure_yields_no_units():
    def boom(pid):
        raise RuntimeError("neo4j down")

    assert build_service_slices("p1", read_fn=boom) == []


def test_builds_a_system_unit_with_rider_surface_and_evidence():
    """v2 (ADR D46): with a `systems_fn` seam, ONE System unit per L1 System is
    appended; its assets are the surface of every Service that rides it PLUS the
    L0 nodes it is EVIDENCED_BY."""
    read = lambda pid: (
        ["checkout"], [_row("checkout", "/orders")],
        [_endpoint("/orders"), _endpoint("/health")],
    )

    def systems(pid):
        riders = [{"kind": "RESTApi", "discriminator": "core-rest", "slug": "checkout"}]
        evidence = [{
            "kind": "AuthenticationSystem", "discriminator": "__singleton__",
            "labels": ["Endpoint"],
            "props": {"path": "/health", "method": "GET", "baseurl": "https://s"},
        }]
        return riders, evidence

    units = build_service_slices("p1", read_fn=read, systems_fn=systems)
    by_src = {u.source_job: u for u in units}
    assert "system:RESTApi:core-rest" in by_src          # the rider's mechanism
    assert "system:AuthenticationSystem" in by_src       # the singleton key
    assert {a.identity["path"] for a in by_src["system:RESTApi:core-rest"].assets} == {"/orders"}
    assert {a.identity["path"] for a in by_src["system:AuthenticationSystem"].assets} == {"/health"}


def test_no_system_units_without_a_systems_seam():
    read = lambda pid: (["checkout"], [_row("checkout", "/a")], [_endpoint("/a")])
    units = build_service_slices("p1", read_fn=read)
    assert all(not u.source_job.startswith("system:") for u in units)


def test_roles_for_dispatches_the_typist_only_on_system_and_residual():
    from polymerhus.analysis.service_slice import _roles_for

    assert _roles_for(Chunk(chunk_id="checkout", source_job="service:checkout", assets=())) == (
        "mechanism_typist", "data_modeller")
    assert _roles_for(Chunk(chunk_id="RESTApi", source_job="system:RESTApi", assets=())) == (
        "mechanism_typist",)
    assert _roles_for(Chunk(chunk_id=RESIDUAL_UNIT, source_job="residual", assets=())) == (
        "mechanism_typist",)


def test_sanitise_slug_is_boundary_safe_and_bounded():
    # an ordinary Service slug is unchanged (so chunk_id IS the Service slug)
    assert sanitise_slug("checkout") == "checkout"
    # the address separator never reaches a thread_id
    assert ":" not in sanitise_slug("checkout:admin")
    assert sanitise_slug("  ") != ""
    long = sanitise_slug("a" * 200)
    assert len(long) <= 80 and long != "a" * 200


# --- the loop -----------------------------------------------------------------

class _Export:
    def __init__(self, aggregates=1, systems=0, enrichment=None):
        self.services_written = 0
        self.systems_written = systems
        self.aggregates_written = aggregates
        self.enrichment = enrichment or {}


def _fake_write_fn(counts):
    def write(deltas, project_id, provenance):
        return _Export(**counts)
    return write


def _ok_body(log, role, *, counts=None):
    counts = counts or {}
    def body(dispatch, state):
        log.append((dispatch.chunk.chunk_id, role))
        return L1DeltaBatch(aggregates=[AggregatesProposal(
            service_slug="checkout", l0={"label": "Endpoint", "identity": {"path": "/x"}},
            confidence=0.9, evidence_refs=["path segment /x"])])
    return body


def test_loop_visits_units_in_order_and_roles_in_order_per_unit():
    units = [Chunk(chunk_id="checkout", assets=(_endpoint("/a"),)),
             Chunk(chunk_id="fulfilment", assets=(_endpoint("/b"),))]
    log = []
    bodies = {
        "mechanism_typist": _ok_body(log, "mechanism_typist"),
        "data_modeller": _ok_body(log, "data_modeller"),
    }
    result = _run(run_service_loop(
        "p1", "r1", units=units, proposer_bodies=bodies,
        write_fn=_fake_write_fn({}), observe=False,
    ))
    assert log == [
        ("checkout", "mechanism_typist"), ("checkout", "data_modeller"),
        ("fulfilment", "mechanism_typist"), ("fulfilment", "data_modeller"),
    ]
    assert result.units == ("checkout", "fulfilment")
    assert result.wrote is True


def test_loop_records_per_unit_receipts_and_outcomes():
    units = [Chunk(chunk_id="checkout", assets=(_endpoint("/a"),))]
    log = []
    bodies = {
        "mechanism_typist": _ok_body(log, "mechanism_typist"),
        "data_modeller": _ok_body(log, "data_modeller"),
    }
    result = _run(run_service_loop(
        "p1", "r1", units=units, proposer_bodies=bodies,
        write_fn=_fake_write_fn({}), observe=False,
    ))
    assert {r.role for r in result.receipts} == {"mechanism_typist", "data_modeller"}
    assert all(r.status == "written" for r in result.receipts)
    assert {o.unit for o in result.outcomes} == {"checkout"}
    assert all(o.status == "written" for o in result.outcomes)


def test_no_surface_unit_yields_an_explicit_outcome_and_is_not_dispatched():
    units = [Chunk(chunk_id="empty-svc", assets=())]
    log = []
    bodies = {
        "mechanism_typist": _ok_body(log, "mechanism_typist"),
        "data_modeller": _ok_body(log, "data_modeller"),
    }
    result = _run(run_service_loop(
        "p1", "r1", units=units, proposer_bodies=bodies,
        write_fn=_fake_write_fn({}), observe=False,
    ))
    assert log == []                                          # never dispatched
    assert [o.status for o in result.outcomes] == ["no_surface", "no_surface"]
    assert result.wrote is False


def test_bounded_retry_recovers_a_unit_whose_first_attempt_degraded():
    calls = {"n": 0}

    def flaky(dispatch, state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient provider error")
        return L1DeltaBatch(aggregates=[AggregatesProposal(
            service_slug="checkout", l0={"label": "Endpoint", "identity": {"path": "/x"}},
            confidence=0.9, evidence_refs=["path segment /x"])])

    units = [Chunk(chunk_id="checkout", assets=(_endpoint("/a"),))]
    result = _run(run_service_loop(
        "p1", "r1", units=units,
        proposer_bodies={"mechanism_typist": flaky, "data_modeller": flaky},
        write_fn=_fake_write_fn({}), attempts=2, observe=False,
    ))
    assert calls["n"] == 4                    # attempt 1 degraded, attempt 2 clean (2 roles)
    assert result.wrote is True
    assert all(o.status == "written" for o in result.outcomes)


def test_an_always_degraded_unit_is_fail_open_and_does_not_stop_the_loop():
    visited = []

    def boom(dispatch, state):
        visited.append(dispatch.chunk.chunk_id)
        raise RuntimeError("always down")

    units = [Chunk(chunk_id="checkout", assets=(_endpoint("/a"),)),
             Chunk(chunk_id="fulfilment", assets=(_endpoint("/b"),))]
    result = _run(run_service_loop(
        "p1", "r1", units=units,
        proposer_bodies={"mechanism_typist": boom, "data_modeller": boom},
        write_fn=_fake_write_fn({}), attempts=2, observe=False,
    ))
    # every unit was still visited (fail-open), and the loop reached the second
    assert set(visited) == {"checkout", "fulfilment"}
    assert all(o.status == "degraded" for o in result.outcomes)
    assert result.wrote is False


def test_stop_between_units_is_honoured():
    units = [Chunk(chunk_id="a", assets=(_endpoint("/a"),)),
             Chunk(chunk_id="b", assets=(_endpoint("/b"),))]
    log = []
    bodies = {
        "mechanism_typist": _ok_body(log, "mechanism_typist"),
        "data_modeller": _ok_body(log, "data_modeller"),
    }
    checks = {"n": 0}

    def stop_fn():
        checks["n"] += 1
        return checks["n"] > 1                 # run the first unit, then stop

    result = _run(run_service_loop(
        "p1", "r1", units=units, proposer_bodies=bodies,
        write_fn=_fake_write_fn({}), stop_fn=stop_fn, observe=False,
    ))
    assert [c[0] for c in log] == ["a", "a"]
    assert result.stopped is True
    assert result.units == ("a",)


def test_backstop_writes_one_note_per_unit_when_the_bodies_are_real(tmp_path):
    """The deferred T3 wiring: the loop threads the per-project memory store and
    the unit slug into run_workflow, so the per-unit backstop is live."""
    from polymerhus.analysis.memory import AnalysisMemoryStore
    from polymerhus.analysis.reasoning_workflow import AnalysisTurn

    store = AnalysisMemoryStore(root_dir=tmp_path)
    units = [Chunk(chunk_id="checkout", assets=(_endpoint("/a"),)),
             Chunk(chunk_id="fulfilment", assets=(_endpoint("/b"),))]

    def invoke(messages, *, schema=None, system_prompt=None):
        return AnalysisTurn()

    result = _run(run_service_loop(
        "p1", "r1", units=units, memory=store,
        invoke_fns={"mechanism_typist": invoke, "data_modeller": invoke},
        inventory_fn=lambda pid: {"services": ["checkout", "fulfilment"],
                                  "systems": [], "data_items": []},
        aggregations_fn=lambda pid: [],
        observe=False,
    ))
    assert all(store.has_note("p1", u) for u in ("checkout", "fulfilment"))
    assert result.units == ("checkout", "fulfilment")


# --- the typist first-definer compounding rule (ADR D19) ----------------------

def test_first_definer_strips_a_recompounded_description():
    from polymerhus.analysis.analyser_types import SystemProposal
    from polymerhus.analysis.mechanism_typist import type_mechanisms
    from polymerhus.analysis.reasoning_workflow import AnalysisTurn

    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[-1].content
        if "EXTRACT SYSTEMS" in content:
            return AnalysisTurn(systems=[SystemProposal(
                kind="RESTApi", props={"description": "compounded again"})])
        return AnalysisTurn()

    # the System is ALREADY in the live inventory: this Service is not its definer
    inventory = {"services": ["checkout"], "systems": ["RESTApi"],
                 "system_descriptions": {"RESTApi": "first definition"}}
    out = type_mechanisms(
        Chunk(chunk_id="checkout", assets=(_endpoint("/a"),)),
        invoke_fn=invoke, inventory=inventory, first_definer=True,
    )
    assert [s.kind for s in out.systems] == ["RESTApi"]
    assert "description" not in (out.systems[0].props or {})


def test_default_typist_path_keeps_the_description_streamed_unbroken():
    from polymerhus.analysis.analyser_types import SystemProposal
    from polymerhus.analysis.mechanism_typist import type_mechanisms
    from polymerhus.analysis.reasoning_workflow import AnalysisTurn

    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[-1].content
        if "EXTRACT SYSTEMS" in content:
            return AnalysisTurn(systems=[SystemProposal(
                kind="RESTApi", props={"description": "enriched"})])
        return AnalysisTurn()

    inventory = {"services": ["checkout"], "systems": ["RESTApi"],
                 "system_descriptions": {"RESTApi": "first definition"}}
    out = type_mechanisms(
        Chunk(chunk_id="checkout", assets=(_endpoint("/a"),)),
        invoke_fn=invoke, inventory=inventory,
    )
    assert (out.systems[0].props or {}).get("description") == "enriched"
