"""Walkthrough predicates (e2e tier) for the Bootstrapper redesign (#26, agent
spec #7). Mechanises E1-E3.

Injected reason_fn/extract_fn/curate_fn (no live LLM/DB); a capturing curate_fn
exposes the exact deltas for the terminal-quantity assertions. Written BEFORE the
build - red on NotImplementedError until the path is filled, then green. Expected
values from the spec. Verifier-gated.
"""
from polymerhus.analysis.bootstrap import (
    ServiceShell,
    SystemShell,
    bootstrap_reasoned,
)

_LINCHPINS = {"IdentificationSystem", "AuthenticationMechanism", "AuthorizationSystem"}


# --- E1: a non-ecommerce KB -> grounded skeleton, one withheld, linchpins, authz ---

def test_E1_logistics_kb_grounded_skeleton():
    # The operator KB describes a B2B logistics tooling architecture. It says nothing
    # about billing; the reasoning WITHHOLDS billing. reason_fn/extract_fn stand in
    # for the two LLM calls (their content is the spec's independent source of truth).
    kb = ("Internal logistics tooling: a public shipment-tracking status page; an "
          "authenticated carrier-rate management console; an authenticated fleet-admin "
          "console. Roles: anonymous, operator, fleet-admin. Runs behind Cloudflare.")

    def reason(operator_kb, service_slugs):
        return "5-step reasoning grounding tracking/rates/fleet-admin; billing withheld (no KB support)"

    def extract(reasoning):
        services = [
            ServiceShell(business_function_slug="shipment-tracking", exposure="public"),
            ServiceShell(business_function_slug="carrier-rates", exposure="authenticated"),
            ServiceShell(business_function_slug="fleet-admin", exposure="authenticated"),
        ]
        systems = [
            SystemShell(kind="WAF", claim="KB: runs behind Cloudflare"),
            SystemShell(kind="AuthorizationSystem",
                        roles=["anonymous", "operator", "fleet-admin"], realms=["web"]),
        ]
        return services, systems

    captured = {}

    def curate(services, systems, project_id):
        captured["services"] = services
        captured["systems"] = systems
        return len(services), len(systems)

    out = bootstrap_reasoned("p1", kb, run_id="r1", reason_fn=reason, extract_fn=extract, curate_fn=curate)

    assert out.blocked is False
    svc = {s.business_function_slug: s.props for s in captured["services"]}
    assert set(svc) == {"shipment-tracking", "carrier-rates", "fleet-admin"}  # billing withheld
    assert svc["shipment-tracking"] == {"exposure": "public"}
    assert svc["carrier-rates"] == {"exposure": "authenticated"}
    assert svc["fleet-admin"] == {"exposure": "authenticated"}
    assert all("label" not in p and "salience" not in p for p in svc.values())
    # no ecommerce slug leaked from the old hardcoded list
    assert not ({"checkout", "cart", "orders", "reviews"} & set(svc))

    sys_kinds = {s.kind for s in captured["systems"]}
    assert _LINCHPINS <= sys_kinds        # 3 linchpins forced
    assert "WAF" in sys_kinds             # claim-based shallow stub present
    authz = next(s for s in captured["systems"] if s.kind == "AuthorizationSystem")
    assert authz.props.get("roles") == ["anonymous", "operator", "fleet-admin"]


# --- E2: empty KB -> linchpins-only, not blocked ------------------------------

def test_E2_empty_kb_minimal_skeleton_proceeds():
    out = bootstrap_reasoned(
        "p1", "", reason_fn=lambda kb, service_slugs: "unused",
        extract_fn=lambda r: ([], []),
        curate_fn=lambda services, systems, p: (len(services), len(systems)),
    )
    assert out.blocked is False
    assert out.services_written == 0
    assert out.systems_written == 3


# --- E3: fail-closed halts the analysis ---------------------------------------

def test_E3_call2_exhaustion_blocks_nothing_written():
    writes = {"n": 0}

    def curate(services, systems, project_id):
        writes["n"] += 1
        return len(services), len(systems)

    out = bootstrap_reasoned(
        "p1", "a non-empty KB", reason_fn=lambda kb, service_slugs: "reasoning",
        extract_fn=lambda r: None,  # extract exhausts
        curate_fn=curate,
    )
    assert out.blocked is True
    assert out.services_written == 0 and out.systems_written == 0
    assert writes["n"] == 0  # nothing written to the graph
