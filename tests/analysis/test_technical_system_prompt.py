"""Arm M E1 and E3: the mechanism-typist prompt links Systems and shapes their descriptions.

The prompt is the role prefix for the extraction call.
E1 adds the services-to-systems linking section and the two-service Example 6; without it the M4 `AUTHORIZED_BY` items stay missing.
E3 adds the authorization description primitives to the general rule and extends Example 6 with them.
"""

from polymerhus.analysis.mechanism_typist import _load_skill


def test_prompt_links_each_system_to_its_services() -> None:
    prompt = _load_skill()

    assert "## Link each System to its Services" in prompt
    assert "system_edges:" in prompt
    assert "service_slug: admin" in prompt
    assert "anonymous-allowed routes" in prompt
    assert "account-creation Service" in prompt
    assert "one edge per (service, System) pair" in prompt
    assert "never duplicate" in prompt.lower()


def test_example_six_shows_the_full_route_chain_and_the_edge() -> None:
    prompt = _load_skill()

    assert "full route chain" in prompt
    assert "GET /api/admin/users" in prompt
    assert "403" in prompt
    assert "AUTHORIZED_BY" in prompt
    assert "service_slug: account-registration" in prompt
    assert "mints the accounts" in prompt
    assert "Stop at existence + linkage" in prompt


def test_authorization_system_description_requires_the_observed_primitives() -> None:
    prompt = _load_skill()

    assert "An `AuthorizationSystem` description carries the observed primitives" in prompt
    assert "identification material" in prompt
    assert "Authorization` header or JWT" in prompt
    assert "every request-payload parameter" in prompt
    assert "named literally" in prompt
    assert "Name EVERY observed carrier" in prompt
    assert "authenticated principal" in prompt
    assert "mere presence of the carrier" in prompt
    assert "privilege level" in prompt
    assert "role vocabulary" in prompt
    assert "302 redirect" in prompt
    assert "not just `302`" in prompt
    assert "breadth of the protected surface" in prompt
    assert "per-route" in prompt
    assert "directly reachable" in prompt
    assert "name the request parameter that carries it" in prompt
    assert "trust-agreement semantics" in prompt
    assert "at most three sentences" in prompt
    assert "never every route" in prompt
    assert "bounded READ-ONLY probe" in prompt
    assert "never extensive probing" in prompt
    assert "never a hierarchy dump" in prompt
    assert "full primitive coverage is a later threat-modelling phase" in prompt


def test_example_six_extends_the_description_with_the_authorization_primitives() -> None:
    prompt = _load_skill()

    assert "session cookie names the principal" in prompt
    assert "account name (`username`)" in prompt
    assert "302 redirect" in prompt
    assert "per-route over `/api/admin/*`" in prompt
    assert "logs the attacker-controlled principal" in prompt
    assert "from the `username` request parameter" in prompt
    assert "observed roles are `admin` and `user`" in prompt
