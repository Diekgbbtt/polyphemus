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
    _live_services_block,
    _service_unit_block,
    bind_fields_to_observed,
    drop_out_of_inventory_services,
    drop_unknown_relationship_kinds,
    enforce_groundedness,
    make_data_modeller_body,
    model_data,
    narrow_to_data,
    observed_vocabulary,
    resolve_surface_refs,
    shape_proposal,
    site_index,
)
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.reasoning_workflow import AnalysisTurn
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
        aggregates=[AggregatesProposal(service_slug="a", confidence=0.9, l0=L0Ref(label="Endpoint", identity={"path": "/x"}))] * 3,
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


# --- owning_services (candidate-owner join) -------------------------------------
#
# RETIRED (C-m1): the per-asset owner join is dead under the L1-unit-first survey -
# the candidate list is no longer fed to the prompt, and the `candidate_services`
# census counter had no other consumer. The function and its two unit tests are
# removed with it; the live Service inventory (the `services` artifact) is the
# surviving validation surface.

# --- make_data_modeller_body / model_data: valid-empty + degradation (C13/C14) --

def test_model_data_scopes_its_invokes_by_the_chunk_batch():
    """Per-batch memory: the body sets the streamed chunk id as the session batch
    around the WHOLE sub-problem chain (hypotheses -> data_extract -> flow_shape ->
    flow_extract), so the chain shares one context and the next chunk starts fresh."""
    from polymerhus.analysis.proposer_turn import current_batch
    from polymerhus.analysis.reasoning_workflow import AnalysisTurn

    seen: list[str | None] = []

    def invoke_fn(messages, *, schema=None, system_prompt=None):
        seen.append(current_batch())
        return AnalysisTurn()

    model_data(_chunk([_param("a")]), invoke_fn=invoke_fn, inventory={}, aggregations=[])
    assert seen == ["stream:0"] * 8


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


# `test_degradation_invoke_raises` was RETIRED (#73): a raising invoke_fn no longer
# reaches the body in production - the default (invoke_role) converts any provider
# failure to a None return via the escalating wrapper (see
# tests/test_llm_providers.py::test_escalating_invoke_fail_closes_to_none_*). The
# None-degradation path the body must honour is covered by test_degradation_invoke_none.

def test_degradation_invoke_none():
    outcome = model_data(_chunk([_param("a")]), invoke_fn=lambda *a, **k: None, inventory={}, aggregations=[])
    assert outcome.batch == L1DeltaBatch()
    assert outcome.stats.reflection_exhausted is True


def test_degradation_inventory_read_raises():
    def boom_inventory(pid):
        raise RuntimeError("neo4j down")

    body = make_data_modeller_body(
        invoke_fn=lambda *a, **k: AnalysisTurn(),
        inventory_fn=boom_inventory, aggregations_fn=lambda pid: [],
    )
    dispatch = type("D", (), {"phase": "A1", "chunk": _chunk([_param("a")])})()
    result = body(dispatch, {"project_id": "p"})
    assert isinstance(result, L1DeltaBatch)


