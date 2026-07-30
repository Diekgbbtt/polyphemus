"""FR-PODSTREAM integration tier — re-delivery is idempotent (AST-PODSTREAM-04).

Delivery is at-least-once across runs (each analyser pull re-reads the whole
graph). This proves that re-delivering the same asset+observation set through the
real l1_curator into live Neo4j MERGE-dedups: a second identical run yields no
duplicate L1 nodes/edges (L1D-22). The LLM invocations are mocked (fixed canned
proposals); the point under test is delivery + idempotent write, not the LLM.

REWIRED (#48 section 11 step 6, ratified 2026-07-30): the legacy
`build_analyser_graph(read_fn=..., analyse_fn=..., curate_fn=...)` seam is
retired along with the legacy pod. This now redelivers the same observation
through the real `run_analyser` (driving the supervised chunk-fed
`supervisor.run_analyser_chunked`) TWICE and asserts the second delivery adds
nothing new: the same dedup-by-id guarantee `delivery.collect_observations`
proves in isolation (`tests/analysis/test_delivery.py`), now exercised
end-to-end against live Neo4j through `run_analyser`'s `deliver_fn` seam. Since
#34 D4 retired Service minting from the Assigner, the owning Service is
pre-seeded here exactly as the Bootstrapper would leave it.
"""
import subprocess
import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.recon.domain import curator
from polymerhus.analysis import delivery
from polymerhus.analysis import l0_stream
from polymerhus.analysis.analyser_types import AggregatesProposal, L1DeltaBatch
from polymerhus.analysis.pod import run_analyser
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta, Observation
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
        pytest.skip(f"neo4j not reachable for delivery integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "deliv_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


SLUG = "orders"


def _seed_surface(session, project):
    """Curate one Endpoint asset + one Observation anchored to it (L0), and the
    owning Service pre-seeded (the Bootstrapper's leavings, #34 D4)."""
    endpoint_id = {"path": "/api/Orders", "method": "GET", "baseurl": "https://a"}
    l0_cy, l0_params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity=dict(endpoint_id), props={"status_code": 200})
    )
    l0_params["project_id"] = project
    session.run(l0_cy, **l0_params).consume()

    session.run(
        "MERGE (:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $p})",
        slug=SLUG, p=project,
    )

    obs = Observation(
        macro_kind="reflected_input", severity="medium", evidence="q=<script>",
        rationale="reflects unsanitised input", source_job="arjun", source_tool="arjun",
        anchor={"type": "Endpoint", "identity": dict(endpoint_id)},
    )
    obs_cy, obs_params = curator.build_observation_cypher(obs)
    obs_params["project_id"] = project
    session.run(obs_cy, **obs_params).consume()
    return endpoint_id


def _typist_invoke(messages, *, schema=None):
    # Deliberately empty: `mechanism_typist_body`'s own inventory/aggregations
    # collaborators are NOT threaded through `analyse_chunked` (a known gap,
    # unrelated to this test - see test_analyser_pod_merge.py's identical note).
    return None if schema is None else L1DeltaBatch()


def _data_modeller_invoke(messages, *, schema=None):
    # no Parameter/Header surface is admitted in this fixture; a legitimate empty.
    return "" if schema is None else L1DeltaBatch()


def test_redelivery_is_idempotent(session, project):
    endpoint_id = _seed_surface(session, project)

    # delivery reads the real graph via the test session (correct auth)
    def sess_read(cy, params):
        return [r.data() for r in session.run(cy, **params)]

    # every delivered observation reaches the analyser exactly once (id-deduped) -
    # `delivery.collect_observations`'s own dedup-by-id guarantee, proven directly
    # (unit-proven in isolation by tests/analysis/test_delivery.py; proven here
    # against a live graph too, since this file's whole subject is live delivery).
    delivered = delivery.collect_observations(project, read_fn=sess_read)
    assert len(delivered) == 1 and delivered[0]["macro_kind"] == "reflected_input"

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

    def assigner_invoke(messages):
        return L1DeltaBatch(aggregates=[AggregatesProposal(
            service_slug=SLUG, confidence=0.9,
            l0=L0Ref(label="Endpoint", identity=dict(endpoint_id)),
        )])

    inventory = {
        "services": [SLUG], "systems": [], "data_items": [],
        "service_contracts": {}, "system_descriptions": {},
        "data_item_fields": {}, "data_item_notes": {},
    }

    # run the analyser TWICE with auto-delivery (observations=None) over the SAME
    # underlying graph - the second pass re-reads the same one Observation.
    # `run_analyser`'s production `deliver_fn` default is `l0_stream.read_observations`
    # (anchor-carrying, what the supervised path's own chunk builder needs -
    # `delivery.collect_observations`'s dict shape drops the anchor and cannot
    # feed chunking, proven above in isolation instead), so that is what is wired
    # here too, over the SAME test session.
    for _ in range(2):
        export = run_analyser(
            project, "run-1",
            deliver_fn=lambda pid: l0_stream.read_observations(pid, read_fn=sess_read),
            invoke_fn=assigner_invoke, typist_invoke_fn=_typist_invoke,
            data_modeller_invoke_fn=_data_modeller_invoke,
            assets_fn=lambda pid: [AssetDelta(type="Endpoint", identity=dict(endpoint_id))],
            inventory_fn=lambda pid: inventory,
            aggregations_fn=lambda pid: [],
            write_fn=write_fn, checkpointer=MemorySaver(), observe=False,
        )
        assert export.error is None

    def _count(q):
        return session.run(q, p=project).single()["c"]

    # idempotent: one Service (pre-seeded, never re-minted), one Endpoint, one
    # AGGREGATES edge, one Observation - the second delivery adds nothing new.
    assert _count("MATCH (n:L1Service {project_id:$p}) RETURN count(n) AS c") == 1
    assert _count("MATCH (n:Observation {project_id:$p}) RETURN count(n) AS c") == 1
    assert _count("MATCH (:L1Service {project_id:$p})-[r:AGGREGATES]->(:Endpoint) RETURN count(r) AS c") == 1
