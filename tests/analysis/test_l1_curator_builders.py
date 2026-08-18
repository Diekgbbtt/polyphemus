"""FR-LCUR unit tier — the L1 sole-writer's PURE builders (no driver, no I/O).

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md §5). The
store-level invariants (real MERGE idempotency, constraint enforcement) are the
integration tier (tests/integration/test_l1_curator_merge.py); here we assert the
Cypher/params the builders produce and the guards they raise.
"""
import pathlib
import re

import pytest

from polymerhus.analysis import l1_curator
from polymerhus.analysis.l1_types import (
    L1_SINGLETON,
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
    SystemDelta,
)

PROV = Provenance(job="bootstrap", model="m", prompt_id="p")
ENV = JudgmentEnvelope(confidence=0.82, evidence_refs=["obs:1"], provenance=PROV)


# --- AST-LCUR-01 / AST-LCUR-07: Service builder is pure, deterministic, keyed ---

def test_service_merge_builder_is_pure_and_keyed():
    d = ServiceDelta(business_function_slug="checkout", props={"label": "Checkout"}, provenance=PROV)
    cy, params = l1_curator.build_service_cypher(d)
    assert (
        "MERGE (n:L1TestableUnit:L1Service "
        "{business_function_slug: $id_business_function_slug, project_id: $project_id})"
    ) in cy
    assert "first_seen" in cy and "last_seen" in cy
    assert params["id_business_function_slug"] == "checkout"
    assert params["props"] == {"label": "Checkout"}
    # pure + deterministic: identical input -> identical Cypher (no hidden state)
    cy2, _ = l1_curator.build_service_cypher(d)
    assert cy == cy2


# --- AST-LCUR-02: discriminator defaults to the non-null __singleton__ string ---

def test_discriminator_defaults_to_singleton_string():
    d = SystemDelta(kind="AuthenticationMechanism", provenance=PROV)
    assert d.discriminator == L1_SINGLETON == "__singleton__"
    _, params = l1_curator.build_system_cypher(d)
    assert params["id_discriminator"] == "__singleton__"
    assert params["id_discriminator"] is not None
    # a blank discriminator is coerced to the sentinel, never left null/empty
    _, p2 = l1_curator.build_system_cypher(SystemDelta(kind="WAF", discriminator="   ", provenance=PROV))
    assert p2["id_discriminator"] == "__singleton__"


# --- AST-LCUR-07: System key shape (project_id, kind, discriminator); no catalogue node ---

def test_system_key_shape_and_no_catalogue_node():
    d = SystemDelta(kind="CDN", discriminator="Datadome", provenance=PROV)
    cy, params = l1_curator.build_system_cypher(d)
    assert (
        "MERGE (n:L1TestableUnit:L1System "
        "{discriminator: $id_discriminator, kind: $id_kind, project_id: $project_id})"
    ) in cy
    assert params["id_kind"] == "CDN"
    assert params["id_discriminator"] == "Datadome"
    # operator correction 2026-07-20: no :SystemKind catalogue node, no OF_KIND edge
    assert "SystemKind" not in cy
    assert "OF_KIND" not in cy


# --- AST-LCUR-08: guards — disallowed labels / unknown kinds / bad identity raise ---

def test_disallowed_unit_label_raises():
    with pytest.raises(ValueError):
        l1_curator.build_unit_cypher("Endpoint", {"x": "y"}, {}, PROV)  # an L0 label
    with pytest.raises(ValueError):
        l1_curator.build_unit_cypher("L1Bogus", {"x": "y"}, {}, PROV)


def test_unknown_system_kind_raises():
    with pytest.raises(ValueError):
        l1_curator.build_system_cypher(SystemDelta(kind="NotAKind", provenance=PROV))


def test_empty_service_slug_raises():
    with pytest.raises(ValueError):
        l1_curator.build_service_cypher(ServiceDelta(business_function_slug="   ", provenance=PROV))


def test_null_identity_component_raises():
    with pytest.raises(ValueError):
        l1_curator.build_unit_cypher("L1Service", {"business_function_slug": None}, {}, PROV)


# --- AST-LCUR-09: provenance + first/last_seen stamped on every write ---

