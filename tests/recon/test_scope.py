"""Scope descriptor parsing (forward decision D14 / D11)."""
from agent.recon.scope import DISCOVERY_JOBS, parse_scope


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
