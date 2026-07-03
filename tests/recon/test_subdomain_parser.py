# tests/recon/test_subdomain_parser.py
from pathlib import Path
from agent.recon.parsers import get_parser
from agent.recon.parsers.subdomain_parser import parse_subfinder, parse_amass

SUBFINDER_FIX = Path(__file__).parent / "fixtures" / "subfinder.jsonl"
AMASS_FIX = Path(__file__).parent / "fixtures" / "amass.jsonl"


def test_registry_exposes_subfinder_and_amass():
    assert get_parser("subfinder") is parse_subfinder
    assert get_parser("amass") is parse_amass


def test_parse_subfinder_emits_subdomain_with_belongs_to_edge():
    deltas = parse_subfinder(SUBFINDER_FIX.read_text())
    subdomains = [d for d in deltas if d.type == "Subdomain"]
    assert len(subdomains) == 2
    names = {d.identity["name"] for d in subdomains}
    assert names == {"www.example.com", "api.example.com"}

    www = next(d for d in subdomains if d.identity["name"] == "www.example.com")
    edge = next(e for e in www.edges if e.rel == "BELONGS_TO")
    assert edge.dir == "out"
    assert edge.node_type == "Domain"
    assert edge.node_identity == {"name": "example.com"}


def test_parse_subfinder_skips_malformed_and_empty_host():
    deltas = parse_subfinder(SUBFINDER_FIX.read_text())
    subdomains = [d for d in deltas if d.type == "Subdomain"]
    assert len(subdomains) == 2


def test_parse_amass_emits_subdomain_ip_and_resolves_to_edge():
    deltas = parse_amass(AMASS_FIX.read_text())
    subdomains = [d for d in deltas if d.type == "Subdomain"]
    names = {d.identity["name"] for d in subdomains}
    assert names == {"mail.example.com", "beta.example.com"}

    mail = next(d for d in subdomains if d.identity["name"] == "mail.example.com")
    belongs = next(e for e in mail.edges if e.rel == "BELONGS_TO")
    assert belongs.dir == "out"
    assert belongs.node_type == "Domain"
    assert belongs.node_identity == {"name": "example.com"}

    resolves = next(e for e in mail.edges if e.rel == "RESOLVES_TO")
    assert resolves.dir == "out"
    assert resolves.node_type == "IP"
    assert resolves.node_identity == {"address": "93.184.216.34"}

    ips = [d for d in deltas if d.type == "IP"]
    assert len(ips) == 1
    assert ips[0].identity == {"address": "93.184.216.34"}

    beta = next(d for d in subdomains if d.identity["name"] == "beta.example.com")
    assert not any(e.rel == "RESOLVES_TO" for e in beta.edges)


def test_parse_amass_skips_malformed_and_empty_name():
    deltas = parse_amass(AMASS_FIX.read_text())
    subdomains = [d for d in deltas if d.type == "Subdomain"]
    assert len(subdomains) == 2


def test_malformed_line_skipped_inline():
    deltas = parse_subfinder('{"host":"a.example.com"}\nNOT JSON\n')
    assert any(d.type == "Subdomain" for d in deltas)
    deltas = parse_amass('{"name":"a.example.com","domain":"example.com"}\nNOT JSON\n')
    assert any(d.type == "Subdomain" for d in deltas)
