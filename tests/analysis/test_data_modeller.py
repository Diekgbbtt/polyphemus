"""Unit tier for the DataPlane Analyser (`data_modeller.py`, #48): the six pure
shaping gates + the census, with every collaborator (invoke_fn/inventory_fn/
aggregations_fn) injected - no live Neo4j, no live LLM (`tests/conftest.py`'s
unit-tier guard).

Mirrors `tests/analysis/test_assigner.py` / the mechanism-typist's unit style.
"""
from __future__ import annotations

from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    DataFlowProposal,
    DataItemProposal,
    DataRelationshipProposal,
    L1DeltaBatch,
    ServiceProposal,
    SurfacesAtProposal,
    SystemEdgeProposal,
    SystemProposal,
)
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.data_modeller import (
    DataPlaneOutcome,
    bind_fields_to_observed,
    drop_out_of_inventory_services,
    drop_unknown_relationship_kinds,
    enforce_groundedness,
    make_data_modeller_body,
    model_data,
    narrow_to_data,
    observed_vocabulary,
    owning_services,
    resolve_surface_refs,
    shape_proposal,
    site_index,
)
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta


def _param(name, endpoint_path="/api/x", baseurl="https://a", position="query"):
    return AssetDelta(
        type="Parameter",
        identity={"name": name, "position": position, "endpoint_path": endpoint_path, "baseurl": baseurl},
    )


def _header(name, value="v", baseurl="https://a"):
    return AssetDelta(type="Header", identity={"name": name, "value": value, "baseurl": baseurl})


def _endpoint(path, baseurl="https://a", method="GET"):
    return AssetDelta(type="Endpoint", identity={"path": path, "method": method, "baseurl": baseurl})


def _chunk(assets, observations=()):
    return Chunk(chunk_id="stream:0", source_job="stream", assets=tuple(assets), observations=tuple(observations))


# --- narrow_to_data (C1/D1) -----------------------------------------------------

def test_narrow_strips_non_data_lists():
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
    assert len(shaped.data_items) == 2
    assert len(shaped.surfaces_at) == 2
    assert len(shaped.data_flows) == 2
    assert len(shaped.data_relationships) == 1


# --- drop_unknown_relationship_kinds (C2/D2) ------------------------------------

def test_kind_allowlist_drops_unknown():
    batch = L1DeltaBatch(data_relationships=[
        DataRelationshipProposal(from_item_key="a", to_item_key="b", kind="derived_from"),
        DataRelationshipProposal(from_item_key="a", to_item_key="b", kind="reflected_in"),
        DataRelationshipProposal(from_item_key="a", to_item_key="b", kind="sourced_from"),
    ])
    shaped, dropped = drop_unknown_relationship_kinds(batch)
    assert len(shaped.data_relationships) == 2
    assert dropped == 1


# --- resolve_surface_refs (C3/C4, D3/D4) ----------------------------------------

def test_reference_gate_canonicalises():
    admitted = [_param("ProductId", endpoint_path="/api/x", baseurl="B")]
    sites = site_index(admitted)
    batch = L1DeltaBatch(surfaces_at=[
        SurfacesAtProposal(item_key="k", l0=L0Ref(label="param", identity={"name": "ProductId"})),
    ])
    shaped, dropped = resolve_surface_refs(batch, sites=sites)
    assert dropped == 0
    ref = shaped.surfaces_at[0].l0
    assert ref.label == "Parameter"
    assert ref.identity == {"name": "ProductId", "position": "query", "endpoint_path": "/api/x", "baseurl": "B"}


def test_reference_gate_drops_unresolvable():
    admitted = [_param("a"), _param("b")]
    sites = site_index(admitted)
    batch = L1DeltaBatch(surfaces_at=[
        SurfacesAtProposal(item_key="k1", l0=L0Ref(label="Parameter", identity={"name": "a"})),
        SurfacesAtProposal(item_key="k2", l0=L0Ref(label="Parameter", identity={"name": "b"})),
        SurfacesAtProposal(item_key="k3", l0=L0Ref(label="Parameter", identity={"name": "nowhere"})),
    ])
    shaped, dropped = resolve_surface_refs(batch, sites=sites)
    assert len(shaped.surfaces_at) == 2
    assert dropped == 1


# --- drop_out_of_inventory_services (C5/D5) -------------------------------------

def test_validation_gate_drops_and_backlogs():
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
    assert len(backlog) == 1
    assert "wishlist" in backlog[0]


# --- bind_fields_to_observed (C7/C8/C9) -----------------------------------------

