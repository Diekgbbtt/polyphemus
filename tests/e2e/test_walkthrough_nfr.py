"""FR-NFR e2e — the §15 walkthrough as a deterministic invariant proof.

Fires EVERY in-scope L1 primitive end-to-end through the REAL writers (no LLM;
canned deltas) against live Neo4j, then asserts the cross-cutting non-functional
invariants hold on the resulting graph: sole-writer, MERGE idempotency,
identity ⊥ membership, __singleton__ non-null (coexisting with a populated
discriminator), provenance on every node/edge, and the token-light index-card
(DD-4). The deferred primitives §15 also narrates (SystemAspect/NM-3, the
concretisation reducer/NM-10, Stage-3, the ordered ON_REQUEST_PATH inter-System
chain/AMV-7) are asserted ABSENT-from-scope, not built.

Mirrors the integration-tier fixture pattern (module session + per-test project),
routing every write through the test session as the sole-writer's merge_fn.
"""
import subprocess
import uuid
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from agent.recon import curator
from agent.recon.analysis import l1_curator, sweep, index_card
from agent.recon.analysis import anatomy
from agent.recon.analysis.anatomy import webpage_profile, classify_authz, commit_anatomy, WebpageProfileProposal
from agent.recon.analysis.l1_types import (
    AggregatesDelta, DataFlowDelta, DataItemDelta, JudgmentEnvelope, L0Ref,
    Provenance, ServiceDelta, SurfacesAtDelta, SystemDelta, SystemEdgeDelta,
)
from agent.recon.types import AssetDelta
from tests.conftest import wait_for

URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")

PROV = Provenance(job="analyser:walkthrough", model="m", prompt_id="p")
BOOTSTRAP_PROV = Provenance(job="bootstrap:walkthrough", model=None, prompt_id=None)

# §15 skeleton (a subset that still fires every primitive)
SERVICES = ["sign-in", "checkout", "orders", "reward-points", "product-introspection",
            "sales-analysis", "item-creation"]
BASEURL = "https://shop.example"
CAT_EP = {"path": "/categories/{id}/parameters", "method": "GET", "baseurl": BASEURL}
SALES_EP = {"path": "/sellers/{id}/sales", "method": "GET", "baseurl": BASEURL}
HEALTHZ_EP = {"path": "/healthz", "method": "GET", "baseurl": BASEURL}


def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d


