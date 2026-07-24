"""Host (bare-IP) seeding - unit assertions.

Mirrors docs/design/host-seeding-assertions.md (U-tier only; I/E tiers need
infra / a real target and live elsewhere). Neo4j is never touched: pure helpers
are exercised directly, and the pipeline-run tests inject fakes and spy on
`curate` so no delta reaches a driver (CODING_STANDARD §10)."""
import asyncio

import pytest

from polymerhus.recon.control import pipeline
from polymerhus.recon.control.jobs import JOBS, PHASES, build_phase_plan
from polymerhus.recon.control.scope import (
    HOST_MODE_ONLY_JOBS,
    HOST_MODE_SUPPRESSED,
    parse_scope,
    resolve_seed,
    seed_kind,
)
from polymerhus.recon.domain.curator import _promote_seed_root
from polymerhus.recon.domain.parsers import PARSERS
from polymerhus.recon.domain.parsers.httpx_parser import _bare_host
from polymerhus.recon.domain.parsers.httpx_parser import parse as parse_httpx
from polymerhus.recon.domain.types import AssetDelta, Edge

from tests.recon.test_pipeline import FakeRegistry, make_load_settings

IP = "93.184.216.34"


# --- A. Seed resolution and classification -------------------------------

def test_resolve_seed_prefers_target_seed():  # A1, A3
    assert resolve_seed({"target_seed": "new", "target_domain": "old"}) == "new"


def test_resolve_seed_falls_back_to_legacy_target_domain():  # A2 (regression)
    assert resolve_seed({"target_domain": "x"}) == "x"


def test_resolve_seed_empty_is_none():  # A4
    assert resolve_seed({}) is None
    assert resolve_seed({"target_seed": ""}) is None
    assert resolve_seed(None) is None


def test_seed_kind_classifies_ipv4_ipv6_domain():  # A5
    assert seed_kind("93.184.216.34") == "ipv4"
    assert seed_kind("::1") == "ipv6"
    assert seed_kind("2001:db8::1") == "ipv6"
    assert seed_kind("example.com") == "domain"
    assert seed_kind("app.example.com") == "domain"


def test_seed_kind_malformed_ip_is_domain():  # A6
    assert seed_kind("999.1.1.1") == "domain"
    assert seed_kind("1.2.3") == "domain"
    assert seed_kind("") == "domain"
    assert seed_kind(None) == "domain"


def test_parse_scope_bare_ipv4_is_host_mode():  # A7, A8
    assert parse_scope(IP) == {"apex": IP, "seed_host": IP, "mode": "host"}


def test_parse_scope_ipv6_is_host_mode_safety_net():  # A9
    assert parse_scope("::1")["mode"] == "host"


def test_parse_scope_never_raises():  # A10
    for s in ("", "  ", "*.", "not a domain", "1.2.3", IP, "::1"):
        parse_scope(s)


# --- G. _bare_host port stripping (S6) -----------------------------------

def test_bare_host_strips_port_from_ip():  # G1, G2
    assert _bare_host(f"{IP}:8080") == IP
    assert _bare_host(f"http://{IP}:8080") == IP


def test_bare_host_leaves_bare_domain():  # G3
    assert _bare_host("app.example.com") == "app.example.com"
    assert _bare_host("https://app.example.com") == "app.example.com"


def test_bare_host_strips_explicit_domain_port():  # G4
    assert _bare_host("https://app.example.com:8443") == "app.example.com"


# --- C. Root promotion (_promote_seed_root) ------------------------------

def test_promote_seed_root_rewrites_subdomain_to_ip():  # C2
    delta = AssetDelta(type="Subdomain", identity={"name": IP})
    _promote_seed_root([delta], IP, "IP")
    assert delta.type == "IP"
    assert delta.identity == {"address": IP}
    assert "name" not in delta.identity


