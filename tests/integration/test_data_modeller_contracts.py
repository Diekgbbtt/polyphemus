"""Contract predicates (integration tier) for the DataPlane Analyser
(`data_modeller`, agent spec #10/#48), per `docs/design/dataplane-assertions.md`.

Mechanises C1-C17. C1-C5, C7-C14, C17 are injected (no live LLM/graph, mirroring
`test_mechanism_typist_contracts.py`); C6/C15 genuinely need a live Neo4j (the
no-mint / idempotent-replay predicates are about what the sole-writer actually
does), so they follow `test_analyser_pod_merge.py`'s truthful skip-gate pattern
rather than an @pytest.mark that merely claims to need one.
"""
from __future__ import annotations

import subprocess

import pytest

from polymerhus.analysis.analyser_types import (
    DataFlowProposal,
    DataItemProposal,
    DataRelationshipProposal,
    L1DeltaBatch,
    SurfacesAtProposal,
)
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.data_modeller import (
    bind_fields_to_observed,
    drop_out_of_inventory_services,
    drop_unknown_relationship_kinds,
    enforce_groundedness,
    make_data_modeller_body,
    resolve_surface_refs,
    shape_proposal,
    site_index,
)
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta
from tests.conftest import wait_for


def _param(name, endpoint_path="/api/x", baseurl="B", position="query"):
    return AssetDelta(
        type="Parameter",
        identity={"name": name, "position": position, "endpoint_path": endpoint_path, "baseurl": baseurl},
    )


def _chunk(assets):
    return Chunk(chunk_id="stream:0", source_job="stream", assets=tuple(assets))


class _Dispatch:
    def __init__(self, phase, chunk):
        self.phase = phase
        self.chunk = chunk


# --- C1 - narrow ----------------------------------------------------------------

def test_D1_narrow_strips_non_data_lists():
    from polymerhus.analysis.analyser_types import (
        AggregatesProposal, ServiceProposal, SystemEdgeProposal, SystemProposal,
    )
    from polymerhus.analysis.data_modeller import narrow_to_data

    raw = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="a")] * 2,
        aggregates=[AggregatesProposal(service_slug="a", l0=L0Ref(label="Endpoint", identity={"path": "/x"}))] * 3,
        systems=[SystemProposal(kind="CDN")],
        system_edges=[SystemEdgeProposal(service_slug="a", kind="CDN", rel="FRONTED_BY")],
        data_items=[DataItemProposal(item_key="a"), DataItemProposal(item_key="b")],
        surfaces_at=[SurfacesAtProposal(item_key="a", l0=L0Ref(label="Parameter", identity={"name": "n"}))] * 2,
        data_flows=[DataFlowProposal(service_slug="a", item_key="a", direction="produces")] * 2,
        data_relationships=[DataRelationshipProposal(from_item_key="a", to_item_key="b", kind="derived_from")],
    )
    shaped = narrow_to_data(raw)
    assert shaped.services == shaped.systems == shaped.aggregates == shaped.system_edges == []
    assert len(shaped.data_items) == 2 and len(shaped.surfaces_at) == 2
    assert len(shaped.data_flows) == 2 and len(shaped.data_relationships) == 1


# --- C2 - kind allowlist ----------------------------------------------------------

def test_D2_kind_allowlist_drops_unknown():
    batch = L1DeltaBatch(data_relationships=[
        DataRelationshipProposal(from_item_key="a", to_item_key="b", kind="derived_from"),
        DataRelationshipProposal(from_item_key="a", to_item_key="b", kind="reflected_in"),
        DataRelationshipProposal(from_item_key="a", to_item_key="b", kind="sourced_from"),
    ])
    shaped, dropped = drop_unknown_relationship_kinds(batch)
    assert len(shaped.data_relationships) == 2
    assert dropped == 1


# --- C3/C4 - reference gate ------------------------------------------------------

def test_D3_reference_gate_canonicalises():
    sites = site_index([_param("ProductId", endpoint_path="/api/x", baseurl="B")])
    batch = L1DeltaBatch(surfaces_at=[
        SurfacesAtProposal(item_key="k", l0=L0Ref(label="param", identity={"name": "ProductId"})),
    ])
    shaped, dropped = resolve_surface_refs(batch, sites=sites)
    assert dropped == 0
    ref = shaped.surfaces_at[0].l0
    assert ref.label == "Parameter"
    assert ref.identity == {"name": "ProductId", "position": "query", "endpoint_path": "/api/x", "baseurl": "B"}