@pytest.fixture(scope="module")
def session():
    try:
        subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=False)
    except Exception:  # noqa: BLE001
        pass
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"neo4j not reachable for the FR-NFR walkthrough: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "nfr_wt_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _run_walkthrough(session, project, *, member_endpoints=(CAT_EP, SALES_EP)):
    """Fire the whole §15 flow through the real writers. `member_endpoints` are the
    L0 endpoints sales-analysis aggregates (varied to test identity ⊥ membership).
    Returns nothing; asserts are done by the callers on the live graph."""
    mf = lambda cy, p: session.run(cy, **p).consume()
    read_fn = lambda cy, p: [r.data() for r in session.run(cy, **p)]

    # 0. seed the controlled-vocabulary catalogues
    l1_curator.seed_system_kinds(project, merge_fn=mf)
    l1_curator.seed_data_relationship_kinds(project, merge_fn=mf)

    # 1. bootstrap: the business Service skeleton + linchpin auth Systems, no L0 refs
    services = [ServiceDelta(business_function_slug=s, props={"label": s}, provenance=BOOTSTRAP_PROV)
                for s in SERVICES]
    systems = [SystemDelta(system_kind=k, provenance=BOOTSTRAP_PROV)
               for k in ("AuthenticationMechanism", "AuthorizationSystem")]
    # also a SINGLETON CDN so it can coexist with the populated-discriminator CDN below
    systems.append(SystemDelta(system_kind="CDN", provenance=BOOTSTRAP_PROV))
    l1_curator.l1_curate(services, systems, project, merge_fn=mf)

    # 2. recon lands L0 endpoints (via the L0 curator; AGGREGATES MATCHes them)
    for ep in (*member_endpoints, HEALTHZ_EP):
        cy, params = curator.build_asset_cypher(AssetDelta(type="Endpoint", identity=dict(ep), props={"status_code": 200}))
        params["project_id"] = project
        session.run(cy, **params).consume()

    # 3. assignment: AGGREGATES with the judgment envelope (/healthz left unassigned -> stale pool)
    env = JudgmentEnvelope(confidence=0.82, status="committed",
                           evidence_refs=["obs:returns sell params"], provenance=PROV)
    aggregates = [AggregatesDelta(service_slug="product-introspection", l0=L0Ref(label="Endpoint", identity=dict(CAT_EP)), envelope=env)]
    for ep in member_endpoints:
        aggregates.append(AggregatesDelta(service_slug="sales-analysis", l0=L0Ref(label="Endpoint", identity=dict(ep)), envelope=env))
    l1_curator.write_aggregates(aggregates, project, merge_fn=mf)

    # 4. enrichment: systems-as-edges (incl a POPULATED CDN discriminator), Tier-1 flow
    system_edges = [
        SystemEdgeDelta(service_slug="sales-analysis", system_kind="RESTApi", rel="EXPOSED_VIA", provenance=PROV),
        SystemEdgeDelta(service_slug="sales-analysis", system_kind="CDN", discriminator="Datadome", rel="FRONTED_BY", provenance=PROV),
        SystemEdgeDelta(service_slug="sales-analysis", system_kind="WAF", rel="PROTECTED_BY", provenance=PROV),
        SystemEdgeDelta(service_slug="sales-analysis", system_kind="ReverseProxy", discriminator="Varnish", rel="ROUTED_BY", provenance=PROV),
    ]
    data_items = [DataItemDelta(item_key="sales_figure", props={"label": "sales figure"}, provenance=PROV)]
    surfaces_at = [SurfacesAtDelta(item_key="sales_figure", l0=L0Ref(label="Endpoint", identity=dict(SALES_EP)), provenance=PROV)]
    data_flows = [
        DataFlowDelta(service_slug="item-creation", item_key="sales_figure", direction="produces", provenance=PROV),
        DataFlowDelta(service_slug="sales-analysis", item_key="sales_figure", direction="consumes",
                      assumption="the figure was authorized for THIS user",
                      assumption_rationale="cross-service financial data rendered in UI", provenance=PROV),
    ]
    l1_curator.enrich(project, data_items=data_items, surfaces_at=surfaces_at, data_flows=data_flows,
                      system_edges=system_edges, merge_fn=mf)

    # 5. webpage-profile anatomy skill: independent SPA + CSR spine slots (canned proposal)
    wp = webpage_profile({"base_url": BASEURL}, service_id="sales-analysis",
                         profile_fn=lambda s: WebpageProfileProposal(
                             navigation_model="SPA", navigation_confidence="High",
                             navigation_evidence="pushState nav + JSON fetch, no Document reload",
                             rendering_model="CSR", rendering_confidence="High",
                             rendering_evidence="empty shell, DOM built post-JS"),
                         steel_available=True)
    commit_anatomy(wp, project, "sales-analysis",
                   curate_fn=lambda svc, sys, pid: l1_curator.l1_curate(svc, sys, pid, merge_fn=mf),
                   observe_fn=lambda obs, pid: curator.curate([], obs, pid, merge_fn=mf),
                   edge_fn=lambda edges, pid: l1_curator.enrich(pid, system_edges=edges, merge_fn=mf))

    # 6. authorization-pyramid skill: AUTHORIZED_BY{role} + AUTHENTICATED_BY{realm} typed edges
    az = classify_authz("view-seller-sales", {"seller": True, "seller-admin": True, "guest": False},
                        service_slug="sales-analysis", base_url=BASEURL,
                        role_realms={"seller": "credential", "seller-admin": "idp"})
    commit_anatomy(az, project, "sales-analysis",
                   curate_fn=lambda svc, sys, pid: l1_curator.l1_curate(svc, sys, pid, merge_fn=mf),
                   observe_fn=lambda obs, pid: curator.curate([], obs, pid, merge_fn=mf),
                   edge_fn=lambda edges, pid: l1_curator.enrich(pid, system_edges=edges, merge_fn=mf))

    return read_fn


# --- AST-NFR-01: the whole walkthrough is idempotent ---

def test_walkthrough_is_idempotent(session, project):
    _run_walkthrough(session, project)
    _run_walkthrough(session, project)  # run the ENTIRE sequence twice

    def c(q):
        return session.run(q, p=project).single()["c"]

    assert c("MATCH (n:L1Service {project_id:$p}) RETURN count(n) AS c") == len(SERVICES)
    # no duplicate service identity
    dup = session.run("MATCH (n:L1Service {project_id:$p}) WITH n.business_function_slug AS k, count(*) AS c "
                      "WHERE c>1 RETURN count(k) AS d", p=project).single()["d"]
    assert dup == 0
    # one AGGREGATES edge per (service, endpoint), one CONSUMES, one FRONTED_BY, one DataItem
    assert c("MATCH (:L1Service {project_id:$p})-[r:AGGREGATES]->() RETURN count(r) AS c") == 3
    assert c("MATCH (:L1Service {project_id:$p})-[r:CONSUMES]->() RETURN count(r) AS c") == 1
    assert c("MATCH (:L1Service {project_id:$p})-[r:FRONTED_BY]->() RETURN count(r) AS c") == 1
    assert c("MATCH (d:L1DataItem {project_id:$p}) RETURN count(d) AS c") == 1
    # one AUTHORIZED_BY per authorised role (2), not doubled
    assert c("MATCH (:L1Service {project_id:$p})-[r:AUTHORIZED_BY]->() RETURN count(r) AS c") == 2


