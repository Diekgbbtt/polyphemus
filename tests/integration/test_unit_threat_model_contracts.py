"""Integration tier: the live L1 read seam and the frozen intake contract.

Catalogue: `docs/design/unit-threat-model-assertions.md` C20-C21 (the real
graph read feeding the ordering and the freeze).

The fixture is the white-jotter-001 ground-truth sample from
`/Users/diekgbbtt/.local/share/polymerhus/vuln-groundtruth/white-jotter/white-jotter-001`
(`l1-profile.md` + `l0-surface.yaml`): one public sign-in Service with the
Shiro authentication mechanism, the REST/WebPresentation exposure systems, a
credential consumed and a session produced, and four aggregated endpoints.

The test reads the L1 through the production `read_l1_inventory` seam - the
same read the run's `_run_intake` performs - then orders and freezes it. It
skips only when the shared Neo4j is unreachable (the repo's live-tier
convention); a reachable graph with the wrong order fails.
"""
from __future__ import annotations

import uuid

import pytest

from polymerhus.attack.hunting.unit_intake import order_intake, read_intake

PROJECT = f"utm-intake-{uuid.uuid4().hex[:8]}"

EXPECTED_ORDER = [
    "Service:account-sign-in",
    "AuthenticationMechanism",
    "RESTApi:account-sign-in::rest",
    "WebPresentation:account-sign-in::login-shell",
]


def _driver():
    from neo4j import GraphDatabase

    from tests.conftest import neo4j_target

    uri, auth = neo4j_target()
    return GraphDatabase.driver(uri, auth=auth)


@pytest.fixture(scope="module")
def live_graph():
    try:
        driver = _driver()
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 - live-tier skip
        pytest.skip(f"Neo4j unavailable: {exc}")
    from tests.e2e.unit_threat_model_stack import seed_white_jotter_l1

    seed_white_jotter_l1(PROJECT)
    try:
        yield driver
    finally:
        with driver.session() as session:
            session.run(
                "MATCH (n {project_id: $p}) DETACH DELETE n", p=PROJECT)
        driver.close()
        from polymerhus.app.clients import neo4j_client

        neo4j_client.close()


def test_white_jotter_ground_truth_intake_order(live_graph):
    """C20: the real L1 read orders the Service first by its three live L1
    edges; the three connected Systems tie on one edge and break by unit id.
    The Service aggregates the four ground-truth endpoints; every System's
    endpoint count is the distinct connected Services' aggregate (4)."""
    units = order_intake(read_intake(PROJECT))

    assert [unit.unit_id for unit in units] == EXPECTED_ORDER
    service = units[0]
    assert service.live_edge_count == 3
    assert service.endpoint_count == 4
    for system in units[1:]:
        assert system.live_edge_count == 1, system
        assert system.endpoint_count == 4, system


def test_intake_read_is_stable_across_repeats(live_graph):
    """C20/C21: the read and the order are pure over the persisted graph; a
    second read produces the same frozen unit set (no duplicate unit ids)."""
    first = order_intake(read_intake(PROJECT))
    second = order_intake(read_intake(PROJECT))
    assert [u.unit_id for u in first] == [u.unit_id for u in second]
    assert len({u.unit_id for u in second}) == len(second)