def test_D4_reference_gate_drops_unresolvable():
    sites = site_index([_param("a"), _param("b")])
    batch = L1DeltaBatch(surfaces_at=[
        SurfacesAtProposal(item_key="k1", l0=L0Ref(label="Parameter", identity={"name": "a"})),
        SurfacesAtProposal(item_key="k2", l0=L0Ref(label="Parameter", identity={"name": "b"})),
        SurfacesAtProposal(item_key="k3", l0=L0Ref(label="Parameter", identity={"name": "nowhere"})),
    ])
    shaped, dropped = resolve_surface_refs(batch, sites=sites)
    assert len(shaped.surfaces_at) == 2
    assert dropped == 1


# --- C5 - validation gate ---------------------------------------------------------

def test_D5_validation_gate_drops_and_backlogs():
    batch = L1DeltaBatch(data_flows=[
        DataFlowProposal(service_slug="cart", item_key="k", direction="produces"),
        DataFlowProposal(service_slug="catalogue", item_key="k", direction="consumes"),
        DataFlowProposal(service_slug="wishlist", item_key="k", direction="produces"),
    ])
    shaped, backlog, dropped = drop_out_of_inventory_services(
        batch, existing_slugs=frozenset({"cart", "catalogue"}),
    )
    assert len(shaped.data_flows) == 2
    assert dropped == 1
    assert len(backlog) == 1 and "wishlist" in backlog[0]


# --- C6 - no Service is minted by the data path (LIVE Neo4j) ---------------------

@pytest.fixture(scope="module")
def _neo4j_session():
    from neo4j import GraphDatabase
    from db.neo4j.init_schema import init_schema
    from db.neo4j.l1_schema import init_l1_schema
    from tests.conftest import neo4j_target

    uri, auth = neo4j_target()

    def _driver():
        d = GraphDatabase.driver(uri, auth=auth)
        d.verify_connectivity()
        return d

    try:
        subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=False)
    except Exception:
        pass
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:
        pytest.skip(f"neo4j not reachable for data_modeller integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


def test_D6_no_service_minted(_neo4j_session):
    import uuid

    from polymerhus.analysis import l1_curator
    from polymerhus.analysis.analyser_types import enrichment_proposals_to_deltas
    from polymerhus.analysis.l1_types import Provenance

    project_id = f"dm-c6-{uuid.uuid4().hex[:8]}"
    provenance = Provenance(job="test:c6", model="test", prompt_id=None)

    raw = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="basket")],
        surfaces_at=[SurfacesAtProposal(item_key="basket", l0=L0Ref(label="Parameter", identity={"name": "ProductId"}))],
        data_flows=[
            DataFlowProposal(service_slug="phantom-one", item_key="basket", direction="produces"),
            DataFlowProposal(service_slug="phantom-two", item_key="basket", direction="consumes"),
        ],
    )
    admitted = [_param("ProductId", endpoint_path="/api/basket", baseurl="B")]
    outcome = shape_proposal(
        raw, sites=site_index(admitted), existing_slugs=frozenset(),  # no live Services at all
    )
    assert outcome.stats.out_of_inventory_flows == 2

    def merge_fn(cypher, params):
        params = dict(params)
        params["project_id"] = project_id
        _neo4j_session.run(cypher, params)

    before = _neo4j_session.run(
        "MATCH (n:L1Service) WHERE n.project_id = $p RETURN count(n) AS c", p=project_id,
    ).single()["c"]
    deltas = enrichment_proposals_to_deltas(outcome.batch, provenance)
    l1_curator.enrich(project_id, merge_fn=merge_fn, **deltas)
    after = _neo4j_session.run(
        "MATCH (n:L1Service) WHERE n.project_id = $p RETURN count(n) AS c", p=project_id,
    ).single()["c"]
    assert before == after == 0


# --- C7/C8/C9 - observed-only fields ----------------------------------------------

def test_D7_fields_observed_only():
    batch = L1DeltaBatch(data_items=[
        DataItemProposal(item_key="k", props={"fields": ["ProductId", "quantity", "price", "discount"]}),
    ])
    shaped, stats = bind_fields_to_observed(batch, observed_names=frozenset({"ProductId", "quantity"}))
    assert shaped.data_items[0].props["fields"] == ["ProductId", "quantity"]
    assert stats["fields_unobserved_dropped"] == 2


def test_D8_fields_compound_never_shrink():
    batch = L1DeltaBatch(data_items=[DataItemProposal(item_key="shopping_basket", props={"fields": ["quantity"]})])
    shaped, stats = bind_fields_to_observed(
        batch, observed_names=frozenset({"quantity"}), existing_fields={"shopping_basket": ["ProductId"]},
    )
    assert shaped.data_items[0].props["fields"] == ["ProductId", "quantity"]
    assert stats["fields_carried_forward"] == 1


