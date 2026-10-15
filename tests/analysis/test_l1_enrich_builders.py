"""FR-ENRICH unit tier — the surviving enrichment PURE builders (no driver) + the
proposal->delta mapping. The DataItem / SURFACES_AT / data-flow / data-relationship
writers were removed with the data plane (`docs/design/drop-data-modeller.md`);
the Service->System edge writer survives. Store-level behaviour is the integration
tier (tests/integration/test_l1_enrich_merge.py).
"""
import pytest

from polymerhus.analysis import l1_curator
from polymerhus.analysis.analyser_types import (
    L1DeltaBatch,
    SystemEdgeProposal,
    enrichment_proposals_to_deltas,
)
from polymerhus.analysis.l1_types import (
    Provenance,
    SystemEdgeDelta,
)

PROV = Provenance(job="analyser:run-1", model="m", prompt_id="p")


# --- System edges: §6 taxonomy label validated, role/realm/order on props ---

def test_system_edge_typed_label_and_role():
    cy, params = l1_curator.build_system_edge_cypher(
        SystemEdgeDelta(service_slug="sales-analysis", kind="AuthorizationSystem",
                        rel="AUTHORIZED_BY", role="seller", provenance=PROV)
    )
    # role is part of the edge IDENTITY (in the MERGE key) so multiple roles coexist
    assert "MERGE (s)-[r:AUTHORIZED_BY {role: $role}]->(sy)" in cy
    assert "SET r.role = $role" in cy
    assert params["role"] == "seller"


def test_system_edge_role_realm_in_merge_key_so_multiple_coexist():
    """Regression (FR-NFR §15 walkthrough): a rel-ONLY MERGE collapsed multiple
    AUTHORIZED_BY {role} edges between one Service and the AuthorizationSystem into
    one (last role wins). role/realm must be in the MERGE key so distinct roles/
    realms are distinct edges."""
    cy_role, _ = l1_curator.build_system_edge_cypher(
        SystemEdgeDelta(service_slug="s", kind="AuthenticationMechanism",
                        rel="AUTHENTICATED_BY", realm="idp", provenance=PROV))
    assert "MERGE (s)-[r:AUTHENTICATED_BY {realm: $realm}]->(sy)" in cy_role
    # an edge with BOTH role and realm keys on both
    cy_both, _ = l1_curator.build_system_edge_cypher(
        SystemEdgeDelta(service_slug="s", kind="AuthorizationSystem",
                        rel="AUTHORIZED_BY", role="seller", realm="credential", provenance=PROV))
    assert "role: $role" in cy_both and "realm: $realm" in cy_both


def test_system_edge_no_role_realm_keeps_rel_only_merge():
    """A plain system edge (no role/realm, e.g. EXPOSED_VIA) keeps the rel-only
    MERGE - one such edge per (service, system) is correct and stays idempotent."""
    cy, _ = l1_curator.build_system_edge_cypher(
        SystemEdgeDelta(service_slug="s", kind="RESTApi", rel="EXPOSED_VIA", provenance=PROV))
    assert "MERGE (s)-[r:EXPOSED_VIA]->(sy)" in cy
    assert "{role:" not in cy and "{realm:" not in cy


def test_secondary_writers_stamp_node_provenance_on_create_only():
    """Regression (FR-NFR §15 walkthrough): the secondary writers MERGE-CREATE L1
    nodes as a side effect; each must stamp provenance ON CREATE (so a side-effect-
    minted node is never provenance-less) but NOT unconditionally (so a node its
    primary writer already made keeps its own provenance). Locks the ON CREATE
    clause against a regression to unconditional SET."""
    se, _ = l1_curator.build_system_edge_cypher(
        SystemEdgeDelta(service_slug="s", kind="RESTApi", rel="EXPOSED_VIA", provenance=PROV))
    assert "ON CREATE SET s.prov_job = $prov_job" in se
    assert "ON CREATE SET sy.prov_job = $prov_job" in se


def test_system_edge_unknown_rel_raises():
    with pytest.raises(ValueError):
        l1_curator.build_system_edge_cypher(
            SystemEdgeDelta(service_slug="s", kind="RESTApi", rel="TELEPORTS_VIA", provenance=PROV)
        )


def test_system_edge_unknown_kind_raises():
    with pytest.raises(ValueError):
        l1_curator.build_system_edge_cypher(
            SystemEdgeDelta(service_slug="s", kind="NotAKind", rel="EXPOSED_VIA", provenance=PROV)
        )


def test_relationship_allowlist_is_the_six_fixed_kinds():
    """The DataRelationship kind catalogue is RETAINED after the data plane was
    removed: the hunting read-only projection imports it to validate the
    relationship edge types it reads. Pinned so an accidental delete is caught."""
    ids = {k for k, _d in l1_curator.DATA_RELATIONSHIP_KINDS}
    assert ids == {"derived_from", "reflected_in", "equals_hash_of",
                   "copy_of", "concatenation_of", "subset_of"}  # FIXED allowlist


# --- proposal -> delta mapping injects system provenance (LLM can't set it) ---

def test_enrichment_mapping_injects_provenance():
    batch = L1DeltaBatch(
        system_edges=[SystemEdgeProposal(service_slug="s", kind="RESTApi", rel="EXPOSED_VIA")],
    )
    deltas = enrichment_proposals_to_deltas(batch, PROV)
    assert set(deltas) == {"system_edges"}
    assert deltas["system_edges"][0].provenance is PROV


def test_enrichment_proposals_have_no_provenance_field():
    assert "provenance" not in SystemEdgeProposal.model_fields