def test_degradation_aggregation_read_raises():
    def boom_aggregations(pid):
        raise RuntimeError("neo4j down")

    body = make_data_modeller_body(
        invoke_fn=lambda *a, **k: AnalysisTurn(),
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


# --- T3: the L1-unit-first survey, the unit feed, the global validation --------

def test_workflow_injects_the_unit_not_a_prefed_surface():
    """T3: no sub-problem is fed a whole streamed asset list. The old `surface`
    (the admitted-asset render) and `candidates` sources are gone; the survey starts
    from the `service` unit and the model discovers the rest through the tools."""
    from polymerhus.analysis.data_modeller import WORKFLOW

    by_id = {sp.id: sp for sp in WORKFLOW.sub_problems}
    for sp in WORKFLOW.sub_problems:
        assert "surface" not in sp.inject, sp.id
        assert "candidates" not in sp.inject, sp.id
    assert by_id["surface_survey"].inject == ("service", "inventory")
    assert "services" in by_id["record_hypotheses"].inject
    assert "services" in by_id["flow_extract"].inject
    assert "services" in by_id["flow_shape"].inject
    # the unit itself is the anchor every reasoning turn reads.
    assert "service" in by_id["surface_survey"].inject
    assert "service" in by_id["insight_recall"].inject


def test_service_unit_block_carries_contract_and_aggregated_endpoints():
    """T3: the `service` base artifact is the UNIT - slug, `service_contract`, and the
    Endpoints the Service already aggregates - not an admitted-asset list."""
    chunk = Chunk(
        chunk_id="checkout", source_job="service:checkout",
        assets=(_param("ProductId", endpoint_path="/orders", baseurl="B"),),
    )
    aggregations = [{
        "slug": "checkout", "labels": ["Endpoint"],
        "props": {"path": "/orders", "method": "POST", "url": "https://a/orders", "baseurl": "B"},
    }]
    inventory = {"service_contracts": {"checkout": "takes a basket to a paid order"}}
    block = _service_unit_block(chunk, inventory, aggregations)
    assert "SERVICE UNIT: checkout" in block
    assert "takes a basket to a paid order" in block   # the service_contract
    assert "POST /orders" in block                     # the aggregated endpoint
    assert "B" in block


def test_live_services_block_lists_the_full_inventory():
    """T3: the `services` artifact is the FULL live Service inventory, so a flow may
    name ANY live Service as producer/consumer - not only the unit's own slug."""
    block = _live_services_block({
        "services": ["checkout", "catalogue"],
        "service_contracts": {"checkout": "takes a basket to a paid order"},
    })
    assert "checkout" in block
    assert "catalogue" in block
    assert "takes a basket to a paid order" in block


def test_no_prefed_surface_stream_reaches_the_prompt():
    """T3: the admitted Parameter is NOT rendered into the prompt as a list. The model
    discovers it through `graph_view`; only the unit context is fed."""
    captured = {}

    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[-1].content
        if "SURVEY - ORIENT" in content:
            captured["survey"] = content
        return AnalysisTurn()

    model_data(_chunk([_param("SURFACE_MARKER_PARAM")]), invoke_fn=invoke,
               inventory={}, aggregations=[])
    prompt = captured["survey"]
    assert "SERVICE UNIT" in prompt
    assert "SURFACE_MARKER_PARAM" not in prompt   # the pre-fed asset list is gone


def test_a_flow_naming_another_live_service_survives_and_a_ghost_is_dropped():
    """T3: the FULL live inventory is the validation set, so a cross-Service flow
    survives; a slug that names no live Service is still dropped (global gate kept)."""
    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[-1].content
        if "TASK - EXTRACT THE FLOWS" in content:
            return AnalysisTurn(data_flows=[
                DataFlowProposal(service_slug="other-live-service", item_key="basket",
                                 direction="consumes"),
                DataFlowProposal(service_slug="ghost", item_key="basket", direction="produces"),
            ])
        if "TASK - EXTRACT THE DATA ITEMS" in content:
            return AnalysisTurn(
                data_items=[DataItemProposal(item_key="basket")],
                surfaces_at=[SurfacesAtProposal(
                    item_key="basket",
                    l0=L0Ref(label="Parameter", identity={"name": "ProductId"}))],
            )
        return AnalysisTurn()

    inventory = {"services": ["checkout", "other-live-service"]}
    outcome = model_data(_chunk([_param("ProductId")]), invoke_fn=invoke,
                         inventory=inventory, aggregations=[])
    assert [f.service_slug for f in outcome.batch.data_flows] == ["other-live-service"]
    assert outcome.stats.out_of_inventory_flows == 1   # the ghost is still dropped


def test_hypothesise_verify_loop_and_observed_only_fields_still_hold():
    """T3: the staged hypothesise/verify loop survives the rewrite, and an
    unobserved field is still stripped by the observed-only gate."""
    captured = {}

    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[-1].content
        if "HYPOTHESISE" in content and "TASK - EXTRACT THE DATA ITEMS" not in content:
            captured["hypotheses"] = content
        if "TASK - EXTRACT THE DATA ITEMS" in content:
            return AnalysisTurn(
                data_items=[DataItemProposal(
                    item_key="basket", props={"fields": ["ProductId", "price"]})],
                surfaces_at=[SurfacesAtProposal(
                    item_key="basket",
                    l0=L0Ref(label="Parameter", identity={"name": "ProductId"}))],
            )
        return AnalysisTurn()

    outcome = model_data(_chunk([_param("ProductId")]), invoke_fn=invoke,
                         inventory={}, aggregations=[])
    assert "VERIFY / FALSIFY" in captured["hypotheses"]
    assert "no business record" in captured["hypotheses"]
    # `price` was never observed, so it is stripped; `ProductId` survives.
    assert outcome.batch.data_items[0].props["fields"] == ["ProductId"]


# --- C-M1: the reference gate is fed the graph-discovered sites ----------------

def test_graph_discovered_site_grounds_an_item_not_in_the_chunk():
    """C-M1: a site the model discovers through `graph_view` (here injected via the
    `read_sites_fn` live index) can ground an item even when the unit's chunk never
    carried it - the gate is no longer bounded by the pre-fed admitted set. N1:
    discovery is scoped to the unit's own BaseURLs, so the discovered site shares the
    unit chunk's origin (a different name on the same BaseURL)."""
    discovered = _param("graphOnlyField", endpoint_path="/discovered", baseurl="https://a")

    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[-1].content
        if "TASK - EXTRACT THE DATA ITEMS" in content:
            return AnalysisTurn(
                data_items=[DataItemProposal(item_key="discovered_record")],
                surfaces_at=[SurfacesAtProposal(
                    item_key="discovered_record",
                    l0=L0Ref(label="Parameter", identity={"name": "graphOnlyField"}))],
            )
        return AnalysisTurn()

    outcome = model_data(
        _chunk([_param("chunkOnlyField")]), invoke_fn=invoke,
        inventory={}, aggregations=[],
        read_sites_fn=lambda pid: [discovered], project_id="p1",
    )
    assert outcome.stats.kept_surfaces == 1
    assert outcome.stats.kept_items == 1
    assert outcome.batch.surfaces_at[0].l0.identity["name"] == "graphOnlyField"

    # CONTROL: without the live index the graph-discovered site is unresolvable and
    # the item it grounded is dropped - the defect C-M1 fixes.
    control = model_data(_chunk([_param("chunkOnlyField")]), invoke_fn=invoke,
                         inventory={}, aggregations=[])
    assert control.stats.unresolvable_surfaces == 1
    assert control.stats.kept_surfaces == 0


# --- C-M2: a contracted Service with no pre-aggregated surface still discovers --

def test_contracted_empty_service_dispatches_the_modeller():
    """C-M2: no pre-aggregated assets is not a skip when the Service has a
    contract - discovery is the point."""
    calls = {"n": 0}

    def invoke(messages, *, schema=None, system_prompt=None):
        calls["n"] += 1
        return AnalysisTurn()

    chunk = Chunk(chunk_id="empty-svc", source_job="service:empty-svc", assets=())
    model_data(chunk, invoke_fn=invoke,
               inventory={"services": ["empty-svc"],
                          "service_contracts": {"empty-svc": "does x"}})
    assert calls["n"] == 8   # the whole chain ran; discovery found nothing -> empty


def test_serviceless_empty_unit_stays_a_no_call_empty():
    """C-M2: neither contract nor assets is a valid no-op with no LLM call."""
    calls = {"n": 0}

    def invoke(messages, *, schema=None, system_prompt=None):
        calls["n"] += 1
        return AnalysisTurn()

    chunk = Chunk(chunk_id="orphan", source_job="service:orphan", assets=())
    outcome = model_data(chunk, invoke_fn=invoke, inventory={})
    assert calls["n"] == 0
    assert outcome.batch == L1DeltaBatch()


# --- N1: unit-scoped discovery and ambiguity-aware resolution -------------------

def test_site_index_does_not_silently_reanchor_a_colliding_name():
    """N1: a Parameter name colliding across two Services' endpoints must NOT be
    first-wins re-anchored. The model's full identity (name + endpoint_path +
    baseurl) decides; a bare ambiguous name is dropped, never rewritten to B's site
    from A's (the reproduced C-M1 defect)."""
    sites = site_index([
        _param("id", endpoint_path="/serviceA/thing", baseurl="https://a"),
        _param("id", endpoint_path="/serviceB/thing", baseurl="https://b"),
    ])
    full = L1DeltaBatch(surfaces_at=[
        SurfacesAtProposal(item_key="k", l0=L0Ref(label="Parameter", identity={
            "name": "id", "endpoint_path": "/serviceB/thing", "baseurl": "https://b"})),
    ])
    shaped, dropped = resolve_surface_refs(full, sites=sites)
    assert dropped == 0
    assert shaped.surfaces_at[0].l0.identity == {
        "name": "id", "position": "query",
        "endpoint_path": "/serviceB/thing", "baseurl": "https://b"}
    # a bare name that maps to two distinct identities is ambiguous -> dropped.
    bare = L1DeltaBatch(surfaces_at=[
        SurfacesAtProposal(item_key="k", l0=L0Ref(label="Parameter", identity={"name": "id"})),
    ])
    shaped_bare, dropped_bare = resolve_surface_refs(bare, sites=sites)
    assert shaped_bare.surfaces_at == []
    assert dropped_bare == 1


def test_site_index_full_identity_mismatch_is_dropped_not_reanchored():
    """N1: a complete identity naming no known site is a HARD miss - the gate never
    falls back to a bare-name match that would rewrite a differing path/baseurl."""
    sites = site_index([_param("id", endpoint_path="/serviceA/thing", baseurl="https://a")])
    batch = L1DeltaBatch(surfaces_at=[
        SurfacesAtProposal(item_key="k", l0=L0Ref(label="Parameter", identity={
            "name": "id", "endpoint_path": "/serviceB/thing", "baseurl": "https://b"})),
    ])
    shaped, dropped = resolve_surface_refs(batch, sites=sites)
    assert shaped.surfaces_at == []
    assert dropped == 1


def test_graph_discovered_site_outside_the_unit_baseurls_is_not_grounded():
    """N1: discovery is UNIT-SCOPED - a site on a different BaseURL than the unit's
    chunk is out of scope and cannot ground an item, so one Service's `surfaces_at`
    can never resolve to another Service's surface."""
    other = _param("otherServiceField", endpoint_path="/serviceB/thing", baseurl="https://b")

    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[-1].content
        if "TASK - EXTRACT THE DATA ITEMS" in content:
            return AnalysisTurn(
                data_items=[DataItemProposal(item_key="record")],
                surfaces_at=[SurfacesAtProposal(
                    item_key="record",
                    l0=L0Ref(label="Parameter", identity={"name": "otherServiceField"}))],
            )
        return AnalysisTurn()

    outcome = model_data(
        _chunk([_param("unitField", endpoint_path="/serviceA/thing", baseurl="https://a")]),
        invoke_fn=invoke, inventory={}, aggregations=[],
        read_sites_fn=lambda pid: [other], project_id="p1",
    )
    assert outcome.stats.kept_surfaces == 0
    assert outcome.stats.unresolvable_surfaces == 1


# --- C-m6: the canonical modelling-closure note name ---------------------------

def test_modelling_closure_note_name_is_canonical(monkeypatch):
    """C-m6: the canonical key is `<unit>:modelling-closure`; the data-modeller
    (code and both prompt files) must not use the underscore variant."""
    monkeypatch.delenv("ANALYSIS_PROMPT_VARIANT", raising=False)
    from polymerhus.analysis import data_modeller as dm

    batched = dm._load_skill()
    assert 'note_name="modelling-closure"' in batched
    assert "modelling_closure" not in batched
    closure = next(sp for sp in dm.WORKFLOW.sub_problems if sp.id == "closure_note")
    assert 'note_name="modelling-closure"' in closure.prompt
    assert "modelling_closure" not in closure.prompt
