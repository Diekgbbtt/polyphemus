"""Operator-ratified L1 domain-model refactor (2026-07-20):

  * Change 1 - `SystemKind` is a System ATTRIBUTE named `kind` (identity property),
    not a `:SystemKind` catalogue node reached by `OF_KIND`.
  * Change 2 - a DataRelationship's kind IS the relationship TYPE (a FIXED
    allowlist, uppercased), not a `:DataRelationshipKind` node + generic
    `DATA_RELATIONSHIP` edge. Unknown kinds are HARD-REJECTED (write nothing).
  * Change 3 - the missing-systems sweep is redesigned to be stale-L0-asset
    driven: for each stale asset, an injected LLM proposes an owner grounded
    primarily in the existing L1 inventory, secondarily in the known-kinds
    enumeration. Fail-open, propose_fn injectable (mirrors curation.py).

These are pure-builder / seam unit tests (no live DB / LLM).
"""
import pytest

from agent.recon.analysis import l1_curator, sweep
from agent.recon.analysis.l1_types import (
    L1_SINGLETON,
    DataRelationshipDelta,
    Provenance,
    SystemDelta,
    SystemEdgeDelta,
)


def _prov():
    return Provenance(job="test", model="m", prompt_id="p")


# --- Change 1: System keyed on `kind`; no SystemKind node / OF_KIND edge --------

def test_build_system_cypher_keyed_on_kind_no_catalogue_node():
    cy, params = l1_curator.build_system_cypher(
        SystemDelta(kind="WebPresentation", props={"rendering_model": "CSR"}, provenance=_prov())
    )
    # identity property is `kind` (Change 1), never `system_kind`
    assert "kind: $id_kind" in cy
    assert "system_kind" not in cy
    assert params["id_kind"] == "WebPresentation"
    # discriminator defaults to the non-null __singleton__ sentinel (L1D-9)
    assert params["id_discriminator"] == L1_SINGLETON
    # the catalogue node + OF_KIND edge are GONE
    assert "SystemKind" not in cy
    assert "OF_KIND" not in cy
    # provenance still stamped (L1D-25)
    assert params["prov_job"] == "test" and params["prov_model"] == "m"


def test_build_system_cypher_rejects_unknown_kind():
    with pytest.raises(ValueError):
        l1_curator.build_system_cypher(SystemDelta(kind="NotAKind", provenance=_prov()))


def test_build_system_edge_cypher_keyed_on_kind():
    cy, params = l1_curator.build_system_edge_cypher(
        SystemEdgeDelta(service_slug="checkout", kind="WebPresentation",
                        rel="EXPOSED_VIA", provenance=_prov())
    )
    assert "kind: $kind" in cy
    assert "system_kind" not in cy
    assert params["kind"] == "WebPresentation"


def test_l1_system_schema_keyed_on_kind():
    from db.neo4j import l1_schema
    joined = "\n".join(l1_schema.L1_CONSTRAINTS)
    assert "sy.kind" in joined
    assert "sy.system_kind" not in joined
    # the catalogue-node constraints are removed
    assert "SystemKind" not in joined
    assert "DataRelationshipKind" not in joined


# --- Change 2: DataRelationship kind IS the edge type; fixed allowlist ----------

def test_data_relationship_known_kind_becomes_typed_edge():
    cy, params = l1_curator.build_data_relationship_cypher(
        DataRelationshipDelta(from_item_key="order_total", to_item_key="line_item",
                              kind="derived_from", predicate="total=sum(price*qty)",
                              provenance=_prov())
    )
    # the kind IS the (uppercased) relationship type
    assert "[r:DERIVED_FROM]" in cy
    # the generic edge + catalogue node are GONE
    assert "DATA_RELATIONSHIP" not in cy.replace("DERIVED_FROM", "")  # no generic type
    assert ":DataRelationshipKind" not in cy
    assert "kind: $kind" not in cy  # kind is not an edge property anymore
    assert params["prov_job"] == "test"  # provenance still stamped


def test_data_relationship_rejects_unknown_kind_writes_nothing():
    # the builder hard-rejects an unknown kind (allowlist miss = ValueError)
    with pytest.raises(ValueError):
        l1_curator.build_data_relationship_cypher(
            DataRelationshipDelta(from_item_key="a", to_item_key="b",
                                  kind="frobnicated", provenance=_prov())
        )