def test_D9_fields_omitted_when_none_observed():
    batch = L1DeltaBatch(data_items=[DataItemProposal(item_key="k", props={"fields": ["price"]})])
    shaped, _ = bind_fields_to_observed(batch, observed_names=frozenset({"quantity"}))
    assert "fields" not in shaped.data_items[0].props


# --- C10/C11 - groundedness --------------------------------------------------------

def test_D10_groundedness_requires_surface():
    batch = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="grounded"), DataItemProposal(item_key="flow_only"),
                   DataItemProposal(item_key="neither")],
        surfaces_at=[SurfacesAtProposal(item_key="grounded", l0=L0Ref(label="Parameter", identity={"name": "n"}))],
        data_flows=[DataFlowProposal(service_slug="s", item_key="flow_only", direction="produces")],
    )
    shaped, dropped_items, _ = enforce_groundedness(batch)
    assert [i.item_key for i in shaped.data_items] == ["grounded"]
    assert dropped_items == 2


def test_D11_orphan_relationship_dropped():
    batch = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="a")],
        surfaces_at=[SurfacesAtProposal(item_key="a", l0=L0Ref(label="Parameter", identity={"name": "n"}))],
        data_relationships=[DataRelationshipProposal(from_item_key="a", to_item_key="ghost", kind="derived_from")],
    )
    shaped, _, dropped_rels = enforce_groundedness(batch)
    assert shaped.data_relationships == []
    assert dropped_rels == 1


# --- C12 - gate order load-bearing --------------------------------------------------

def test_D12_gate_order_load_bearing():
    raw = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="ghost_item")],
        surfaces_at=[SurfacesAtProposal(item_key="ghost_item", l0=L0Ref(label="Parameter", identity={"name": "nowhere"}))],
    )
    outcome = shape_proposal(raw, sites=site_index([_param("real")]))
    assert outcome.stats.kept_items == 0
    assert outcome.stats.unresolvable_surfaces == 1
    assert outcome.stats.ungrounded_items_dropped == 1


# --- C13 - empty but valid ----------------------------------------------------------

def test_D13_empty_admission_no_llm_call():
    calls = {"n": 0}

    def invoke_fn(messages, *, schema=None):
        calls["n"] += 1
        return None

    body = make_data_modeller_body(invoke_fn=invoke_fn, inventory_fn=lambda pid: {}, aggregations_fn=lambda pid: [])
    # a chunk with only an Endpoint admits 0 Parameters/Headers/Secrets
    from polymerhus.recon.domain.types import AssetDelta as AD
    chunk = _chunk([AD(type="Endpoint", identity={"path": "/x", "method": "GET", "baseurl": "B"})])
    result = body(_Dispatch("A1", chunk), {"project_id": "p"})
    assert result == L1DeltaBatch()
    assert calls["n"] == 0


# --- C14 - degradation ---------------------------------------------------------------

def test_D14_degradation_invoke_raises():
    def invoke_fn(messages, *, schema=None):
        raise RuntimeError("boom")

    body = make_data_modeller_body(invoke_fn=invoke_fn, inventory_fn=lambda pid: {}, aggregations_fn=lambda pid: [])
    result = body(_Dispatch("A1", _chunk([_param("a")])), {"project_id": "p"})
    assert result == L1DeltaBatch()


def test_D14_degradation_invoke_none():
    from polymerhus.analysis.data_modeller import model_data

    outcome = model_data(_chunk([_param("a")]), invoke_fn=lambda *a, **k: None, inventory={}, aggregations=[])
    assert outcome.batch == L1DeltaBatch()
    assert outcome.stats.reflection_exhausted is True


def test_D14_degradation_inventory_read_raises():
    def boom(pid):
        raise RuntimeError("neo4j down")

    body = make_data_modeller_body(
        invoke_fn=lambda *a, **k: (L1DeltaBatch() if k.get("schema") else "reflected"),
        inventory_fn=boom, aggregations_fn=lambda pid: [],
    )
    result = body(_Dispatch("A1", _chunk([_param("a")])), {"project_id": "p"})
    assert isinstance(result, L1DeltaBatch)


def test_D14_degradation_aggregation_read_raises():
    def boom(pid):
        raise RuntimeError("neo4j down")

    body = make_data_modeller_body(
        invoke_fn=lambda *a, **k: (L1DeltaBatch() if k.get("schema") else "reflected"),
        inventory_fn=lambda pid: {}, aggregations_fn=boom,
    )
    result = body(_Dispatch("A1", _chunk([_param("a")])), {"project_id": "p"})
    assert isinstance(result, L1DeltaBatch)


# --- C15 - idempotent replay (LIVE Neo4j) --------------------------------------------

