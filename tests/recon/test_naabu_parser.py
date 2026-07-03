# tests/recon/test_naabu_parser.py
from pathlib import Path
from agent.recon.parsers import get_parser
from agent.recon.parsers.naabu_parser import parse, get_service_name

FIX = Path(__file__).parent / "fixtures" / "naabu.jsonl"


def test_registry_exposes_naabu():
    assert get_parser("naabu") is parse


def test_get_service_name_known_and_unknown():
    assert get_service_name(443) == "https"
    assert get_service_name(31337) == "unknown"


def test_parse_emits_one_ip_two_ports_two_services():
    deltas = parse(FIX.read_text())

    ips = [d for d in deltas if d.type == "IP"]
    ports = [d for d in deltas if d.type == "Port"]
    services = [d for d in deltas if d.type == "Service"]

    assert len(ips) == 1
    assert ips[0].identity == {"address": "93.184.216.34"}
    assert ips[0].props["version"] == "ipv4"

    assert len(ports) == 2
    port_numbers = {p.identity["number"] for p in ports}
    assert port_numbers == {443, 31337}
    for p in ports:
        assert p.identity["protocol"] == "tcp"
        assert p.identity["ip_address"] == "93.184.216.34"
        assert p.props["state"] == "open"
        assert any(
            e.rel == "HAS_PORT" and e.dir == "in" and e.node_type == "IP"
            and e.node_identity == {"address": "93.184.216.34"}
            for e in p.edges
        )

    assert len(services) == 2
    svc_443 = next(s for s in services if s.identity["port_number"] == 443)
    assert svc_443.identity["name"] == "https"
    assert svc_443.identity["ip_address"] == "93.184.216.34"
    assert any(
        e.rel == "RUNS_SERVICE" and e.dir == "in" and e.node_type == "Port"
        and e.node_identity == {"number": 443, "protocol": "tcp", "ip_address": "93.184.216.34"}
        for e in svc_443.edges
    )

    svc_unknown = next(s for s in services if s.identity["port_number"] == 31337)
    assert svc_unknown.identity["name"] == "unknown"


def test_malformed_line_skipped():
    deltas = parse('{"host":"a","ip":"1.2.3.4","port":80}\nNOT JSON\n')
    assert any(d.type == "IP" for d in deltas)


def test_missing_ip_line_skipped():
    deltas = parse('{"host":"a","port":80}\n')
    assert deltas == []


def test_ipv6_version_inferred():
    deltas = parse('{"host":"a","ip":"2001:db8::1","port":80}\n')
    ip = next(d for d in deltas if d.type == "IP")
    assert ip.props["version"] == "ipv6"