def test_enrich_drops_unknown_data_relationship_kind():
    """An unknown kind must be rejected AND written nowhere (fail-open per-delta):
    the merge_fn is never called for the bad delta."""
    calls = []

    def fake_merge(cypher, params):
        calls.append(cypher)

    counts = l1_curator.enrich(
        "proj",
        data_relationships=[
            DataRelationshipDelta(from_item_key="a", to_item_key="b", kind="frobnicated", provenance=_prov()),
            DataRelationshipDelta(from_item_key="a", to_item_key="b", kind="equals_hash_of", provenance=_prov()),
        ],
        merge_fn=fake_merge,
    )
    assert counts["data_relationships"] == 1               # only the known kind written
    assert any("EQUALS_HASH_OF" in c for c in calls)       # typed edge
    assert not any("FROBNICATED" in c.upper() for c in calls)


def test_all_six_allowlisted_kinds_map_to_uppercase_edges():
    for kind, _desc in l1_curator.DATA_RELATIONSHIP_KINDS:
        cy, _ = l1_curator.build_data_relationship_cypher(
            DataRelationshipDelta(from_item_key="a", to_item_key="b", kind=kind, provenance=_prov())
        )
        assert f"[r:{kind.upper()}]" in cy


# --- Change 3: stale-L0-asset-driven ownership resolution (the redesigned sweep) -

def test_resolve_stale_owners_grounds_prompt_in_inventory_then_kinds():
    """The prompt is grounded PRIMARILY in the existing L1 inventory and
    SECONDARILY in the known-kinds enumeration (the constant list)."""
    captured = {}

    def fake_read(query, params):
        if "AGGREGATES" in query and "count(n)" not in query:  # stale_pool
            return [{"props": {"path": "/healthz", "_label": "Endpoint"}}]
        if "L1Service" in query:
            return [{"slug": "checkout"}]
        if "L1System" in query:
            return [{"kind": "WebPresentation", "disc": L1_SINGLETON}]
        if "L1DataItem" in query:
            return [{"item_key": "order"}]
        return []

    def fake_propose(context):
        captured["context"] = context
        return sweep.StaleOwnershipBatch(proposals=[
            sweep.StaleAssetOwnership(asset_ref={"path": "/healthz"}, kind="AuthorizationSystem",
                                      service_slug="checkout", rationale="probe under authz"),
        ])

    batch = sweep.resolve_stale_owners("proj", read_fn=fake_read, propose_fn=fake_propose)
    assert len(batch.proposals) == 1
    assert batch.proposals[0].kind == "AuthorizationSystem"

    ctx = captured["context"]
    assert ctx["inventory"]["services"] == ["checkout"]
    assert ctx["stale_pool"]                         # the stale assets were read
    assert "WebPresentation" in ctx["known_kinds"]   # the constant kinds enumeration

    # prompt construction: inventory appears BEFORE the kinds enumeration (primary/secondary)
    prompt = sweep.stale_ownership_prompt(ctx)
    assert prompt.index("checkout") < prompt.index("WebPresentation")


def test_resolve_stale_owners_fail_open_on_propose_error():
    def fake_read(query, params):
        if "AGGREGATES" in query and "count(n)" not in query:
            return [{"props": {"path": "/x", "_label": "Endpoint"}}]
        return []

    def boom(context):
        raise RuntimeError("llm down")

    batch = sweep.resolve_stale_owners("proj", read_fn=fake_read, propose_fn=boom)
    assert batch.proposals == []  # degrades to an empty batch, never raises


def test_resolve_stale_owners_fail_open_on_read_error():
    def bad_read(query, params):
        raise RuntimeError("db down")

    batch = sweep.resolve_stale_owners("proj", read_fn=bad_read, propose_fn=lambda c: None)
    assert batch.proposals == []


def test_known_kinds_enumeration_is_the_single_source():
    """The kinds enumeration the sweep uses is the SAME constant the curator
    validates against (single source of truth)."""
    from agent.recon.analysis.l1_curator import SYSTEM_KINDS
    assert set(sweep.known_system_kind_ids()) == {k for k, _ in SYSTEM_KINDS}
