"""FR-JOURNEY unit tier - the light-membership read helper with an injected
read_fn (no live DB).

Journey membership is a LIGHT prop: each `L1Service` carries `journeys: list[str]`
naming the business journeys it participates in (plan §1). "Services in the same
journey" is then a single property-match query - no `Journey` node, no order, no
schema migration. `services_in_journey` is the read side of that model; assignment
is the curation pass (out of this area's scope).
"""
from agent.recon.analysis import l1_read


# A small in-memory service set the fake read_fn filters over, so the test
# genuinely exercises the params the helper passes ($p / $j) rather than a
# canned row list - members sharing a journey must come back, non-members must not.
_SERVICES = [
    {"business_function_slug": "cart", "project_id": "proj-1", "journeys": ["checkout-flow"]},
    {"business_function_slug": "checkout", "project_id": "proj-1", "journeys": ["checkout-flow", "signup-flow"]},
    {"business_function_slug": "payment", "project_id": "proj-1", "journeys": ["checkout-flow"]},
    {"business_function_slug": "signup", "project_id": "proj-1", "journeys": ["signup-flow"]},
    {"business_function_slug": "healthz", "project_id": "proj-1", "journeys": []},
    # same journey slug, DIFFERENT project - must be scoped out by $p.
    {"business_function_slug": "other-cart", "project_id": "proj-2", "journeys": ["checkout-flow"]},
]


def _fake_read_from_services(services):
    """A minimal Cypher stand-in that applies `s.project_id = $p AND $j IN s.journeys`
    over `services`, returning `slug` rows exactly as the aliased RETURN would."""

    def fake_read(cy, params):
        p = params["p"]
        j = params["j"]
        return [
            {"slug": s["business_function_slug"]}
            for s in services
            if s["project_id"] == p and j in s["journeys"]
        ]

    return fake_read


def test_services_in_journey_returns_members():
    fake_read = _fake_read_from_services(_SERVICES)

    members = l1_read.services_in_journey("proj-1", "checkout-flow", read_fn=fake_read)

    # every proj-1 service whose journeys contains the slug, sorted, and nothing else.
    assert members == ["cart", "checkout", "payment"]
    # a non-member (empty journeys) and a same-slug service in another project are excluded.
    assert "healthz" not in members
    assert "other-cart" not in members

    # a service can belong to more than one journey - the signup group overlaps checkout on `checkout`.
    signup = l1_read.services_in_journey("proj-1", "signup-flow", read_fn=fake_read)
    assert signup == ["checkout", "signup"]

    # an unknown journey slug yields no members (not an error).
    assert l1_read.services_in_journey("proj-1", "no-such-flow", read_fn=fake_read) == []


def test_journey_prop_does_not_change_identity():
    """identity ⊥ membership (L1D-11): reading journey membership must never key on
    the member set. The helper filters on `journeys` (membership, a queryable prop)
    but returns `business_function_slug` (the Service identity) - so setting/removing
    a journey is a prop write that never churns identity. Verified via the query shape."""
    captured = {}

    def fake_read(cy, params):
        captured["cy"] = cy
        captured["params"] = params
        return []

    l1_read.services_in_journey("proj-1", "checkout-flow", read_fn=fake_read)

    cy = captured["cy"]
    # membership (`journeys`) appears ONLY as a WHERE filter, never as the returned key.
    assert "MATCH (s:L1Service)" in cy
    assert "$j IN s.journeys" in cy
    # the RETURN projects the IDENTITY key, not the membership set.
    return_clause = cy.split("RETURN", 1)[1]
    assert "business_function_slug" in return_clause
    assert "journeys" not in return_clause
    # the journey slug is a bound parameter, not string-interpolated into the query.
    assert captured["params"] == {"p": "proj-1", "j": "checkout-flow"}
    assert "checkout-flow" not in cy


def test_read_error_is_fail_open():
    def boom(cy, params):
        raise RuntimeError("neo4j is down")

    # a read error degrades to an empty list, never crashes the caller (fail-open).
    assert l1_read.services_in_journey("proj-1", "checkout-flow", read_fn=boom) == []