def test_D15_idempotent_replay(_neo4j_session):
    import uuid

    from polymerhus.analysis import l1_curator
    from polymerhus.analysis.analyser_types import enrichment_proposals_to_deltas
    from polymerhus.analysis.l1_types import Provenance

    project_id = f"dm-c15-{uuid.uuid4().hex[:8]}"
    provenance = Provenance(job="test:c15", model="test", prompt_id=None)
    _neo4j_session.run(
        "MERGE (:L1TestableUnit:L1Service {business_function_slug: 'cart', project_id: $p})",
        p=project_id,
    )

    raw = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="basket")],
        surfaces_at=[SurfacesAtProposal(item_key="basket", l0=L0Ref(label="Parameter", identity={"name": "ProductId"}))],
        data_flows=[DataFlowProposal(service_slug="cart", item_key="basket", direction="produces")],
    )
    admitted = [_param("ProductId", endpoint_path="/api/basket", baseurl="B")]
    outcome1 = shape_proposal(raw, sites=site_index(admitted), existing_slugs=frozenset({"cart"}))
    outcome2 = shape_proposal(raw, sites=site_index(admitted), existing_slugs=frozenset({"cart"}))
    assert outcome1.batch == outcome2.batch  # byte-identical shaped batch

    def merge_fn(cypher, params):
        params = dict(params)
        params["project_id"] = project_id
        _neo4j_session.run(cypher, params)

    deltas = enrichment_proposals_to_deltas(outcome1.batch, provenance)
    l1_curator.enrich(project_id, merge_fn=merge_fn, **deltas)
    counts_1 = {
        "items": _neo4j_session.run("MATCH (n:L1DataItem) WHERE n.project_id=$p RETURN count(n) AS c", p=project_id).single()["c"],
        "surfaces": _neo4j_session.run("MATCH (:L1DataItem)-[r:SURFACES_AT]->() WHERE r.prov_job='test:c15' RETURN count(r) AS c").single()["c"],
        "produces": _neo4j_session.run("MATCH (:L1Service)-[r:PRODUCES]->(:L1DataItem) WHERE r.prov_job='test:c15' RETURN count(r) AS c").single()["c"],
    }
    l1_curator.enrich(project_id, merge_fn=merge_fn, **deltas)
    counts_2 = {
        "items": _neo4j_session.run("MATCH (n:L1DataItem) WHERE n.project_id=$p RETURN count(n) AS c", p=project_id).single()["c"],
        "surfaces": _neo4j_session.run("MATCH (:L1DataItem)-[r:SURFACES_AT]->() WHERE r.prov_job='test:c15' RETURN count(r) AS c").single()["c"],
        "produces": _neo4j_session.run("MATCH (:L1Service)-[r:PRODUCES]->(:L1DataItem) WHERE r.prov_job='test:c15' RETURN count(r) AS c").single()["c"],
    }
    assert counts_1 == counts_2


# --- C16 - the write path carries data (fixes the DPL-DEC-21 silent drop) --------

def test_D16_write_routing_carries_data_only_batch():
    from polymerhus.analysis.l1_types import Provenance
    from polymerhus.analysis.supervisor import _aggregates_write_fn, _chunked_write_fn

    data_only_batch = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="basket")],
        surfaces_at=[SurfacesAtProposal(item_key="basket", l0=L0Ref(label="Parameter", identity={"name": "n"}))],
    )
    provenance = Provenance(job="test:c16", model="test", prompt_id=None)

    # documents the defect this predicate guards against: routed through the OLD
    # aggregates-only writer, a data-only batch produces zero enrichment
    old_export = _aggregates_write_fn(data_only_batch, "p1", provenance)
    assert old_export.enrichment in (None, {})

    calls = {}

    def fake_curate_with_enrichment(deltas, pid, prov):
        calls["deltas"] = deltas
        from polymerhus.analysis.pod import AnalyserExport
        return AnalyserExport(enrichment={"data_items": 1, "surfaces_at": 1})

    import polymerhus.analysis.pod as pod_module
    original = pod_module.default_curate_with_enrichment_fn
    pod_module.default_curate_with_enrichment_fn = fake_curate_with_enrichment
    try:
        export = _chunked_write_fn(data_only_batch, "p1", provenance)
    finally:
        pod_module.default_curate_with_enrichment_fn = original

    assert calls["deltas"] is data_only_batch
    assert sum(export.enrichment.values()) > 0


# --- C17 - no Cypher, no provenance ---------------------------------------------------

def test_D17_no_cypher_no_provenance():
    import inspect

    from polymerhus.analysis import data_modeller as dm

    source = inspect.getsource(dm)
    assert "MERGE" not in source
    for cls in (DataItemProposal, SurfacesAtProposal, DataFlowProposal, DataRelationshipProposal):
        assert "provenance" not in cls.model_fields
