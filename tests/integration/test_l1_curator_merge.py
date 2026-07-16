"""FR-LCUR integration tier — the L1 sole-writer against the REAL neo4j:5.26
container. Encodes the store-level assertions (docs/design/L1-MVP-plan.md §5):
idempotent MERGE, singleton dedup, identity ⊥ membership, SystemKind seed +
OF_KIND, constraints enforced, provenance persisted, and the :L1* namespace
disjoint from the L0 :Service label.

Mirrors the live-graph convention already used by tests/e2e/test_neo4j_write_dedup.py
and tests/test_neo4j_schema.py: connect from the host to the published bolt port,
apply the schema, run against a unique per-test project_id, clean up. The
AGGREGATES cross-layer edge + envelope (AST-LCUR-04/05) are covered by
test_aggregates_envelope_persisted_and_idempotent and
test_aggregates_edge_resolves_l0, using the native
`(:L1Service)-[:AGGREGATES {envelope}]->(:L0)` edge (operator decision, option A).
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from agent.recon import curator
from agent.recon.analysis import l1_curator, l1_read
from agent.recon.analysis.l1_types import (
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
    SystemDelta,
)
from agent.recon.types import AssetDelta
from tests.conftest import wait_for

URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")
PROV = Provenance(job="it", model="m", prompt_id="p")
ENV = JudgmentEnvelope(confidence=0.82, status="committed", evidence_refs=["obs:cat-params"], provenance=PROV)
ENDPOINT_ID = {"path": "/categories/{id}/parameters", "method": "GET", "baseurl": "https://a"}


def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d


@pytest.fixture(scope="module")
def session():
    # Best-effort bring-up (already healthy in dev); skip cleanly if unreachable.
    try:
        subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=False)
    except Exception:  # noqa: BLE001 - docker CLI may be absent in some CI
        pass
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"neo4j not reachable for L1 integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "l1lcur_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _merge_fn(session):
    return lambda cy, params: session.run(cy, **params).consume()


def _count(session, label, pid, **props):
    where = " AND ".join(f"n.{k} = ${k}" for k in props)
    q = (
        f"MATCH (n:{label}) WHERE n.project_id = $p"
        + (f" AND {where}" if props else "")
        + " RETURN count(n) AS c"
    )
    return session.run(q, p=pid, **props).single()["c"]


def _write_l0_endpoint(session, pid, identity=ENDPOINT_ID, **props):
    """Write a real L0 Endpoint through the L0 curator's own builder (the sole L0
    write path), so the AGGREGATES edge has a genuine co-resident target."""
    cy, params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity=dict(identity), props=props or {"status_code": 200})
    )
    params["project_id"] = pid
    session.run(cy, **params).consume()


# --- AST-LCUR-01: idempotent MERGE -> exactly one node on replay ---

def test_service_merge_twice_one_node(session, project):
    d = ServiceDelta(business_function_slug="checkout", props={"label": "Checkout"}, provenance=PROV)
    for _ in range(2):
        l1_curator.l1_curate([d], [], project, merge_fn=_merge_fn(session))
    assert _count(session, "L1Service", project, business_function_slug="checkout") == 1


# --- AST-LCUR-02: two singleton Systems of one kind MERGE to one node; never null ---

def test_singleton_system_dedup(session, project):
    d = SystemDelta(system_kind="AuthenticationMechanism", provenance=PROV)
    for _ in range(2):
        l1_curator.l1_curate([], [d], project, merge_fn=_merge_fn(session))
    assert _count(
        session, "L1System", project,
        system_kind="AuthenticationMechanism", discriminator="__singleton__",
    ) == 1
    nulls = session.run(
        "MATCH (n:L1System) WHERE n.project_id = $p AND n.discriminator IS NULL RETURN count(n) AS c",
        p=project,
    ).single()["c"]
    assert nulls == 0


# --- AST-LCUR-03: identity independent of membership ---

def test_identity_independent_of_members(session, project):
    mf = _merge_fn(session)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="orders", props={"members": "a"}, provenance=PROV)], [], project, merge_fn=mf)
    # re-run the SAME identity with a DIFFERENT member-ish payload
    l1_curator.l1_curate([ServiceDelta(business_function_slug="orders", props={"members": "a,b,c"}, provenance=PROV)], [], project, merge_fn=mf)
    assert _count(session, "L1Service", project, business_function_slug="orders") == 1
    rec = session.run(
        "MATCH (n:L1Service {project_id: $p, business_function_slug: 'orders'}) RETURN n.members AS m",
        p=project,
    ).single()
    assert rec["m"] == "a,b,c"  # props updated, identity unchanged, no duplicate


# --- AST-LCUR-06: SystemKind seed idempotent + a System OF_KIND its catalogue row ---

def test_systemkind_seed_idempotent_and_of_kind(session, project):
    mf = _merge_fn(session)
    for _ in range(2):
        seeded = l1_curator.seed_system_kinds(project, merge_fn=mf)
    assert seeded == 13
    assert _count(session, "SystemKind", project) == 13
    # catalogue rows are provenance'd (spec §2.3) + carry description/timestamps
    krec = session.run(
        "MATCH (k:SystemKind {project_id: $p, id: 'RESTApi'}) "
        "RETURN k.prov_job AS j, k.first_seen AS f, k.description AS d",
        p=project,
    ).single()
    assert krec["j"] == "l1_curator:seed_system_kinds"
    assert krec["f"] is not None
    assert krec["d"]
    l1_curator.l1_curate([], [SystemDelta(system_kind="RESTApi", provenance=PROV)], project, merge_fn=mf)
    linked = session.run(
        "MATCH (:L1System {project_id: $p, system_kind: 'RESTApi'})-[:OF_KIND]->"
        "(k:SystemKind {project_id: $p, id: 'RESTApi'}) RETURN count(*) AS c",
        p=project,
    ).single()["c"]
    assert linked == 1
    assert _count(session, "SystemKind", project) == 13  # OF_KIND MERGE did not duplicate


# --- AST-LCUR-07: L1 constraints present and enforced ---

def test_l1_constraints_present_and_enforced(session, project):
    from neo4j.exceptions import ClientError

    names = {r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name")}
    assert {"l1service_unique", "l1system_unique", "systemkind_unique"} <= names
    # enforcement (not just presence): a direct duplicate CREATE — which, unlike
    # MERGE, does not dedup — must be rejected by the uniqueness constraint. This
    # fails loudly if a constraint is ever dropped/disabled (MERGE tests alone
    # would still pass).
    slug = "enf-" + project
    session.run(
        "CREATE (n:L1TestableUnit:L1Service {project_id: $p, business_function_slug: $s})",
        p=project, s=slug,
    ).consume()
    with pytest.raises(ClientError):
        session.run(
            "CREATE (n:L1TestableUnit:L1Service {project_id: $p, business_function_slug: $s})",
            p=project, s=slug,
        ).consume()


# --- AST-LCUR-09: provenance + timestamps persisted ---

def test_provenance_persisted(session, project):
    l1_curator.l1_curate(
        [ServiceDelta(business_function_slug="reviews", provenance=Provenance(job="bootstrap", model="gpt", prompt_id="pid1"))],
        [], project, merge_fn=_merge_fn(session),
    )
    rec = session.run(
        "MATCH (n:L1Service {project_id: $p, business_function_slug: 'reviews'}) "
        "RETURN n.prov_job AS j, n.prov_model AS m, n.prov_prompt_id AS pi, "
        "n.first_seen AS f, n.last_seen AS l",
        p=project,
    ).single()
    assert rec["j"] == "bootstrap" and rec["m"] == "gpt" and rec["pi"] == "pid1"
    assert rec["f"] is not None and rec["l"] is not None


# --- AST-LCUR-10: :L1* namespace disjoint from the L0 :Service label ---

def test_l1_namespace_disjoint_from_l0_service(session, project):
    mf = _merge_fn(session)
    # L0 network :Service (port service) and L1 business :L1Service coexist under one project
    session.run(
        "MERGE (svc:Service {name: 'https', port_number: 443, ip_address: '1.2.3.4', project_id: $p})",
        p=project,
    )
    l1_curator.l1_curate([ServiceDelta(business_function_slug="https-biz", provenance=PROV)], [], project, merge_fn=mf)
    assert _count(session, "Service", project) == 1
    assert _count(session, "L1Service", project) == 1
    both = session.run(
        "MATCH (n:L1TestableUnit:L1Service {project_id: $p}) RETURN count(n) AS c", p=project,
    ).single()["c"]
    assert both == 1  # the L1 unit carries the supertype label
    overlap = session.run(
        "MATCH (n:Service:L1Service {project_id: $p}) RETURN count(n) AS c", p=project,
    ).single()["c"]
    assert overlap == 0  # no node is both an L0 Service and an L1 Service


# --- AST-LCUR-04: the AGGREGATES edge persists the envelope + is idempotent ---

def test_aggregates_envelope_persisted_and_idempotent(session, project):
    mf = _merge_fn(session)
    _write_l0_endpoint(session, project)  # recon precedes assignment
    l1_curator.l1_curate([ServiceDelta(business_function_slug="product-introspection", provenance=PROV)], [], project, merge_fn=mf)
    d = AggregatesDelta(service_slug="product-introspection", l0=L0Ref(label="Endpoint", identity=ENDPOINT_ID), envelope=ENV)
    for _ in range(2):  # replay -> exactly one AGGREGATES edge (MERGE on the pattern)
        l1_curator.write_aggregates([d], project, merge_fn=mf)
    rec = session.run(
        "MATCH (:L1Service {project_id: $p, business_function_slug: 'product-introspection'})"
        "-[r:AGGREGATES]->(e:Endpoint {project_id: $p}) "
        "RETURN count(r) AS c, collect(r.confidence)[0] AS conf, collect(r.status)[0] AS st, "
        "collect(r.evidence_refs)[0] AS ev, collect(r.prov_job)[0] AS j, collect(r.ts)[0] AS ts",
        p=project,
    ).single()
    assert rec["c"] == 1  # idempotent: one edge, not two
    assert rec["conf"] == 0.82
    assert rec["st"] == "committed"
    assert rec["ev"] == ["obs:cat-params"]
    assert rec["j"] == "it"  # envelope provenance (module PROV.job)
    assert rec["ts"] is not None  # server-stamped when the envelope carried none


# --- AST-LCUR-05: the cross-layer edge resolves the L0 node (traversal-then-fetch) ---

def test_aggregates_edge_resolves_l0(session, project):
    mf = _merge_fn(session)
    read_fn = lambda cy, p: [dict(r) for r in session.run(cy, **p)]
    _write_l0_endpoint(session, project)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="product-introspection", provenance=PROV)], [], project, merge_fn=mf)
    l1_curator.write_aggregates(
        [AggregatesDelta(service_slug="product-introspection", l0=L0Ref(label="Endpoint", identity=ENDPOINT_ID), envelope=ENV)],
        project, merge_fn=mf,
    )
    # resolve lazily by traversing the native AGGREGATES edge (one hop)
    l0_nodes = l1_read.read_aggregated_l0("product-introspection", project, read_fn=read_fn)
    assert len(l0_nodes) == 1
    assert l0_nodes[0]["path"] == "/categories/{id}/parameters"
    assert l0_nodes[0]["status_code"] == 200
    assert "Endpoint" in l0_nodes[0]["_labels"]
    # the L1 Service is still keyed by slug, NOT by the L0 path (L1 never reuses an L0 key)
    svc = session.run(
        "MATCH (s:L1Service {project_id: $p, business_function_slug: 'product-introspection'}) "
        "RETURN s.business_function_slug AS k, s.path AS path",
        p=project,
    ).single()
    assert svc["k"] == "product-introspection" and svc["path"] is None


# --- AST-LCUR-05 (fail-open): a missing L0 target creates no edge and no L0 node ---

def test_aggregates_missing_l0_target_is_noop(session, project):
    mf = _merge_fn(session)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="ghost", provenance=PROV)], [], project, merge_fn=mf)
    # target L0 endpoint does NOT exist -> the MATCH yields nothing
    l1_curator.write_aggregates(
        [AggregatesDelta(
            service_slug="ghost",
            l0=L0Ref(label="Endpoint", identity={"path": "/nope", "method": "GET", "baseurl": "https://a"}),
            envelope=ENV,
        )],
        project, merge_fn=mf,
    )
    no_edge = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AGGREGATES]->() RETURN count(r) AS c", p=project,
    ).single()["c"]
    assert no_edge == 0  # no edge created
    assert _count(session, "Endpoint", project) == 0  # l1_curator did NOT create an L0 node
