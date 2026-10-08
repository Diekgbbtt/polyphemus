"""Scope descriptor parsing (forward decision D14 / D11 / D-SEEDNORM)."""
from polymerhus.recon.control.scope import (
    DISCOVERY_JOBS,
    parse_scope,
    seed_probe_target,
)


def test_bare_apex_is_exact_host():
    assert parse_scope("example.com") == {
        "apex": "example.com",
        "seed_host": "example.com",
        "mode": "exact",
    }


def test_subdomain_is_exact_host_with_registrable_apex():
    assert parse_scope("app.example.com") == {
        "apex": "example.com",
        "seed_host": "app.example.com",
        "mode": "exact",
    }


def test_wildcard_is_zone_scope_apex_seeded():
    # Wildcard = whole zone in scope; the apex itself is still the seed host so
    # its own web origin is probed alongside discovered subdomains (D11).
    assert parse_scope("*.example.com") == {
        "apex": "example.com",
        "seed_host": "example.com",
        "mode": "wildcard",
    }


def test_normalizes_case_whitespace_and_trailing_dot():
    assert parse_scope("  APP.Example.COM.  ") == {
        "apex": "example.com",
        "seed_host": "app.example.com",
        "mode": "exact",
    }


def test_empty_or_none_falls_back_to_placeholder_exact():
    for value in (None, "", "   "):
        assert parse_scope(value) == {
            "apex": "example.com",
            "seed_host": "example.com",
            "mode": "exact",
        }


def test_bare_wildcard_falls_back_to_placeholder_apex():
    assert parse_scope("*.") == {
        "apex": "example.com",
        "seed_host": "example.com",
        "mode": "wildcard",
    }


def test_discovery_jobs_gate_excludes_takeover_and_passive():
    # The scope gate suppresses subdomain ENUMERATION only.
    assert DISCOVERY_JOBS == {"subfinder", "amass", "puredns", "dnsx"}
    assert "subdomain_takeover" not in DISCOVERY_JOBS
    assert "whois" not in DISCOVERY_JOBS
    assert "gau" not in DISCOVERY_JOBS
    assert "paramspider" not in DISCOVERY_JOBS


def test_parse_scope_strips_leading_www():
    # www.<x> seeds the same scope as <x>, exact or wildcard.
    assert parse_scope("www.example.com") == {
        "apex": "example.com", "seed_host": "example.com", "mode": "exact"}
    assert parse_scope("*.www.example.com")["seed_host"] == "example.com"
    # a non-leading www label is untouched.
    assert parse_scope("wwwize.example.com")["seed_host"] == "wwwize.example.com"


def test_parse_scope_strips_scheme_and_port_to_bare_host():
    # D-SEEDNORM: a Seed may carry a scheme and/or port; the scope keys on the
    # bare host so the gate's host comparison and the graph root identity are a
    # hostname, never a URL. The probe target keeps the authority separately.
    assert parse_scope("http://app.example.com:8443") == {
        "apex": "example.com", "seed_host": "app.example.com", "mode": "exact"}
    assert parse_scope("APP.Example.COM:8443") == {
        "apex": "example.com", "seed_host": "app.example.com", "mode": "exact"}
    assert parse_scope("https://app.example.com/path?q=1") == {
        "apex": "example.com", "seed_host": "app.example.com", "mode": "exact"}


def test_parse_scope_authority_bearing_ip_is_host_mode():
    # D-SEEDNORM: a scheme/port-bearing IPv4 is still a bare-IP seed - host mode,
    # the IP as both apex and seed host, no registrable-apex math.
    assert parse_scope("http://1.2.3.4:8080") == {
        "apex": "1.2.3.4", "seed_host": "1.2.3.4", "mode": "host"}
    assert parse_scope("1.2.3.4:8080") == {
        "apex": "1.2.3.4", "seed_host": "1.2.3.4", "mode": "host"}


def test_seed_probe_target_preserves_authority():
    # The probe target is what the Subdomain-consuming probes receive; it keeps
    # the scheme and port so the probe reaches the seeded service, while the
    # host is normalized to match parse_scope's seed_host.
    assert seed_probe_target("http://app.example.com:8443") == "http://app.example.com:8443"
    assert seed_probe_target("app.example.com:8443") == "app.example.com:8443"
    assert seed_probe_target("APP.Example.COM:8443") == "app.example.com:8443"
    assert seed_probe_target("https://app.example.com") == "https://app.example.com"
    assert seed_probe_target("app.example.com") == "app.example.com"
    # wildcard/www fold to the apex probe target, mirroring parse_scope.
    assert seed_probe_target("*.example.com") == "example.com"
    assert seed_probe_target("*.example.com:8443") == "example.com:8443"
    assert seed_probe_target("www.example.com") == "example.com"
    assert seed_probe_target(None) == ""


def test_scheme_port_seed_admits_its_own_minted_assets():
    # #184 full parse_scope -> scope-gate path: a scheme/port seed admits the
    # BaseURL its own probe mints and still drops a sibling host.
    from polymerhus.recon.domain.noise_filter import filter_deltas
    from polymerhus.recon.domain.types import AssetDelta

    scope = parse_scope("http://app.example.com:8443")
    own = AssetDelta(type="BaseURL", identity={"url": "http://app.example.com:8443"})
    sibling = AssetDelta(type="BaseURL", identity={"url": "https://api.example.com"})
    kept = filter_deltas([own, sibling], scope_domain=scope["seed_host"])
    assert own in kept
    assert sibling not in kept
