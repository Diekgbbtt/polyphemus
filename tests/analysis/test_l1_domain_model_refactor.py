"""Operator-ratified L1 domain-model refactor (2026-07-20):

  * Change 1 - `SystemKind` is a System ATTRIBUTE named `kind` (identity property),
    not a `:SystemKind` catalogue node reached by `OF_KIND`.
  * Change 3 - the missing-systems sweep is redesigned to be stale-L0-asset
    driven: for each stale asset, an injected LLM proposes an owner grounded
    primarily in the existing L1 inventory, secondarily in the known-kinds
    enumeration. Fail-open, propose_fn injectable (mirrors curation.py).

(Change 2 - the DataRelationship kind-as-edge-type correction - was retired with
the data plane; see `docs/design/drop-data-modeller.md`. The `DATA_RELATIONSHIP_KINDS`
catalogue is retained for the hunting read-only projection.)

These are pure-builder / seam unit tests (no live DB / LLM).
"""
import pytest

from polymerhus.analysis import l1_curator, sweep
from polymerhus.analysis.l1_types import (
    L1_SINGLETON,
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
    from polymerhus.analysis.l1_curator import SYSTEM_KINDS
    assert set(sweep.known_system_kind_ids()) == {k for k, _ in SYSTEM_KINDS}
