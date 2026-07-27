"""FR-ELICIT integration tier — bootstrap writing the real L1 skeleton into live
Neo4j (services + linchpin auth Systems, NO AGGREGATES), idempotent, and the
bootstrap->assignment flow (an elicited Service later receives an AGGREGATES edge
from the analyser). Elicitation is mocked (canned batch) for the LLM.
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.recon.domain import curator
from polymerhus.analysis import bootstrap, l1_curator
from polymerhus.analysis.l1_types import (
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
)
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
        pytest.skip(f"neo4j not reachable for bootstrap integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "boot_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _mf(session):
    return lambda cy, params: session.run(cy, **params).consume()


def _count(session, label, pid, **props):
    where = " AND ".join(f"n.{k} = ${k}" for k in props)
    q = f"MATCH (n:{label}) WHERE n.project_id = $p" + (f" AND {where}" if props else "") + " RETURN count(n) AS c"
    return session.run(q, p=pid, **props).single()["c"]


# The canned call-2 extraction, standing in for the two LLM calls (#29: the
# superseded single-call `elicit_fn` path is retired, so these exercise the
# reasoned path's collaborators). Each Service carries its `service_contract`.
_CANNED_SHELLS = (
    [
        bootstrap.ServiceShell(
            business_function_slug="checkout", exposure="authenticated",
            service_contract="Take a basket to a paid order; owns the order record. "
                             "Deals in baskets, orders, payment and confirmation.",
        ),
        bootstrap.ServiceShell(
            business_function_slug="product-introspection", exposure="public",
            service_contract="Browse and inspect the products on sale; owns the product "
                             "listing. Deals in products, categories and search.",
        ),
    ],
    [bootstrap.SystemShell(kind="RESTApi")],
)


def _canned_reason(operator_kb, service_slugs):
    return "canned reasoning"


def _canned_extract(reasoning):
    return _CANNED_SHELLS


def _bootstrap(project, session, **kwargs):
    return bootstrap.bootstrap_reasoned(
        project, kwargs.pop("kb", "kb"),
        reason_fn=_canned_reason, extract_fn=_canned_extract,
        curate_fn=_session_curate(session), service_slugs=[], **kwargs,
    )


def _session_curate(session):
    def curate_fn(services, systems, project_id):
        return l1_curator.l1_curate(services, systems, project_id, merge_fn=_mf(session))
    return curate_fn


def _prop(session, pid, slug, key):
    row = session.run(
        f"MATCH (n:L1Service) WHERE n.project_id = $p AND n.business_function_slug = $s "
        f"RETURN n.{key} AS v", p=pid, s=slug,
    ).single()
    return row and row["v"]


# --- AST-ELICIT-01/02/03: skeleton written, linchpins present, NO AGGREGATES ---

def test_bootstrap_writes_skeleton_with_no_l0_refs(session, project):
    export = _bootstrap(project, session, kb="marketplace with checkout and product introspection")
    assert export.blocked is False and export.error is None
    assert _count(session, "L1Service", project, business_function_slug="checkout") == 1
    assert _count(session, "L1Service", project, business_function_slug="product-introspection") == 1
    # the 3 linchpin auth-identity Systems present
    for kind in bootstrap._LINCHPIN_SYSTEMS:
        assert _count(session, "L1System", project, kind=kind) == 1
    # PURE business projection: no AGGREGATES edge exists anywhere for this project
    agg = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AGGREGATES]->() RETURN count(r) AS c", p=project,
    ).single()["c"]
    assert agg == 0


def test_service_contract_is_persisted_on_the_node(session, project):
    """#29: the contract is a free-form prop, so this is the check that it actually
    survives the sole-writer onto the node a later Assigner reads - the shaping tests
    only prove it reaches the curate boundary."""
    _bootstrap(project, session)
    assert _prop(session, project, "checkout", "service_contract").startswith("Take a basket")
    # a forced linchpin is never contract-less either
    assert _prop(session, project, "sign-in", "service_contract")
    # and the A.1 attributes are genuinely absent (not written empty)
    assert _prop(session, project, "checkout", "label") is None
    assert _prop(session, project, "checkout", "salience") is None


def test_re_bootstrap_does_not_clobber_a_contract_with_a_blank_one(session, project):
    """A weaker second pass (the model omits the contract) must leave the stored one
    standing: absence is omission, so the idempotent MERGE has nothing to overwrite
    it with."""
    _bootstrap(project, session)
    stored = _prop(session, project, "checkout", "service_contract")

    def contractless_extract(reasoning):
        return ([bootstrap.ServiceShell(business_function_slug="checkout", exposure="authenticated")], [])

    bootstrap.bootstrap_reasoned(
        project, "kb", reason_fn=_canned_reason, extract_fn=contractless_extract,
        curate_fn=_session_curate(session), service_slugs=[],
    )
    assert _prop(session, project, "checkout", "service_contract") == stored


def test_bootstrap_is_idempotent(session, project):
    for _ in range(2):
        _bootstrap(project, session)
    assert _count(session, "L1Service", project, business_function_slug="checkout") == 1
    for kind in bootstrap._LINCHPIN_SYSTEMS:
        assert _count(session, "L1System", project, kind=kind) == 1


# --- bootstrap -> assignment flow: an elicited Service receives an AGGREGATES edge ---

def test_elicited_service_can_receive_aggregates_assignment(session, project):
    mf = _mf(session)
    # bootstrap the skeleton (no L0 refs)
    _bootstrap(project, session)
    # recon lands an L0 endpoint
    endpoint_id = {"path": "/categories/{id}/parameters", "method": "GET", "baseurl": "https://a"}
    l0_cy, l0_params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity=dict(endpoint_id), props={"status_code": 200})
    )
    l0_params["project_id"] = project
    session.run(l0_cy, **l0_params).consume()
    # assignment: the analyser attaches the endpoint to the elicited Service
    l1_curator.write_aggregates(
        [AggregatesDelta(
            service_slug="product-introspection",
            l0=L0Ref(label="Endpoint", identity=endpoint_id),
            envelope=JudgmentEnvelope(confidence=0.8, status="committed", evidence_refs=["obs"],
                                      provenance=Provenance(job="analyser:run-1")),
        )],
        project, merge_fn=mf,
    )
    # the elicited Service now has exactly one AGGREGATES edge to the L0 endpoint
    edges = session.run(
        "MATCH (:L1Service {project_id: $p, business_function_slug: 'product-introspection'})"
        "-[r:AGGREGATES]->(:Endpoint {project_id: $p}) RETURN count(r) AS c",
        p=project,
    ).single()["c"]
    assert edges == 1
