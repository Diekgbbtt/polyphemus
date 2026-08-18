"""FR-MERGE unit tier - the L1 sole-writer's destructive reconciliation PURE
builders + the impure `reconcile` batcher's fail-open / no-L0-write discipline
(no driver, no live Neo4j). The store-level assertions (real re-point, idempotent
replay, relabel shape) are the integration tier
(tests/integration/test_l1_curator_reconcile.py).

Each test names the FR-MERGE assertion it encodes
(docs/design/post-recon-curation-and-l1-remediation-plan.md §3).
"""
import re

import pytest

from polymerhus.analysis import l1_curator
from polymerhus.analysis.l1_types import (
    DeleteOp,
    MergeOp,
    Provenance,
    RelabelOp,
)

PROV = Provenance(job="curation", model="m", prompt_id="p")

# The rel types the merge builder MUST re-point (task allowlist): the §6 System
# taxonomy plus the cross-layer / data-flow edges plus the SIX typed data-
# relationship edges (the kind IS the edge type; operator correction 2026-07-20).
_REQUIRED_REPOINT_RELS = (
    {"AGGREGATES", "SURFACES_AT", "PRODUCES", "CONSUMES", "EVIDENCED_BY"}
    | set(l1_curator.SYSTEM_EDGE_RELS)
    | {k.upper() for k, _d in l1_curator.DATA_RELATIONSHIP_KINDS}
)


# --- AST-MERGE-01: merge builder re-points every allowlisted rel + deletes dup ---

def test_merge_builder_repoints_and_deletes():
    cy, params = l1_curator.build_merge_units_cypher(
        "L1Service",
        canonical_identity={"business_function_slug": "checkout"},
        duplicate_identity={"business_function_slug": "check-out"},
        provenance=PROV,
    )
    # both nodes MATCHed by identity, keys interpolated but VALUES parameterised
    assert "MATCH (canon:L1Service {business_function_slug: $canon_business_function_slug, project_id: $project_id})" in cy
    assert "MATCH (dup:L1Service {business_function_slug: $dup_business_function_slug, project_id: $project_id})" in cy
    assert params["canon_business_function_slug"] == "checkout"
    assert params["dup_business_function_slug"] == "check-out"
    # canonical is never deleted when canonical == duplicate (safe no-op guard)
    assert "WHERE elementId(canon) <> elementId(dup)" in cy
    # every allowlisted rel type re-pointed, BOTH directions
    for rel in _REQUIRED_REPOINT_RELS:
        assert f"MATCH (dup)-[r:{rel}]->(x) MERGE (canon)-[nr:{rel}]->(x)" in cy, rel
        assert f"MATCH (x)-[r:{rel}]->(dup) MERGE (x)-[nr:{rel}]->(canon)" in cy, rel
    # duplicate DETACH DELETEd; canonical stamped superseded + provenance
    assert "DETACH DELETE dup" in cy
    assert "SET canon.superseded_from = coalesce(canon.superseded_from, []) + [$dup_marker]" in cy
    assert params["dup_marker"] == "L1Service:business_function_slug=check-out"
    assert params["prov_job"] == "curation"
    # pure + deterministic
    cy2, _ = l1_curator.build_merge_units_cypher(
        "L1Service", {"business_function_slug": "checkout"}, {"business_function_slug": "check-out"}, PROV
    )
    assert cy == cy2


def test_merge_builder_copies_missing_props_after_delete():
    """The property copy runs AFTER the duplicate is deleted, so a transient copy
    of the duplicate's identity key can never collide with the still-present
    duplicate on the uniqueness constraint (the live-container failure mode)."""
    cy, _ = l1_curator.build_merge_units_cypher(
        "L1System", {"kind": "WAF", "discriminator": "__singleton__"},
        {"kind": "WAF", "discriminator": "dup"}, PROV,
    )
    assert cy.index("DETACH DELETE dup") < cy.index("SET canon += dupProps")
    # canon keeps its own props (second SET restores them), gains dup-only props
    assert "SET canon += dupProps" in cy and "SET canon += canonProps" in cy