def test_writes_carry_provenance_and_timestamps():
    cy, params = l1_curator.build_service_cypher(ServiceDelta(business_function_slug="orders", provenance=PROV))
    assert "ON CREATE SET n.first_seen = datetime()" in cy
    assert "SET n.last_seen = datetime()" in cy
    assert "n.prov_job = $prov_job" in cy
    assert "n.prov_model = $prov_model" in cy
    assert "n.prov_prompt_id = $prov_prompt_id" in cy
    assert params["prov_job"] == "bootstrap"
    assert params["prov_model"] == "m"
    assert params["prov_prompt_id"] == "p"


def test_reserved_props_are_stripped_so_they_cannot_spoof_identity_or_provenance():
    d = ServiceDelta(
        business_function_slug="cart",
        props={"project_id": "evil", "prov_job": "spoof", "business_function_slug": "evil", "label": "Cart"},
        provenance=PROV,
    )
    _, params = l1_curator.build_service_cypher(d)
    assert params["props"] == {"label": "Cart"}
    assert params["prov_job"] == "bootstrap"
    assert params["id_business_function_slug"] == "cart"


# --- AST-LCUR-06: the known-system-kinds enumeration (12 kinds; no catalogue) ---

def test_all_twelve_seed_kinds_present():
    ids = {kind_id for kind_id, _desc in l1_curator.SYSTEM_KINDS}
    assert len(l1_curator.SYSTEM_KINDS) == 12
    for expected in (
        "WAF", "CDN", "ReverseProxy", "APIGateway", "RESTApi", "GraphQLApi",
        "IdentificationSystem", "IntegrationSystem", "AuthenticationMechanism",
        "AuthorizationSystem", "WebPresentation", "Sitemap",
    ):
        assert expected in ids


# --- AST-MODEL-01: the mechanism-as-System correction (WebPresentation replaces
# the two RenderingSystem_* kinds; RENDERED_BY leaves the edge taxonomy) ---

def test_webpresentation_replaces_rendering_systems():
    ids = {kind_id for kind_id, _desc in l1_curator.SYSTEM_KINDS}
    # the single WebPresentation kind carries rendering_model + navigation_model props
    assert "WebPresentation" in ids
    # the two per-rendering-mode kinds are gone (merged into WebPresentation)
    assert "RenderingSystem_SSR_UI" not in ids
    assert "RenderingSystem_CSR_JSMap" not in ids


def test_rendered_by_removed_from_edge_taxonomy():
    # RENDERED_BY is deleted; a Service reaches its web presentation via EXPOSED_VIA
    assert "RENDERED_BY" not in l1_curator.SYSTEM_EDGE_RELS
    assert "EXPOSED_VIA" in l1_curator.SYSTEM_EDGE_RELS
    # the merge re-point allowlist is DERIVED from SYSTEM_EDGE_RELS, so it drops
    # RENDERED_BY automatically (the edge no longer exists to re-point)
    assert "RENDERED_BY" not in l1_curator._REPOINT_REL_TYPES


# --- AST-LCUR-08 / FR-NFR: sole-writer wiring + fail-open batching ---

def test_l1_curate_defaults_to_neo4j_client_merge(monkeypatch):
    """When no merge_fn is injected, the sole-writer dispatches through
    neo4j_client.merge (the same driver seam L0's curator uses)."""
    calls = []
    import polymerhus.app.clients.neo4j_client as nc
    monkeypatch.setattr(nc, "merge", lambda cy, p: calls.append((cy, p)))
    n_s, n_sy = l1_curator.l1_curate([ServiceDelta(business_function_slug="x", provenance=PROV)], [], "proj1")
    assert (n_s, n_sy) == (1, 0)
    assert len(calls) == 1
    assert calls[0][1]["project_id"] == "proj1"


def test_l1_curate_skips_bad_and_continues():
    calls = []
    services = [
        ServiceDelta(business_function_slug="good", provenance=PROV),
        ServiceDelta(business_function_slug="   ", provenance=PROV),  # bad -> skipped
    ]
    systems = [
        SystemDelta(kind="WAF", provenance=PROV),
        SystemDelta(kind="Bogus", provenance=PROV),  # unknown -> skipped
    ]
    n_s, n_sy = l1_curator.l1_curate(services, systems, "proj1", merge_fn=lambda cy, p: calls.append((cy, p)))
    assert (n_s, n_sy) == (1, 1)
    assert len(calls) == 2


