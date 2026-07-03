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