def test_fields_observed_only():
    batch = L1DeltaBatch(data_items=[
        DataItemProposal(item_key="k", props={"fields": ["ProductId", "quantity", "price", "discount"]}),
    ])
    shaped, stats = bind_fields_to_observed(
        batch, observed_names=frozenset({"ProductId", "quantity"}),
    )
    assert shaped.data_items[0].props["fields"] == ["ProductId", "quantity"]
    assert stats["fields_unobserved_dropped"] == 2


def test_fields_compound_never_shrink():
    batch = L1DeltaBatch(data_items=[
        DataItemProposal(item_key="shopping_basket", props={"fields": ["quantity"]}),
    ])
    shaped, stats = bind_fields_to_observed(
        batch, observed_names=frozenset({"quantity"}),
        existing_fields={"shopping_basket": ["ProductId"]},
    )
    assert shaped.data_items[0].props["fields"] == ["ProductId", "quantity"]
    assert stats["fields_carried_forward"] == 1


def test_fields_omitted_when_none_observed():
    batch = L1DeltaBatch(data_items=[DataItemProposal(item_key="k", props={"fields": ["price"]})])
    shaped, stats = bind_fields_to_observed(batch, observed_names=frozenset({"quantity"}))
    assert "fields" not in shaped.data_items[0].props


def test_fields_untouched_when_not_proposed():
    """An item with NO `fields` key in its proposal is passed through unchanged -
    `SET n += map` never touches a key the map does not carry, so persisted
    fields already on the node are safe without a rewrite here."""
    batch = L1DeltaBatch(data_items=[DataItemProposal(item_key="k", props={"notes": "n"})])
    shaped, stats = bind_fields_to_observed(
        batch, observed_names=frozenset(), existing_fields={"k": ["ProductId"]},
    )
    assert shaped.data_items[0].props == {"notes": "n"}
    assert stats["fields_carried_forward"] == 0


# --- enforce_groundedness (C10/C11) ---------------------------------------------

def test_groundedness_requires_surface():
    batch = L1DeltaBatch(
        data_items=[
            DataItemProposal(item_key="grounded"),
            DataItemProposal(item_key="flow_only"),
            DataItemProposal(item_key="neither"),
        ],
        surfaces_at=[SurfacesAtProposal(item_key="grounded", l0=L0Ref(label="Parameter", identity={"name": "n"}))],
        data_flows=[DataFlowProposal(service_slug="s", item_key="flow_only", direction="produces")],
    )
    shaped, dropped_items, dropped_rels = enforce_groundedness(batch)
    assert [i.item_key for i in shaped.data_items] == ["grounded"]
    assert dropped_items == 2


def test_orphan_relationship_dropped():
    batch = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="a")],
        surfaces_at=[SurfacesAtProposal(item_key="a", l0=L0Ref(label="Parameter", identity={"name": "n"}))],
        data_relationships=[DataRelationshipProposal(from_item_key="a", to_item_key="ghost", kind="derived_from")],
    )
    shaped, _, dropped_rels = enforce_groundedness(batch)
    assert shaped.data_relationships == []
    assert dropped_rels == 1


def test_known_item_not_regrounded():
    """An item already in the live inventory is NOT re-tested per chunk (it was
    grounded when it was written) - DPL-DEC-13."""
    batch = L1DeltaBatch(data_items=[DataItemProposal(item_key="known_item")])
    shaped, dropped_items, _ = enforce_groundedness(batch, known_items=frozenset({"known_item"}))
    assert [i.item_key for i in shaped.data_items] == ["known_item"]
    assert dropped_items == 0


# --- shape_proposal ordering (C12/D12) ------------------------------------------

def test_gate_order_load_bearing():
    """The only anchor for a NEW item is a `surfaces_at` the reference gate (3)
    drops - proves gate 6 ran AFTER gate 3 saw the drop, not before."""
    raw = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="ghost_item")],
        surfaces_at=[SurfacesAtProposal(item_key="ghost_item", l0=L0Ref(label="Parameter", identity={"name": "nowhere"}))],
    )
    outcome = shape_proposal(raw, sites=site_index([_param("real")]))
    assert outcome.stats.kept_items == 0
    assert outcome.stats.unresolvable_surfaces == 1
    assert outcome.stats.ungrounded_items_dropped == 1


# --- census / proposed counts ----------------------------------------------------

def test_shape_proposal_census_end_to_end():
    admitted = [_param("ProductId"), _header("X-Cart-Token")]
    raw = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="basket", props={"fields": ["ProductId"]})],
        surfaces_at=[SurfacesAtProposal(item_key="basket", l0=L0Ref(label="Parameter", identity={"name": "ProductId"}))],
        data_flows=[DataFlowProposal(service_slug="cart", item_key="basket", direction="produces")],
    )
    outcome = shape_proposal(
        raw, sites=site_index(admitted), existing_slugs=frozenset({"cart"}),
        observed_names=observed_vocabulary(admitted),
    )
    assert outcome.stats.kept_items == 1
    assert outcome.stats.kept_surfaces == 1
    assert outcome.stats.kept_flows == 1
    assert outcome.stats.new_item_keys == 1
    assert outcome.stats.reused_item_keys == 0