# --- AST-NFR-02: __singleton__ + a populated discriminator of the same kind coexist ---

def test_singleton_and_populated_discriminator_coexist(session, project):
    _run_walkthrough(session, project)
    cdns = session.run("MATCH (y:L1System {project_id:$p, system_kind:'CDN'}) "
                       "RETURN y.discriminator AS d ORDER BY d", p=project)
    discs = [r["d"] for r in cdns]
    assert discs == ["Datadome", "__singleton__"]  # two DISTINCT CDN nodes coexist
    # the sentinel is a literal non-null string, never null
    nulls = session.run("MATCH (y:L1System {project_id:$p}) WHERE y.discriminator IS NULL RETURN count(y) AS c",
                        p=project).single()["c"]
    assert nulls == 0


# --- AST-NFR-03: provenance on every L1 node + edge; envelope on AGGREGATES ---

def test_provenance_on_every_node_and_edge(session, project):
    _run_walkthrough(session, project)
    # every L1 node carries prov_job
    noprov = session.run("MATCH (n {project_id:$p}) WHERE (n:L1Service OR n:L1System OR n:L1DataItem) "
                         "AND n.prov_job IS NULL RETURN count(n) AS c", p=project).single()["c"]
    assert noprov == 0
    # every L1-authored edge carries prov_job
    for rel in ("AGGREGATES", "CONSUMES", "PRODUCES", "SURFACES_AT", "EXPOSED_VIA", "FRONTED_BY", "AUTHORIZED_BY", "AUTHENTICATED_BY"):
        bad = session.run(f"MATCH (a {{project_id:$p}})-[r:{rel}]->() WHERE r.prov_job IS NULL RETURN count(r) AS c",
                          p=project).single()["c"]
        assert bad == 0, f"{rel} edge missing prov_job"
    # the AGGREGATES edge carries the full judgment envelope
    env = session.run("MATCH (:L1Service {project_id:$p})-[r:AGGREGATES]->() "
                      "RETURN count(r) AS t, sum(CASE WHEN r.confidence IS NOT NULL AND r.status IS NOT NULL "
                      "AND r.evidence_refs IS NOT NULL THEN 1 ELSE 0 END) AS full", p=project).single()
    assert env["t"] == 3 and env["full"] == 3
    # ON CREATE (not unconditional SET): a bootstrap-minted Service that a later
    # EDGE writer only touches KEEPS its original provenance (item-creation is
    # bootstrapped, then the PRODUCES edge writer references it). A regression to
    # unconditional SET would clobber it to the edge writer's job - this locks it.
    ic_prov = session.run("MATCH (s:L1Service {project_id:$p, business_function_slug:'item-creation'}) "
                          "RETURN s.prov_job AS j", p=project).single()["j"]
    assert ic_prov == "bootstrap:walkthrough"  # not overwritten by the PRODUCES edge writer


# --- AST-NFR-04: identity ⊥ membership ---

def test_identity_independent_of_membership(session, project):
    _run_walkthrough(session, project, member_endpoints=(CAT_EP, SALES_EP))
    before = session.run("MATCH (s:L1Service {project_id:$p, business_function_slug:'sales-analysis'}) "
                         "RETURN elementId(s) AS id, s.first_seen AS fs", p=project).single()
    # re-run with a LARGER member set (a third endpoint assigned to sales-analysis)
    extra_ep = {"path": "/sellers/{id}/revenue", "method": "GET", "baseurl": BASEURL}
    _run_walkthrough(session, project, member_endpoints=(CAT_EP, SALES_EP, extra_ep))
    after = session.run("MATCH (s:L1Service {project_id:$p, business_function_slug:'sales-analysis'}) "
                        "RETURN elementId(s) AS id, s.first_seen AS fs", p=project).single()
    # identity unchanged: still ONE node, same element id, same first_seen - membership grew, identity did not
    n = session.run("MATCH (s:L1Service {project_id:$p, business_function_slug:'sales-analysis'}) RETURN count(s) AS c",
                    p=project).single()["c"]
    assert n == 1
    assert after["id"] == before["id"]
    assert after["fs"] == before["fs"]  # first_seen unchanged: the key held across the re-curate
    # membership DID grow (identity ⊥ membership: the key held while the member set changed)
    members = session.run("MATCH (:L1Service {project_id:$p, business_function_slug:'sales-analysis'})-[:AGGREGATES]->(e) "
                          "RETURN count(e) AS c", p=project).single()["c"]
    assert members == 3


# --- AST-NFR-05: sole-writer discipline (static) ---

