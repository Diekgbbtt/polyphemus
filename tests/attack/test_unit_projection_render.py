"""Unit tier: the coherent Markdown renderer for one unit projection.

The renderer shows every analysis unit, every endpoint under its service, every
parameter under its endpoint, and one deduplicated header list per baseURL. It
never cuts an endpoint.
"""
from polymerhus.attack.hunting.unit_projection import (
    AggregatedEndpoint,
    HeaderInfo,
    ParameterInfo,
    SystemInfo,
    UnitProjection,
)
from polymerhus.attack.hunting.unit_projection_render import render_unit_projection


def _system(slug, contract):
    return SystemInfo(
        kind="Service",
        discriminator=slug,
        exposure="public",
        description=None,
        props={"business_function_slug": slug, "service_contract": contract},
    )


def test_render_puts_endpoints_under_their_service_and_headers_under_the_baseurl():
    projection = UnitProjection(
        unit_id="RESTApi:api",
        kind="RESTApi",
        spine={},
        edges={},
        data_edges={},
        data_rel_kinds=frozenset(),
        cooperating_systems={
            "EXPOSED_VIA": (
                _system("library-catalog", "Owns the public catalogue."),
                _system("user-administration", "Administers the account roster."),
            ),
        },
        aggregated_endpoints=(
            AggregatedEndpoint(method="GET", path="/api/library",
                               baseurl="http://t", service_slug="library-catalog"),
            AggregatedEndpoint(method="GET", path="/api/admin/user",
                               baseurl="http://t", service_slug="user-administration",
                               parameters=(ParameterInfo(name="username",
                                                         position="body"),)),
        ),
        baseurl_headers={
            "http://t": (
                HeaderInfo(name="server", value="nginx", direction="response"),
                HeaderInfo(name="vary", value="accept-encoding",
                           direction="response"),
            ),
        },
    )

    rendered = render_unit_projection(projection)

    assert "### Service: library-catalog" in rendered
    assert "Owns the public catalogue." in rendered
    assert "GET /api/library" in rendered
    assert "### Service: user-administration" in rendered
    assert "GET /api/admin/user" in rendered
    assert "username (body)" in rendered
    assert "#### BaseURL http://t" in rendered
    assert rendered.count("server: nginx") == 1
    assert "vary: accept-encoding" in rendered


def test_render_never_cuts_an_endpoint():
    endpoints = tuple(
        AggregatedEndpoint(method="GET", path=f"/api/{i}", baseurl="http://t",
                           service_slug="svc")
        for i in range(60)
    )
    projection = UnitProjection(
        unit_id="Service:svc",
        kind="Service",
        spine={},
        edges={},
        data_edges={},
        data_rel_kinds=frozenset(),
        aggregated_endpoints=endpoints,
    )

    rendered = render_unit_projection(projection)

    assert "GET /api/0" in rendered
    assert "GET /api/59" in rendered
    assert "..." not in rendered


def test_render_shows_orphan_endpoints_on_a_system_unit():
    projection = UnitProjection(
        unit_id="RESTApi:api",
        kind="RESTApi",
        spine={},
        edges={},
        data_edges={},
        data_rel_kinds=frozenset(),
        cooperating_systems={
            "EXPOSED_VIA": (_system("library-catalog", "Owns the catalogue."),),
        },
        aggregated_endpoints=(
            AggregatedEndpoint(method="GET", path="/api/library",
                               baseurl="http://t", service_slug="library-catalog"),
            AggregatedEndpoint(method="GET", path="/api/orphan",
                               baseurl="http://t", service_slug=None),
        ),
    )

    rendered = render_unit_projection(projection)

    assert "### Endpoints without a cooperating service" in rendered
    assert "GET /api/orphan" in rendered


def test_render_says_none_observed_when_parameters_are_absent():
    projection = UnitProjection(
        unit_id="Service:svc",
        kind="Service",
        spine={},
        edges={},
        data_edges={},
        data_rel_kinds=frozenset(),
        aggregated_endpoints=(
            AggregatedEndpoint(method="GET", path="/api/a", baseurl="http://t"),
        ),
    )

    rendered = render_unit_projection(projection)

    assert "Parameters: none observed" in rendered
