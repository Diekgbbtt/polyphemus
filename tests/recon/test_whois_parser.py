# tests/recon/test_whois_parser.py
from pathlib import Path
from agent.recon.parsers import get_parser
from agent.recon.parsers.whois_parser import parse

WHOIS_FIX = Path(__file__).parent / "fixtures" / "whois.txt"


def test_registry_exposes_whois():
    assert get_parser("whois") is parse


def test_parse_whois_emits_single_domain_delta_with_props():
    deltas = parse(WHOIS_FIX.read_text())

    domains = [d for d in deltas if d.type == "Domain"]
    assert len(domains) == 1

    domain = domains[0]
    assert domain.identity == {"name": "example.com"}
    assert domain.props["registrar"] == "Example Registrar, LLC"
    assert domain.props["creation_date"] == "1995-08-14T04:00:00Z"
    assert domain.props["expiration_date"] == "2026-08-13T04:00:00Z"
    assert domain.props["updated_date"] == "2025-08-14T10:22:31Z"
    assert domain.props["name_servers"] == ["a.iana-servers.net", "b.iana-servers.net"]


def test_parse_whois_handles_expiration_date_variant():
    text = (
        "Domain Name: variant.com\n"
        "Registrar: Variant Registrar\n"
        "Creation Date: 2010-01-01T00:00:00Z\n"
        "Expiration Date: 2030-01-01T00:00:00Z\n"
        "Name Server: ns1.variant.com\n"
    )
    deltas = parse(text)
    domain = next(d for d in deltas if d.type == "Domain")
    assert domain.identity == {"name": "variant.com"}
    assert domain.props["expiration_date"] == "2030-01-01T00:00:00Z"
    assert domain.props["name_servers"] == ["ns1.variant.com"]


def test_parse_whois_handles_expiry_date_variant():
    text = (
        "Domain Name: expiry.com\n"
        "Registrar: Expiry Registrar\n"
        "Registry Expiry Date: 2031-05-01T00:00:00Z\n"
    )
    deltas = parse(text)
    domain = next(d for d in deltas if d.type == "Domain")
    assert domain.props["expiration_date"] == "2031-05-01T00:00:00Z"


def test_parse_whois_empty_input_returns_empty_list():
    assert parse("") == []
    assert parse("\n\n   \n") == []


def test_parse_whois_garbage_input_returns_empty_list():
    assert parse("this is not whois output at all, just garbage text") == []


def test_parse_whois_missing_domain_name_returns_empty_list():
    text = "Registrar: No Domain Name Registrar\nCreation Date: 2020-01-01T00:00:00Z\n"
    assert parse(text) == []


def test_parse_whois_anchors_domain_to_apex_when_no_domain_name_line():
    """D14b/D11: a non-registrable exact host whose whois text carries NO
    `Domain Name:` line must STILL yield a Domain node, anchored to the
    registrable apex derived from the queried host - so later-phase Domain
    consumers (paramspider) always have an anchor."""
    text = (
        "Registrar: Some Registrar\n"
        "Creation Date: 2019-06-01T00:00:00Z\n"
        "Name Server: ns1.daytona.io\n"
    )
    deltas = parse(text, target_url="app.daytona.io")
    domain = next(d for d in deltas if d.type == "Domain")
    assert domain.identity == {"name": "daytona.io"}
    # Parsed props still ride along from the raw text.
    assert domain.props["registrar"] == "Some Registrar"
    assert domain.props["name_servers"] == ["ns1.daytona.io"]


def test_parse_whois_apex_anchor_overrides_raw_domain_name_line():
    """When a queried host is supplied, the deterministic registrable apex is
    the anchor - the raw `Domain Name:` line is NOT trusted (it can be a
    registry-canonicalised or unrelated value)."""
    text = "Domain Name: SOMETHINGELSE.NET\nRegistrar: R\n"
    deltas = parse(text, target_url="api.app.daytona.io")
    domain = next(d for d in deltas if d.type == "Domain")
    assert domain.identity == {"name": "daytona.io"}


def test_parse_whois_apex_anchor_tolerates_url_and_www_and_port():
    """The queried host is a bare host in practice, but a URL / port / www.
    prefix is tolerated when deriving the apex."""
    for target in ("https://www.daytona.io:443/path", "www.daytona.io", "DAYTONA.IO"):
        domain = next(
            d for d in parse("Registrar: R\n", target_url=target) if d.type == "Domain"
        )
        assert domain.identity == {"name": "daytona.io"}


def test_parse_whois_no_target_and_no_domain_name_still_empty():
    """Fallback path unchanged: with neither a queried host nor a parseable
    `Domain Name:` line there is no anchor, so no Domain node (existing
    direct-parse unit-test contract)."""
    assert parse("Registrar: R\nCreation Date: 2020-01-01T00:00:00Z\n") == []


def test_parse_whois_dedups_name_servers_preserving_order():
    """Registries list each NS twice (registry + registrar sections); the
    parser must dedup while preserving first-seen order (Defect D4)."""
    text = (
        "Domain Name: dedup.com\n"
        "Name Server: NS1.EXAMPLE.NET\n"
        "Name Server: NS2.EXAMPLE.NET\n"
        "Name Server: ns1.example.net\n"  # dup (case-normalised)
        "Name Server: ns2.example.net\n"  # dup
    )
    domain = next(d for d in parse(text) if d.type == "Domain")
    assert domain.props["name_servers"] == ["ns1.example.net", "ns2.example.net"]
