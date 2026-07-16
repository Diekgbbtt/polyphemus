"""FR-ENRICH unit tier — the enrichment PURE builders (no driver) + the
proposal->delta mapping. Store-level behaviour is the integration tier
(tests/integration/test_l1_enrich_merge.py).
"""
import pytest

from agent.recon.analysis import l1_curator
from agent.recon.analysis.analyser_types import (
    DataFlowProposal,
    DataItemProposal,
    DataRelationshipProposal,
    L1DeltaBatch,
    SurfacesAtProposal,
    SystemEdgeProposal,
    enrichment_proposals_to_deltas,
)
from agent.recon.analysis.l1_types import (
    DataFlowDelta,
    DataItemDelta,
    DataRelationshipDelta,
    L0Ref,
    Provenance,
    SurfacesAtDelta,
    SystemEdgeDelta,
)

PROV = Provenance(job="analyser:run-1", model="m", prompt_id="p")


# --- DataItem: flexible semantic-key identity, identity ⊥ membership ---

def test_dataitem_keyed_on_semantic_item_key_only():
    cy, params = l1_curator.build_dataitem_cypher(
        DataItemDelta(item_key="sales_figure", props={"type": "float"}, provenance=PROV)
    )
    assert "MERGE (d:L1DataItem {item_key: $item_key, project_id: $project_id})" in cy
    assert params["item_key"] == "sales_figure"
    assert params["props"] == {"type": "float"}
    assert params["prov_job"] == "analyser:run-1"


def test_dataitem_empty_key_raises():
    with pytest.raises(ValueError):
        l1_curator.build_dataitem_cypher(DataItemDelta(item_key="  ", provenance=PROV))


# --- SURFACES_AT: native cross-layer edge, L0 MATCHed never created ---

def test_surfaces_at_matches_l0_never_creates():
    cy, params = l1_curator.build_surfaces_at_cypher(
        SurfacesAtDelta(item_key="sales_figure",
                        l0=L0Ref(label="Parameter", identity={"name": "figure", "position": "query"}),
                        provenance=PROV)
    )
    assert "MATCH (l0:Parameter {" in cy
    assert "MERGE (d:L1DataItem {item_key: $item_key, project_id: $project_id})" in cy
    assert "MERGE (d)-[r:SURFACES_AT]->(l0)" in cy
    assert "MERGE (l0" not in cy  # L0 target only ever MATCHed
    assert params["l0_name"] == "figure" and params["l0_position"] == "query"


def test_surfaces_at_unsafe_l0_label_raises():
    with pytest.raises(ValueError):
        l1_curator.build_surfaces_at_cypher(
            SurfacesAtDelta(item_key="x", l0=L0Ref(label="P) DETACH DELETE n //", identity={"name": "q"}), provenance=PROV)
        )


# --- PRODUCES / CONSUMES: assumption predicate rides on CONSUMES only ---

def test_produces_has_no_assumption():
    cy, _ = l1_curator.build_data_flow_cypher(
        DataFlowDelta(service_slug="item-creation", item_key="sales_figure", direction="produces", provenance=PROV)
    )
    assert "MERGE (s)-[r:PRODUCES]->(d)" in cy
    assert "assumption" not in cy


def test_consumes_carries_assumption():
    cy, params = l1_curator.build_data_flow_cypher(
        DataFlowDelta(service_slug="sales-analysis", item_key="sales_figure", direction="consumes",
                      assumption="figure authorized for THIS user", assumption_rationale="cross-service financial read",
                      provenance=PROV)
    )
    assert "MERGE (s)-[r:CONSUMES]->(d)" in cy
    assert "SET r.assumption = $assumption" in cy
    assert params["assumption"] == "figure authorized for THIS user"


def test_bad_direction_raises():
    with pytest.raises(ValueError):
        l1_curator.build_data_flow_cypher(
            DataFlowDelta(service_slug="s", item_key="i", direction="mutates", provenance=PROV)  # type: ignore
        )