# --- AST-MERGE-04 (guards): no L0 writes - every op rejects a non-L1 label ---

def test_no_l0_writes():
    for l0_label in ("Endpoint", "Service", "Parameter", "Header"):
        with pytest.raises(ValueError):
            l1_curator.build_delete_unit_cypher(l0_label, {"path": "/x"}, PROV)
        with pytest.raises(ValueError):
            l1_curator.build_merge_units_cypher(l0_label, {"path": "/a"}, {"path": "/b"}, PROV)
        with pytest.raises(ValueError):
            l1_curator.build_relabel_unit_cypher(l0_label, "L1System", {"path": "/x"}, {"kind": "WAF"}, PROV)
        with pytest.raises(ValueError):
            l1_curator.build_relabel_unit_cypher("L1Service", l0_label, {"business_function_slug": "s"}, {"path": "/x"}, PROV)
    # a valid delete only ever DETACH DELETEs an :L1* node; no L0 node label appears
    cy, _ = l1_curator.build_delete_unit_cypher("L1System", {"kind": "WAF", "discriminator": "__singleton__"}, PROV)
    assert "DETACH DELETE n" in cy
    assert "MATCH (n:L1System {" in cy
    # no builder ever MERGEs/CREATEs a bare L0 node label (a System relabel now
    # just SETs the `kind` attribute - no catalogue node is created either)
    node_write = re.compile(r"(MERGE|CREATE)\s*\(\s*\w*:(Endpoint|Parameter|Header)\b")
    for builder_cy in (
        cy,
        l1_curator.build_merge_units_cypher("L1Service", {"business_function_slug": "a"}, {"business_function_slug": "b"}, PROV)[0],
        l1_curator.build_relabel_unit_cypher("L1Service", "L1System", {"business_function_slug": "s"}, {"kind": "RESTApi"}, PROV)[0],
    ):
        assert not node_write.search(builder_cy)


# --- AST-MERGE-03 (builder shape): relabel swaps label, re-keys, remaps edge ---

def test_relabel_builder_swaps_label_rekeys_and_remaps_edge():
    cy, params = l1_curator.build_relabel_unit_cypher(
        "L1Service", "L1System",
        identity={"business_function_slug": "graphql-api"},
        new_identity={"kind": "GraphQLApi", "discriminator": "__singleton__"},
        provenance=PROV,
    )
    assert "MATCH (n:L1Service {business_function_slug: $id_business_function_slug, project_id: $project_id})" in cy
    assert "REMOVE n:L1Service" in cy and "SET n:L1System" in cy
    assert "REMOVE n.business_function_slug" in cy            # old key dropped
    assert "n.kind = $newid_kind" in cy                       # new keys set
    assert "n.discriminator = $newid_discriminator" in cy
    assert params["newid_kind"] == "GraphQLApi"
    assert params["newid_discriminator"] == "__singleton__"
    # AGGREGATES -> EVIDENCED_BY re-point (semantics change with the type)
    assert "MATCH (n)-[r:AGGREGATES]->(x) MERGE (n)-[nr:EVIDENCED_BY]->(x)" in cy
    # operator correction 2026-07-20: no catalogue node, no OF_KIND edge - the
    # `kind` attribute is simply SET on the re-kinded node
    assert "SystemKind" not in cy
    assert "OF_KIND" not in cy
    # provenance stamped
    assert params["relabelled_from"] == "L1Service:business_function_slug=graphql-api"
    assert "SET n.prov_job = $prov_job" in cy


def test_relabel_to_system_requires_known_kind_and_coerces_blank_discriminator():
    with pytest.raises(ValueError):
        l1_curator.build_relabel_unit_cypher(
            "L1Service", "L1System", {"business_function_slug": "s"}, {"kind": "NotAKind"}, PROV
        )
    # blank discriminator coerced to the non-null singleton sentinel (L1D-9)
    _, params = l1_curator.build_relabel_unit_cypher(
        "L1Service", "L1System", {"business_function_slug": "s"},
        {"kind": "WAF", "discriminator": "   "}, PROV,
    )
    assert params["newid_discriminator"] == "__singleton__"