def test_sole_writer_discipline():
    # only l1_curator may emit an :L1* label write; grep the agent tree for L1-label
    # MERGE/CREATE and confirm every hit is inside l1_curator.py.
    root = Path(__file__).resolve().parents[2] / "agent"
    offenders = []
    import re
    l1_write = re.compile(r"(MERGE|CREATE)\s*\([^)]*:L1")
    for py in root.rglob("*.py"):
        if py.name == "l1_curator.py":
            continue
        text = py.read_text(encoding="utf-8")
        if l1_write.search(text):
            offenders.append(str(py.relative_to(root)))
    assert offenders == [], f"non-l1_curator modules emit :L1* label writes: {offenders}"


# --- AST-NFR-06: every in-scope primitive fired ---

def test_every_inscope_primitive_fired(session, project):
    read_fn = _run_walkthrough(session, project)

    def c(q):
        return session.run(q, p=project).single()["c"]

    # assignment envelope, systems-as-edges, Tier-1 flow with assumption, SURFACES_AT
    assert c("MATCH (:L1Service {project_id:$p})-[r:AGGREGATES]->() WHERE r.confidence IS NOT NULL RETURN count(r) AS c") >= 1
    assert c("MATCH (:L1Service {project_id:$p})-[r:EXPOSED_VIA]->(:L1System {system_kind:'RESTApi'}) RETURN count(r) AS c") == 1
    assumption = session.run("MATCH (:L1Service {project_id:$p})-[r:CONSUMES]->() RETURN r.assumption AS a", p=project).single()["a"]
    assert assumption and "authorized" in assumption  # assumption predicate on CONSUMES
    assert c("MATCH (:L1DataItem {project_id:$p})-[r:SURFACES_AT]->() RETURN count(r) AS c") == 1
    # independent SPA + CSR props on the WebPresentation System the service is
    # EXPOSED_VIA (the mechanism-as-System correction) - NOT stranded as Service props
    wp = session.run("MATCH (:L1Service {project_id:$p, business_function_slug:'sales-analysis'})"
                     "-[:EXPOSED_VIA]->(w:L1System {project_id:$p, system_kind:'WebPresentation'}) "
                     "RETURN w.navigation_model AS nav, w.rendering_model AS ren", p=project).single()
    assert wp["nav"] == "SPA" and wp["ren"] == "CSR"  # independent props on the WebPresentation
    svc = session.run("MATCH (s:L1Service {project_id:$p, business_function_slug:'sales-analysis'}) "
                      "RETURN s.navigation_model AS nav, s.rendering_model AS ren", p=project).single()
    assert svc["nav"] is None and svc["ren"] is None  # never stranded on the Service
    # AUTHORIZED_BY{role} + AUTHENTICATED_BY{realm}
    roles = {r["role"] for r in session.run("MATCH (:L1Service {project_id:$p})-[r:AUTHORIZED_BY]->() RETURN r.role AS role", p=project)}
    realms = {r["realm"] for r in session.run("MATCH (:L1Service {project_id:$p})-[r:AUTHENTICATED_BY]->() RETURN r.realm AS realm", p=project)}
    assert roles == {"seller", "seller-admin"} and realms == {"credential", "idp"}
    # sweeps: /healthz in the stale pool; missing kinds derivable
    stale_paths = {row["path"] for row in sweep.stale_pool(project, read_fn=read_fn)}
    assert "/healthz" in stale_paths
    assert isinstance(sweep.missing_system_kinds(project, read_fn=read_fn), list)
    # index-card is token-light: edge-degree, no raw member payload leaked
    cards = index_card.index_cards(project, read_fn=read_fn)
    sales_card = next(c for c in cards if c.get("key", {}).get("business_function_slug") == "sales-analysis")
    assert sales_card["edge_degree"].get("AGGREGATES") == 2  # a COUNT, not the member set
    import json
    blob = json.dumps(sales_card)
    assert "/sellers/" not in blob and BASEURL not in blob  # no member node data in the card


# --- AST-NFR-07: MVP fence - deferred primitives are absent ---

def test_deferred_primitives_absent(session, project):
    _run_walkthrough(session, project)
    # SystemAspect (NM-3, DFS-up reification) is NOT built: no such label anywhere
    aspects = session.run("MATCH (n:SystemAspect) RETURN count(n) AS c").single()["c"]
    assert aspects == 0
    # no Stage-3 signature / risk-scoring module on the L1 path
    agent_root = Path(__file__).resolve().parents[2] / "agent" / "recon" / "analysis"
    names = {p.name for p in agent_root.glob("*.py")}
    assert not (names & {"signatures.py", "risk.py", "prefilter.py", "stage3.py"})
    # the ordered inter-System ON_REQUEST_PATH chain (AMV-7) is deferred: none written
    chain = session.run("MATCH (:L1System {project_id:$p})-[r:ON_REQUEST_PATH]->() RETURN count(r) AS c", p=project).single()["c"]
    assert chain == 0