# --- DataRelationship: extensible vocabulary, kind validated, predicate carried ---

def test_data_relationship_known_kind_and_predicate():
    cy, params = l1_curator.build_data_relationship_cypher(
        DataRelationshipDelta(from_item_key="client_id", to_item_key="email", kind="equals_hash_of",
                              predicate="client_id = md5(email+id)", rationale="derivation", provenance=PROV)
    )
    assert "MERGE (a)-[r:DATA_RELATIONSHIP {kind: $kind}]->(b)" in cy
    assert "MERGE (k:DataRelationshipKind {id: $kind, project_id: $project_id})" in cy  # catalogue row ensured
    assert params["kind"] == "equals_hash_of"
    assert params["predicate"] == "client_id = md5(email+id)"


def test_data_relationship_unknown_kind_raises():
    with pytest.raises(ValueError):
        l1_curator.build_data_relationship_cypher(
            DataRelationshipDelta(from_item_key="a", to_item_key="b", kind="teleports_to", provenance=PROV)
        )


def test_relationship_vocabulary_is_extensible_catalogue():
    ids = {k for k, _d in l1_curator.DATA_RELATIONSHIP_KINDS}
    assert {"derived_from", "reflected_in", "equals_hash_of"} <= ids  # seeded, extensible by adding rows


# --- System edges: §6 taxonomy label validated, role/realm/order on props ---

def test_system_edge_typed_label_and_role():
    cy, params = l1_curator.build_system_edge_cypher(
        SystemEdgeDelta(service_slug="sales-analysis", system_kind="AuthorizationSystem",
                        rel="AUTHORIZED_BY", role="seller", provenance=PROV)
    )
    assert "MERGE (s)-[r:AUTHORIZED_BY]->(sy)" in cy
    assert "SET r.role = $role" in cy
    assert params["role"] == "seller"


def test_system_edge_unknown_rel_raises():
    with pytest.raises(ValueError):
        l1_curator.build_system_edge_cypher(
            SystemEdgeDelta(service_slug="s", system_kind="RESTApi", rel="TELEPORTS_VIA", provenance=PROV)
        )


def test_system_edge_unknown_kind_raises():
    with pytest.raises(ValueError):
        l1_curator.build_system_edge_cypher(
            SystemEdgeDelta(service_slug="s", system_kind="NotAKind", rel="EXPOSED_VIA", provenance=PROV)
        )


# --- proposal -> delta mapping injects system provenance (LLM can't set it) ---

def test_enrichment_mapping_injects_provenance():
    batch = L1DeltaBatch(
        data_items=[DataItemProposal(item_key="sales_figure")],
        surfaces_at=[SurfacesAtProposal(item_key="sales_figure", l0=L0Ref(label="Parameter", identity={"name": "f"}))],
        data_flows=[DataFlowProposal(service_slug="sales-analysis", item_key="sales_figure", direction="consumes")],
        data_relationships=[DataRelationshipProposal(from_item_key="a", to_item_key="b", kind="derived_from")],
        system_edges=[SystemEdgeProposal(service_slug="s", system_kind="RESTApi", rel="EXPOSED_VIA")],
    )
    deltas = enrichment_proposals_to_deltas(batch, PROV)
    assert set(deltas) == {"data_items", "surfaces_at", "data_flows", "data_relationships", "system_edges"}
    assert isinstance(deltas["data_items"][0], DataItemDelta)
    assert deltas["data_items"][0].provenance is PROV
    assert deltas["surfaces_at"][0].provenance is PROV
    assert deltas["data_flows"][0].provenance is PROV
    assert deltas["data_relationships"][0].provenance is PROV
    assert deltas["system_edges"][0].provenance is PROV


def test_enrichment_proposals_have_no_provenance_field():
    for model in (DataItemProposal, SurfacesAtProposal, DataFlowProposal, DataRelationshipProposal, SystemEdgeProposal):
        assert "provenance" not in model.model_fields