# --- AST-MERGE-04 (injection guard): unsafe identity keys are rejected ---

def test_reconcile_builders_reject_unsafe_identity_keys():
    with pytest.raises(ValueError):
        l1_curator.build_delete_unit_cypher("L1Service", {"slug) DETACH DELETE n //": "x"}, PROV)
    with pytest.raises(ValueError):
        l1_curator.build_merge_units_cypher(
            "L1Service", {"business_function_slug": "a"}, {"bad key": "b"}, PROV
        )
    with pytest.raises(ValueError):
        l1_curator.build_delete_unit_cypher("L1Service", {}, PROV)  # empty identity


# --- AST-MERGE-04: reconcile is fail-open per op (no DB - injected fake merge_fn) ---

def test_reconcile_fail_open():
    calls = []
    merges = [
        MergeOp(label="L1Service", canonical={"business_function_slug": "a"}, duplicate={"business_function_slug": "b"}, provenance=PROV),
        MergeOp(label="Endpoint", canonical={"path": "/a"}, duplicate={"path": "/b"}, provenance=PROV),  # L0 label -> skipped at build
    ]
    deletes = [
        DeleteOp(label="L1System", identity={"kind": "WAF", "discriminator": "__singleton__"}, provenance=PROV),
        DeleteOp(label="L1Service", identity={}, provenance=PROV),  # empty identity -> skipped at build
    ]
    relabels = [
        RelabelOp(from_label="L1Service", to_label="L1System", identity={"business_function_slug": "s"}, new_identity={"kind": "RESTApi"}, provenance=PROV),
        RelabelOp(from_label="L1Service", to_label="L1System", identity={"business_function_slug": "s2"}, new_identity={"kind": "Bogus"}, provenance=PROV),  # unknown kind -> skipped
    ]
    out = l1_curator.reconcile(
        "proj1", merges=merges, deletes=deletes, relabels=relabels,
        merge_fn=lambda cy, p: calls.append((cy, p)),
    )
    # one good op survives per category; the bad op in each is skipped+logged
    assert out == {"merged": 1, "deleted": 1, "relabelled": 1}
    assert len(calls) == 3
    assert all(c[1]["project_id"] == "proj1" for c in calls)


def test_reconcile_merge_fn_exception_does_not_abort_batch():
    """A merge_fn that raises on one op is skipped+logged; the batch continues."""
    seen = []

    def flaky(cy, p):
        seen.append(p)
        if p.get("id_business_function_slug") == "boom":
            raise RuntimeError("db blip")

    deletes = [
        DeleteOp(label="L1Service", identity={"business_function_slug": "boom"}, provenance=PROV),  # merge_fn raises
        DeleteOp(label="L1Service", identity={"business_function_slug": "ok"}, provenance=PROV),   # succeeds
    ]
    out = l1_curator.reconcile("proj1", deletes=deletes, merge_fn=flaky)
    assert out == {"merged": 0, "deleted": 1, "relabelled": 0}
    assert len(seen) == 2  # both attempted; one failed without aborting the batch


def test_reconcile_defaults_to_neo4j_client_merge(monkeypatch):
    calls = []
    import polymerhus.app.clients.neo4j_client as nc
    monkeypatch.setattr(nc, "merge", lambda cy, p: calls.append((cy, p)))
    out = l1_curator.reconcile(
        "proj1",
        deletes=[DeleteOp(label="L1Service", identity={"business_function_slug": "x"}, provenance=PROV)],
    )
    assert out == {"merged": 0, "deleted": 1, "relabelled": 0}
    assert len(calls) == 1 and calls[0][1]["project_id"] == "proj1"