def test_no_other_production_module_writes_l1():
    """Sole-writer discipline: only l1_curator.py may emit an :L1* node MERGE or
    an :AGGREGATES cross-layer edge."""
    root = pathlib.Path(l1_curator.__file__).resolve().parents[3]
    # Only WRITES matter (MERGE/CREATE) — a read traversal (MATCH ...-[:AGGREGATES])
    # or a docstring mention is fine.
    node_pat = re.compile(r"(MERGE|CREATE)\s*\([^)]*:L1(Service|System|TestableUnit|DataItem)")
    edge_pat = re.compile(r"(MERGE|CREATE)\s*\([^)]*\)\s*-\[[^\]]*:AGGREGATES")
    offenders = []
    for base in ("agent", "db"):
        for py in (root / base).rglob("*.py"):
            if py.name == "l1_curator.py" or "__pycache__" in py.parts:
                continue
            text = py.read_text(encoding="utf-8", errors="ignore")
            if node_pat.search(text) or edge_pat.search(text):
                offenders.append(str(py.relative_to(root)))
    assert offenders == [], f"unexpected :L1 node / :AGGREGATES writers outside l1_curator: {offenders}"


# --- AST-LCUR-04: the AGGREGATES native edge carries the full judgment envelope ---

def test_aggregates_edge_carries_full_envelope():
    d = AggregatesDelta(
        service_slug="product-introspection",
        l0=L0Ref(label="Endpoint", identity={"path": "/categories/{id}/parameters", "method": "GET", "baseurl": "https://a"}),
        envelope=ENV,
    )
    cy, params = l1_curator.build_aggregates_cypher(d)
    # native edge to the MATCHed (never MERGEd) co-resident L0 node (option A)
    assert "MATCH (l0:Endpoint {" in cy
    assert "MERGE (s:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $project_id})" in cy
    assert "MERGE (s)-[r:AGGREGATES]->(l0)" in cy
    assert "MERGE (l0" not in cy  # the L0 target is only ever MATCHed here
    # full envelope on the edge (L1D-25); MVP writes status="committed"
    assert params["confidence"] == 0.82
    assert params["status"] == "committed"
    assert params["evidence_refs"] == ["obs:1"]
    assert params["prov_job"] == "bootstrap"
    # L0 identity carried as MATCH params, keyed by L0's own key (L1D-2)
    assert params["l0_path"] == "/categories/{id}/parameters"
    assert params["l0_method"] == "GET"
    assert params["l0_baseurl"] == "https://a"


def test_aggregates_builder_is_deterministic_and_identity_order_independent():
    a = AggregatesDelta(service_slug="s", l0=L0Ref(label="Endpoint", identity={"path": "/x", "method": "GET", "baseurl": "https://a"}), envelope=ENV)
    b = AggregatesDelta(service_slug="s", l0=L0Ref(label="Endpoint", identity={"baseurl": "https://a", "method": "GET", "path": "/x"}), envelope=ENV)
    cy_a, _ = l1_curator.build_aggregates_cypher(a)
    cy_b, _ = l1_curator.build_aggregates_cypher(b)
    assert cy_a == cy_b  # sorted identity keys -> identity map order does not change the query


def test_aggregates_bad_input_raises():
    with pytest.raises(ValueError):  # empty service slug
        l1_curator.build_aggregates_cypher(
            AggregatesDelta(service_slug="   ", l0=L0Ref(label="Endpoint", identity={"path": "/x"}), envelope=ENV)
        )
    with pytest.raises(ValueError):  # empty L0 identity
        l1_curator.build_aggregates_cypher(
            AggregatesDelta(service_slug="s", l0=L0Ref(label="Endpoint", identity={}), envelope=ENV)
        )
    with pytest.raises(ValueError):  # unsafe L0 label (Cypher-injection guard)
        l1_curator.build_aggregates_cypher(
            AggregatesDelta(service_slug="s", l0=L0Ref(label="Endpoint) DETACH DELETE n //", identity={"path": "/x"}), envelope=ENV)
        )
