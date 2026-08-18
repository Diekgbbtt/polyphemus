"""FR-ANALYSER integration tier — the analyser writing real L1 nodes via the
sanctioned l1_curator into a live Neo4j, with MOCKED LLM invocations standing in
for the provider. Proves AST-ANALYSER-01: the analyser is a pure
f(surface+context)->L1-deltas whose writes are idempotent MERGEs (running twice
yields one node/edge).

REWIRED (#48 section 11 step 6, ratified 2026-07-30): the legacy
`build_analyser_graph(read_fn=..., analyse_fn=..., curate_fn=...)` seam is
retired along with the legacy pod. This now runs the SUPERVISED chunk-fed path
(`run_analyser`, driving `supervisor.run_analyser_chunked`) twice against a live
Neo4j fixture and asserts the same node/edge counts hold after the second pass -
the same idempotent-MERGE guarantee, now exercised through the three-role
`assigner -> mechanism_typist -> data_modeller` schedule. Since #34 D4 retired
Service minting from the Assigner, the owning Service is pre-seeded here exactly
as the Bootstrapper would leave it, and the Assigner's fixed invoke_fn only
proposes an AGGREGATES judgment onto that pre-existing slug.
"""
import subprocess
import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.recon.domain import curator
from polymerhus.analysis.analyser_types import AggregatesProposal, L1DeltaBatch
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.pod import run_analyser
from polymerhus.recon.domain.types import AssetDelta
from tests.conftest import wait_for

from tests.conftest import neo4j_target

# Single source of truth (tests/conftest.py::neo4j_target): env-driven so this
# file works BOTH in-network (bolt://neo4j:7687) and from the host against the
# published port. Was a hardcoded localhost constant, which cannot resolve
# inside the Docker network.
URI, AUTH = neo4j_target()


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
        pytest.skip(f"neo4j not reachable for analyser integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "anlz_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


SLUG = "product-introspection"


def _assigner_invoke(endpoint_id):
    def invoke(messages):
        return L1DeltaBatch(aggregates=[AggregatesProposal(
            service_slug=SLUG, confidence=0.82, evidence_refs=["obs:cat"],
            l0=L0Ref(label="Endpoint", identity=dict(endpoint_id)),
        )])
    return invoke


def _typist_invoke(messages, *, schema=None):
    # Deliberately empty (reflection returns None -> bounded_retry exhausts ->
    # fail-CLOSED, no Systems): `mechanism_typist_body`'s own `read_inventory`/
    # `read_aggregations` collaborators are NOT threaded through
    # `analyse_chunked`'s `inventory_fn`/`aggregations_fn` (a known gap in the
    # typist's supervisor wiring, unrelated to this test), so it would otherwise
    # fall back to LIVE default reads against the real neo4j_client rather than
    # this test's session - the same reason `test_data_modeller_walkthrough.py`'s
    # E1 keeps this stub a deliberate no-op. This test's subject is the curator's
    # idempotent MERGE on the AGGREGATES path, not the typist.
    return None if schema is None else L1DeltaBatch()


def _data_modeller_invoke(messages, *, schema=None):
    # no Parameter/Header surface is admitted in this fixture, so both calls are
    # a legitimate empty (nothing to lift) - not the subject of this test.
    return "" if schema is None else L1DeltaBatch()


# --- AST-ANALYSER-01: pure f(surface+context)->L1-deltas, idempotent MERGE ----

def test_analyser_writes_l1_idempotently_via_curator(session, project):
    endpoint_id = {"path": "/categories/{id}/parameters", "method": "GET", "baseurl": "https://a"}

    # the Bootstrapper's leavings: the owning Service already exists before the
    # Assigner ever runs (#34 D4 - the Assigner never mints).
    session.run(
        "MERGE (:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $p})",
        slug=SLUG, p=project,
    )
    # recon precedes analysis: a real L0 Endpoint exists (AGGREGATES MATCHes it)
    l0_cy, l0_params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity=dict(endpoint_id), props={"status_code": 200})
    )
    l0_params["project_id"] = project
    session.run(l0_cy, **l0_params).consume()

    def merge_fn(cypher, params):
        params = dict(params)
        params["project_id"] = project
        session.run(cypher, params)

    def write_fn(deltas, pid, provenance):
        from polymerhus.analysis import l1_curator
        from polymerhus.analysis.analyser_types import enrichment_proposals_to_deltas, proposals_to_deltas
        from polymerhus.analysis.pod import AnalyserExport

        services, systems, aggregates = proposals_to_deltas(deltas, provenance)
        sw, syw = l1_curator.l1_curate(services, systems, project, merge_fn=merge_fn)
        aw = l1_curator.write_aggregates(aggregates, project, merge_fn=merge_fn)
        enrich_deltas = enrichment_proposals_to_deltas(deltas, provenance)
        counts = l1_curator.enrich(project, merge_fn=merge_fn, **enrich_deltas) if any(enrich_deltas.values()) else {}
        return AnalyserExport(services_written=sw, systems_written=syw, aggregates_written=aw, enrichment=counts)

    inventory = {
        "services": [SLUG], "systems": [], "data_items": [],
        "service_contracts": {}, "system_descriptions": {},
        "data_item_fields": {}, "data_item_notes": {},
    }

    for _ in range(2):  # run the supervised pass twice on the same input
        export = run_analyser(
            project, "run-1", observations=[],
            invoke_fn=_assigner_invoke(endpoint_id), typist_invoke_fn=_typist_invoke,
            data_modeller_invoke_fn=_data_modeller_invoke,
            assets_fn=lambda pid: [AssetDelta(type="Endpoint", identity=dict(endpoint_id))],
            inventory_fn=lambda pid: inventory,
            aggregations_fn=lambda pid: [],
            write_fn=write_fn, checkpointer=MemorySaver(), observe=False,
        )
        assert export.error is None

    def _count(label, **props):
        where = " AND ".join(f"n.{k} = ${k}" for k in props)
        q = f"MATCH (n:{label}) WHERE n.project_id = $p" + (f" AND {where}" if props else "") + " RETURN count(n) AS c"
        return session.run(q, p=project, **props).single()["c"]

    # idempotent: one Service (pre-seeded, never re-minted), one AGGREGATES edge
    # - no duplicates across the two passes.
    assert _count("L1Service", business_function_slug=SLUG) == 1
    edges = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AGGREGATES]->(:Endpoint {project_id: $p}) RETURN count(r) AS c",
        p=project,
    ).single()["c"]
    assert edges == 1
    # the AGGREGATES envelope carries the analyser's confidence + system provenance
    env = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AGGREGATES]->() RETURN r.confidence AS c, r.prov_job AS j",
        p=project,
    ).single()
    assert env["c"] == 0.82
    assert env["j"] == "analyser:run-1"
