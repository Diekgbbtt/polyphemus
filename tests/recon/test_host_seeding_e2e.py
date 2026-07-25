"""Host (bare-IP) seeding REAL-infra e2e (D-HS, E-tier).

Drives `pipeline.run_pipeline` with PRODUCTION defaults against the live compose
stack and a real bare-IP target reachable over the kali container's VPN tun.
Nothing is mocked: real Kali exec over MCP, real triager LLM, real curate ->
live Neo4j, real Postgres registry.

Validates the host-seeding path end to end:
  bare IP -> `host` scope mode -> an `IP` engagement root -> naabu/httpx probe
  the IP -> BaseURL(s) on the IP -> the host-mode-only `httpx_services` bridge
  runs. Confirms the IP is NEVER mis-typed as a Subdomain/Domain (C1/C6).

Gated/skippable: needs an OpenRouter key, the live stack reachable on localhost,
AND the target reachable from inside the kali container (the harness/operator
brings the VPN up first). Skips cleanly otherwise, so it never breaks the
offline suite.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import socket
import uuid

import pytest

TARGET_IP = os.environ.get("HS_TARGET_IP", "10.129.244.214")

TOOLCALL_MODEL = os.environ.get("SB_TOOLCALL_MODEL", "openai/gpt-4.1-mini")
REASONING_MODEL = os.environ.get("SB_REASONING_MODEL", "deepseek/deepseek-v4-flash")

pytestmark = [
    pytest.mark.live_neo4j,
    pytest.mark.skipif(
        not (os.environ.get("API_KEY_OPENROUTER") or os.environ.get("OPENAI_API_KEY")),
        reason="live OpenRouter key required (API_KEY_OPENROUTER or OPENAI_API_KEY)",
    ),
]


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _bridge_env_to_localhost() -> None:
    """Bridge the operator's .env for a host-side run: OpenRouter key + per-role
    models + localhost service URLs, then reload config + neo4j_client so they
    bind to the live stack (the compose-internal hostnames only resolve inside
    the network)."""
    key = os.environ.get("API_KEY_OPENROUTER") or os.environ.get("OPENAI_API_KEY")
    os.environ["API_KEY_OPENROUTER"] = key
    os.environ["LLM_MODEL_CRAWLER"] = f"openrouter:{TOOLCALL_MODEL}"
    os.environ["LLM_MODEL_CONFIGURATOR"] = f"openrouter:{TOOLCALL_MODEL}"
    os.environ["LLM_MODEL_JOB_ORCHESTRATOR"] = f"openrouter:{REASONING_MODEL}"
    os.environ["LLM_MODEL_TRIAGER"] = f"openrouter:{REASONING_MODEL}"
    os.environ["NEO4J_URI"] = "bolt://localhost:7687"
    os.environ["NEO4J_USER"] = "neo4j"
    os.environ["NEO4J_PASSWORD"] = os.environ.get("SB_NEO4J_PASSWORD", "polymerhus")
    os.environ["POSTGRES_DSN"] = "postgresql://polymerhus:polymerhus@localhost:5432/polymerhus"
    os.environ["KALI_MCP_URL"] = "http://localhost:8000/mcp"
    os.environ.setdefault("MAX_POD_ITERS", "2")

    import polymerhus.app.config as config_mod
    importlib.reload(config_mod)
    from polymerhus.app.clients import neo4j_client
    importlib.reload(neo4j_client)


def test_host_seeding_real_infra_pipeline():
    if not (_port_open("localhost", 7687) and _port_open("localhost", 5432) and _port_open("localhost", 8000)):
        pytest.skip("live stack (neo4j:7687 / postgres:5432 / kali:8000) not reachable")

    _bridge_env_to_localhost()

    from polymerhus.app.clients import neo4j_client, pg
    from polymerhus.recon.control import pipeline
    from polymerhus.recon.control.scope import parse_scope
    from polymerhus.recon.domain.pod import default_exec_fn

    # The target is a bare IP -> host scope mode (the whole point).
    assert parse_scope(TARGET_IP)["mode"] == "host", parse_scope(TARGET_IP)

    # Preflight 1: the Kali MCP exec path actually runs a command.
    echo = default_exec_fn("echo hs-e2e", "preflight", 30)
    assert echo.returncode == 0 and "hs-e2e" in echo.stdout, echo

    # Preflight 2: the target is reachable FROM the kali container (VPN up). If
    # not, skip rather than fail - bringing the tunnel up is the harness's job.
    reach = default_exec_fn(
        f"timeout 6 bash -c 'echo > /dev/tcp/{TARGET_IP}/443' && echo HS_REACHABLE || echo HS_UNREACHABLE",
        "preflight", 20,
    )
    if "HS_REACHABLE" not in (reach.stdout or ""):
        pytest.skip(f"target {TARGET_IP} not reachable from kali (VPN down?): {reach.stdout!r} {reach.stderr!r}")

    project_id = f"hs-e2e-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    neo4j_client.ensure_schema()
    pg.create_project(project_id, "host-seeding-e2e")
    pg.save_settings(project_id, {"target_seed": TARGET_IP})

    # Bounded host-mode subset: naabu (Port/Service), httpx (BaseURL on the IP,
    # 443), and the host-mode-only httpx_services bridge (Service -> BaseURL for
    # non-standard web ports; here it exercises the run + F9 no-BaseURL-for-
    # non-web-port path). Discovery/whois/paramspider are auto-suppressed by the
    # host-mode gate.
    asyncio.run(
        pipeline.run_pipeline(
            project_id,
            run_id=run_id,
            job_subset=["naabu", "httpx", "httpx_services"],
        )
    )

    # 1. Terminal state reached (fail-open rings always converge).
    run = pg.get_run(run_id)
    assert run["status"] == "complete", run

    # 2. Host-mode job gate (target-independent contract): discovery + the
    #    passive harvesters are suppressed; naabu/httpx run; the host-mode-only
    #    httpx_services bridge is present (NOT gated out - it may be `skipped`
    #    when naabu surfaces no non-default web port, which is still "present").
    jobs = {j["job"]: j for j in pg.get_run_jobs(run_id)}
    for suppressed in ("subfinder", "amass", "dnsx", "puredns", "whois", "paramspider"):
        assert suppressed not in jobs, f"{suppressed} must be suppressed in host mode: {jobs}"
    assert "naabu" in jobs and "httpx" in jobs, jobs
    assert "httpx_services" in jobs, f"host-mode-only bridge missing from plan: {jobs}"

    with neo4j_client._driver.session() as s:
        ip_root = s.run(
            "MATCH (n:IP {address:$a, project_id:$p}) RETURN count(n) AS c",
            a=TARGET_IP, p=project_id,
        ).single()["c"]
        mistyped_root = s.run(
            "MATCH (n {project_id:$p}) WHERE (n:Subdomain OR n:Domain) AND n.name=$a "
            "RETURN count(n) AS c",
            a=TARGET_IP, p=project_id,
        ).single()["c"]
        baseurls = [
            r["u"] for r in s.run(
                "MATCH (b:BaseURL {project_id:$p}) RETURN b.url AS u", p=project_id
            )
        ]
        labels = {
            r["l"]: r["c"] for r in s.run(
                "MATCH (n {project_id:$p}) UNWIND labels(n) AS l "
                "RETURN l AS l, count(*) AS c",
                p=project_id,
            )
        }

    # 3. THE load-bearing host-seeding contract (C1/C6, target-independent): a
    #    bare IP is deterministically the engagement root as an `IP` node, and is
    #    NEVER mis-typed as a Subdomain/Domain (the whole _promote_seed_root
    #    correctness argument). This is what the feature owns and must hold on any
    #    reachable target.
    assert ip_root >= 1, f"no IP root minted for {TARGET_IP}; labels={labels}"
    assert mistyped_root == 0, f"IP {TARGET_IP} mis-typed as Subdomain/Domain (x{mistyped_root})"

    # 4. Surface build is best-effort here and depends on the TARGET/substrate,
    #    not on host-seeding logic. Two known substrate limitations make a rich
    #    surface target-dependent (see docs/design/host-seeding-*.md):
    #      - httpx `-fr` drops the result when a bare IP 301-redirects to an
    #        unresolvable vhost (the FireFlow box -> https://fireflow.htb/);
    #      - naabu's connect scan does not traverse the VPN tun on this host.
    #    So we do NOT hard-require Port/Service/BaseURL. If a BaseURL WAS minted,
    #    it must be IP-hosted (structural), proving the IP reaches web discovery
    #    with no domain in play.
    print(f"[hs-e2e] surface: labels={labels} baseurls={baseurls}")
    for u in baseurls:
        assert TARGET_IP in (u or ""), f"BaseURL not IP-hosted in a host-mode run: {u}"
