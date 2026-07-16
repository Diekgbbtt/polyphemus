"""FR-TEMPLATE unit tier — the endpoint-template derivation (L1D-32 / door D5)
and its wiring onto the AGGREGATES edge at assignment.
"""
from agent.recon.analysis import l1_curator
from agent.recon.analysis.l1_types import (
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
)

PROV = Provenance(job="analyser:run-1", model="m", prompt_id="p")
ENV = JudgmentEnvelope(confidence=0.8, status="committed", evidence_refs=["o"], provenance=PROV)


# --- the pure derivation: numeric + uuid segments -> {id} ---

def test_numeric_segment_templated():
    assert l1_curator.endpoint_template("/api/Products/12") == "/api/Products/{id}"
    assert l1_curator.endpoint_template("/categories/5/parameters") == "/categories/{id}/parameters"


def test_uuid_segment_templated():
    assert l1_curator.endpoint_template(
        "/users/550e8400-e29b-41d4-a716-446655440000"
    ) == "/users/{id}"


def test_multiple_id_segments_templated():
    assert l1_curator.endpoint_template("/sellers/3/products/47") == "/sellers/{id}/products/{id}"


def test_no_id_segment_unchanged():
    assert l1_curator.endpoint_template("/api/Products") == "/api/Products"
    assert l1_curator.endpoint_template("/rest/user/whoami") == "/rest/user/whoami"


def test_template_is_idempotent():
    once = l1_curator.endpoint_template("/api/Products/12")
    assert l1_curator.endpoint_template(once) == once  # re-templating a template is a no-op


def test_non_numeric_word_not_templated():
    # a word that merely contains digits is not an id segment
    assert l1_curator.endpoint_template("/2fa/enter") == "/2fa/enter"
    assert l1_curator.endpoint_template("/v2/api") == "/v2/api"


def test_empty_and_malformed_pass_through():
    assert l1_curator.endpoint_template("") == ""
    assert l1_curator.endpoint_template(None) is None  # type: ignore


# --- wiring: the key is set on the AGGREGATES edge for Endpoint targets only ---

def test_aggregates_edge_carries_endpoint_template():
    d = AggregatesDelta(
        service_slug="product-introspection",
        l0=L0Ref(label="Endpoint", identity={"path": "/api/Products/12", "method": "GET", "baseurl": "https://a"}),
        envelope=ENV,
    )
    cy, params = l1_curator.build_aggregates_cypher(d)
    assert "SET r.endpoint_template = $endpoint_template" in cy
    assert params["endpoint_template"] == "/api/Products/{id}"


def test_non_endpoint_aggregate_has_no_template():
    d = AggregatesDelta(
        service_slug="s",
        l0=L0Ref(label="BaseURL", identity={"url": "https://a"}),
        envelope=ENV,
    )
    cy, params = l1_curator.build_aggregates_cypher(d)
    assert "endpoint_template" not in cy  # only Endpoint targets carry the key
    assert "endpoint_template" not in params


def test_two_instance_endpoints_share_one_template_key():
    a = AggregatesDelta(service_slug="s", l0=L0Ref(label="Endpoint", identity={"path": "/sellers/1/sales", "method": "GET", "baseurl": "https://a"}), envelope=ENV)
    b = AggregatesDelta(service_slug="s", l0=L0Ref(label="Endpoint", identity={"path": "/sellers/2/sales", "method": "GET", "baseurl": "https://a"}), envelope=ENV)
    _, pa = l1_curator.build_aggregates_cypher(a)
    _, pb = l1_curator.build_aggregates_cypher(b)
    assert pa["endpoint_template"] == pb["endpoint_template"] == "/sellers/{id}/sales"