def test_promote_seed_root_rewrites_edge_target_to_ip():  # C3
    delta = AssetDelta(
        type="BaseURL",
        identity={"url": f"http://{IP}"},
        edges=[Edge(rel="BELONGS_TO", dir="out", node_type="Subdomain",
                    node_identity={"name": IP})],
    )
    _promote_seed_root([delta], IP, "IP")
    edge = delta.edges[0]
    assert edge.node_type == "IP"
    assert edge.node_identity == {"address": IP}


def test_promote_seed_root_domain_mode_matches_legacy():  # C4 (regression)
    seed = "app.t.com"
    delta = AssetDelta(type="Subdomain", identity={"name": seed})
    edged = AssetDelta(
        type="BaseURL", identity={"url": f"https://{seed}"},
        edges=[Edge(rel="BELONGS_TO", dir="out", node_type="Subdomain",
                    node_identity={"name": seed})],
    )
    _promote_seed_root([delta, edged], seed, "Domain")
    assert delta.type == "Domain" and delta.identity == {"name": seed}
    assert edged.edges[0].node_type == "Domain"
    assert edged.edges[0].node_identity == {"name": seed}


def test_promote_seed_root_leaves_non_seed_subdomains():  # C5
    other = AssetDelta(type="Subdomain", identity={"name": "other.t.com"})
    _promote_seed_root([other], IP, "IP")
    assert other.type == "Subdomain" and other.identity == {"name": "other.t.com"}


# --- F. httpx_services bridge: job, plan, parser reuse -------------------

def test_httpx_services_reuses_httpx_parser():  # F6
    assert PARSERS["httpx_services"] is PARSERS["httpx"] is parse_httpx


def test_httpx_services_consumes_service():
    assert JOBS["httpx_services"].consumes == "Service"


def test_httpx_services_phase_after_naabu_before_crawl():  # F2
    flat = [j for phase in PHASES for j in phase]
    assert flat.index("naabu") < flat.index("httpx_services")
    assert flat.index("httpx_services") < flat.index("katana")
    assert flat.index("httpx") < flat.index("httpx_services")


def test_httpx_services_only_in_host_plan():  # F1, R2 (regression)
    host_plan = pipeline._gate_plan_by_scope(build_phase_plan(), {"mode": "host"})
    exact_plan = pipeline._gate_plan_by_scope(build_phase_plan(), {"mode": "exact"})
    wild_plan = pipeline._gate_plan_by_scope(build_phase_plan(), {"mode": "wildcard"})
    assert any("httpx_services" in phase for phase in host_plan)
    assert not any("httpx_services" in phase for phase in exact_plan)
    assert not any("httpx_services" in phase for phase in wild_plan)


# --- Service -> probe-target transform (S5a) -----------------------------

def test_services_transform_skips_default_ports():  # F4
    svcs = [
        {"name": "http", "port_number": 80, "ip_address": IP},
        {"name": "https", "port_number": 443, "ip_address": IP},
    ]
    assert pipeline._services_to_probe_targets(svcs) == []


def test_services_transform_synthesizes_nonstandard_ports():  # F5
    svcs = [
        {"name": "http-proxy", "port_number": 8080, "ip_address": IP},
        {"name": "unknown", "port_number": 8000, "ip_address": IP},  # naabu naming miss
    ]
    out = pipeline._services_to_probe_targets(svcs)
    assert {"url": f"{IP}:8080", "target": f"{IP}:8080"} in out
    assert {"url": f"{IP}:8000", "target": f"{IP}:8000"} in out


def test_services_transform_dedupes_and_ignores_ipless():
    svcs = [
        {"name": "http-proxy", "port_number": 8080, "ip_address": IP},
        {"name": "http-proxy", "port_number": 8080, "ip_address": IP},
        {"name": "x", "port_number": 8080},  # no ip -> dropped
    ]
    out = pipeline._services_to_probe_targets(svcs)
    assert out == [{"url": f"{IP}:8080", "target": f"{IP}:8080"}]


