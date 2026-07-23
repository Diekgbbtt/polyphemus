# tests/recon/test_dns_parser.py
from pathlib import Path
from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers.dns_parser import parse_dnsx, parse_puredns

DNSX_FIX = Path(__file__).parent / "fixtures" / "dnsx.jsonl"
PUREDNS_FIX = Path(__file__).parent / "fixtures" / "puredns.txt"


def test_registry_exposes_dnsx_and_puredns():
    assert get_parser("dnsx") is parse_dnsx
    assert get_parser("puredns") is parse_puredns


def test_parse_dnsx_emits_ip_resolves_to_and_dns_record_for_a():
    deltas = parse_dnsx(DNSX_FIX.read_text())

    www = next(
        d for d in deltas if d.type == "Subdomain" and d.identity["name"] == "www.example.com"
    )
    assert www.props.get("has_dns_records") is True

    resolves = next(e for e in www.edges if e.rel == "RESOLVES_TO")
    assert resolves.dir == "out"
    assert resolves.node_type == "IP"
    assert resolves.node_identity == {"address": "93.184.216.34"}

    ips = [d for d in deltas if d.type == "IP"]
    assert len(ips) == 1
    assert ips[0].identity == {"address": "93.184.216.34"}


def test_parse_dnsx_emits_dns_record_for_a_and_cname_with_type_on_node():
    deltas = parse_dnsx(DNSX_FIX.read_text())

    records = [d for d in deltas if d.type == "DNSRecord"]
    types_for_www = {
        r.identity["type"] for r in records if r.identity["subdomain"] == "www.example.com"
    }
    assert types_for_www == {"A", "CNAME"}

    a_record = next(
        r
        for r in records
        if r.identity["subdomain"] == "www.example.com" and r.identity["type"] == "A"
    )
    assert a_record.identity["value"] == "93.184.216.34"

    cname_record = next(
        r
        for r in records
        if r.identity["subdomain"] == "www.example.com" and r.identity["type"] == "CNAME"
    )
    assert cname_record.identity["value"] == "edge.example.net"

    www = next(
        d for d in deltas if d.type == "Subdomain" and d.identity["name"] == "www.example.com"
    )
    has_dns_record_edges = [e for e in www.edges if e.rel == "HAS_DNS_RECORD"]
    assert len(has_dns_record_edges) == 2
    for edge in has_dns_record_edges:
        assert edge.dir == "out"
        assert edge.node_type == "DNSRecord"

    # CNAME must not also emit an IP/RESOLVES_TO edge
    cname_ip_edges = [
        e for e in www.edges if e.rel == "RESOLVES_TO" and e.node_identity.get("address") == "edge.example.net"
    ]
    assert cname_ip_edges == []


def test_parse_dnsx_emits_dns_records_for_mx_and_txt_without_ip():
    deltas = parse_dnsx(DNSX_FIX.read_text())

    mail = next(
        d for d in deltas if d.type == "Subdomain" and d.identity["name"] == "mail.example.com"
    )
    assert not any(e.rel == "RESOLVES_TO" for e in mail.edges)

    records = [d for d in deltas if d.type == "DNSRecord" and d.identity["subdomain"] == "mail.example.com"]
    types = {r.identity["type"] for r in records}
    assert types == {"MX", "TXT"}


def test_parse_dnsx_skips_malformed_and_empty_host():
    deltas = parse_dnsx(DNSX_FIX.read_text())
    subdomains = [d for d in deltas if d.type == "Subdomain"]
    assert len(subdomains) == 2


def test_parse_puredns_emits_resolved_subdomains():
    deltas = parse_puredns(PUREDNS_FIX.read_text())
    subdomains = [d for d in deltas if d.type == "Subdomain"]
    names = {d.identity["name"] for d in subdomains}
    assert names == {"www.example.com", "mail.example.com"}
    for d in subdomains:
        assert d.props.get("has_dns_records") is True


def test_parse_puredns_skips_blank_and_invalid_lines():
    deltas = parse_puredns(PUREDNS_FIX.read_text())
    subdomains = [d for d in deltas if d.type == "Subdomain"]
    assert len(subdomains) == 2


def test_malformed_line_skipped_inline():
    deltas = parse_dnsx('{"host":"a.example.com","a":["1.2.3.4"]}\nNOT JSON\n')
    assert any(d.type == "Subdomain" for d in deltas)
    deltas = parse_puredns("a.example.com\n\n")
    assert any(d.type == "Subdomain" for d in deltas)