# --- owning_services (candidate owner join, section 6) --------------------------

def test_owning_services_parameter_joins_endpoint_and_baseurl():
    admitted = [_param("ProductId", endpoint_path="/api/basket", baseurl="B")]
    aggregations = [
        {"slug": "cart", "labels": ["Endpoint"], "props": {"path": "/api/basket", "baseurl": "B"}},
        {"slug": "other", "labels": ["Endpoint"], "props": {"path": "/api/other", "baseurl": "B"}},
    ]
    candidates = owning_services(admitted, aggregations)
    ref = list(candidates)[0]
    assert candidates[ref] == ["cart"]


def test_owning_services_header_joins_baseurl_only():
    admitted = [_header("X-Cart-Token", baseurl="B")]
    aggregations = [
        {"slug": "cart", "labels": ["Endpoint"], "props": {"path": "/api/basket", "baseurl": "B"}},
        {"slug": "orders", "labels": ["Endpoint"], "props": {"path": "/api/orders", "baseurl": "B"}},
    ]
    candidates = owning_services(admitted, aggregations)
    ref = list(candidates)[0]
    assert candidates[ref] == ["cart", "orders"]  # coarse: every Service on that origin


# --- make_data_modeller_body / model_data: valid-empty + degradation (C13/C14) --

def test_empty_admission_no_llm_call():
    calls = {"n": 0}

    def invoke_fn(messages, *, schema=None):
        calls["n"] += 1
        return None

    body = make_data_modeller_body(invoke_fn=invoke_fn, inventory_fn=lambda pid: {}, aggregations_fn=lambda pid: [])
    dispatch = type("D", (), {"phase": "A1", "chunk": _chunk([_endpoint("/x")])})()  # no Parameter/Header/Secret admitted
    result = body(dispatch, {"project_id": "p"})
    assert result == L1DeltaBatch()
    assert calls["n"] == 0


def test_phase_guard_returns_none_for_non_a1():
    body = make_data_modeller_body(invoke_fn=lambda *a, **k: None)
    dispatch = type("D", (), {"phase": "A2", "chunk": _chunk([_param("a")])})()
    assert body(dispatch, {"project_id": "p"}) is None


def test_degradation_invoke_raises():
    def invoke_fn(messages, *, schema=None):
        raise RuntimeError("boom")

    body = make_data_modeller_body(invoke_fn=invoke_fn, inventory_fn=lambda pid: {}, aggregations_fn=lambda pid: [])
    dispatch = type("D", (), {"phase": "A1", "chunk": _chunk([_param("a")])})()
    result = body(dispatch, {"project_id": "p"})
    assert result == L1DeltaBatch()


def test_degradation_invoke_none():
    outcome = model_data(_chunk([_param("a")]), invoke_fn=lambda *a, **k: None, inventory={}, aggregations=[])
    assert outcome.batch == L1DeltaBatch()
    assert outcome.stats.reflection_exhausted is True


def test_degradation_inventory_read_raises():
    def boom_inventory(pid):
        raise RuntimeError("neo4j down")

    body = make_data_modeller_body(
        invoke_fn=lambda *a, **k: L1DeltaBatch() if k.get("schema") else "reflected",
        inventory_fn=boom_inventory, aggregations_fn=lambda pid: [],
    )
    dispatch = type("D", (), {"phase": "A1", "chunk": _chunk([_param("a")])})()
    result = body(dispatch, {"project_id": "p"})
    assert isinstance(result, L1DeltaBatch)


def test_degradation_aggregation_read_raises():
    def boom_aggregations(pid):
        raise RuntimeError("neo4j down")

    body = make_data_modeller_body(
        invoke_fn=lambda *a, **k: L1DeltaBatch() if k.get("schema") else "reflected",
        inventory_fn=lambda pid: {}, aggregations_fn=boom_aggregations,
    )
    dispatch = type("D", (), {"phase": "A1", "chunk": _chunk([_param("a")])})()
    result = body(dispatch, {"project_id": "p"})
    assert isinstance(result, L1DeltaBatch)


# --- C17: no Cypher, no provenance on the proposal shapes -----------------------

def test_no_cypher_no_provenance():
    import inspect

    from polymerhus.analysis import data_modeller as dm

    source = inspect.getsource(dm)
    assert "MERGE" not in source
    for cls in (DataItemProposal, SurfacesAtProposal, DataFlowProposal, DataRelationshipProposal):
        assert "provenance" not in cls.model_fields