# --- B/C/D/F. Host-mode pipeline run (fully mocked) ----------------------

def _run_host(settings, *, service_nodes=None):
    """Drive a fully-mocked host-mode run. Spies on `curate` (so no delta hits a
    driver) and returns (call_order, seen_inputs, curate_calls)."""
    call_order, seen_inputs, curate_calls = [], {}, []

    async def run_job(job, input_assets, *, run_id, phase, extra):
        call_order.append(job.tool)
        seen_inputs[job.tool] = input_assets
        from polymerhus.recon.control.job_agent import PodExport
        return [PodExport(input_asset={}, verdict="success")]

    def read_assets(node_type, project_id, where=None):
        if node_type == "Service":
            return list(service_nodes or [])
        return []  # no discovered subdomains in host mode

    def spy_curate(assets, observations, project_id, **kw):
        curate_calls.append(assets)
        return (len(assets), len(observations))

    orig = pipeline.curate
    pipeline.curate = spy_curate
    try:
        asyncio.run(
            pipeline.run_pipeline(
                "proj1", run_id="run1",
                run_job=run_job,
                load_settings=make_load_settings(settings),
                registry=FakeRegistry(),
                read_assets=read_assets,
            )
        )
    finally:
        pipeline.curate = orig
    return call_order, seen_inputs, curate_calls


def test_host_mode_suppresses_discovery_and_harvesters():  # B1, B2, B4
    call_order, _, _ = _run_host({"target_seed": IP})
    for job in ("subfinder", "amass", "puredns", "dnsx", "whois", "paramspider"):
        assert job not in call_order
    assert "naabu" in call_order and "httpx" in call_order


def test_host_mode_keeps_subdomain_takeover():  # B3
    call_order, _, _ = _run_host({"target_seed": IP})
    assert "subdomain_takeover" in call_order


def test_host_mode_seeds_ip_into_naabu_and_httpx():  # D1
    _, seen_inputs, _ = _run_host({"target_seed": IP})
    assert seen_inputs["naabu"][0] == {"name": IP}
    assert seen_inputs["httpx"][0] == {"name": IP}


def test_host_mode_root_materialized_as_ip():  # C1
    _, _, curate_calls = _run_host({"target_seed": IP})
    root = curate_calls[0][0]
    assert root.type == "IP"
    assert root.identity == {"address": IP}


def test_host_mode_runs_httpx_services_on_discovered_ports():  # F1 (run), F8-shape
    svcs = [{"name": "http-proxy", "port_number": 8080, "ip_address": IP}]
    call_order, seen_inputs, _ = _run_host({"target_seed": IP}, service_nodes=svcs)
    assert "httpx_services" in call_order
    assert seen_inputs["httpx_services"] == [{"url": f"{IP}:8080", "target": f"{IP}:8080"}]


def test_domain_mode_never_runs_httpx_services():  # R2 (regression)
    call_order, _, _ = _run_host({"target_seed": "app.t.com"})
    assert "httpx_services" not in call_order


# --- H. Launch guard -----------------------------------------------------

def _guard(monkeypatch, settings):
    from polymerhus.app.clients import pg
    from polymerhus.project_management import repository
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: settings)
    repository.validate_launch("p1", None)


def test_guard_refuses_targetless(monkeypatch):  # H1
    with pytest.raises(ValueError, match="target_seed"):
        _guard(monkeypatch, {})


def test_guard_accepts_legacy_target_domain(monkeypatch):  # H2 (regression)
    _guard(monkeypatch, {"target_domain": "example.com"})  # no raise


def test_guard_accepts_ipv4_seed(monkeypatch):  # H3
    _guard(monkeypatch, {"target_seed": IP})  # no raise


def test_guard_rejects_ipv6_seed(monkeypatch):  # H4
    with pytest.raises(ValueError, match="IPv6"):
        _guard(monkeypatch, {"target_seed": "2001:db8::1"})
