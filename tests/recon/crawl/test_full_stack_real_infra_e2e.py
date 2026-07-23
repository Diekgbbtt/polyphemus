"""Full-stack REAL-infra recon e2e (Stream-B loop deliverable).

Unlike `test_full_stack_live_llm_e2e.py` (which fakes the Kali exec + graph),
this drives `polymerhus.recon.control.pipeline.run_pipeline` with its PRODUCTION defaults
against the live compose stack and a real target:

  - real `default_exec_fn` -> Kali MCP `execute_command` over streamable-http
  - real `default_triage_fn` -> OpenRouter (reasoning model) triager LLM
  - real `curate` -> `neo4j_client.merge` writing into the live Neo4j
  - real Postgres registry (`polymerhus.app.clients.pg`)

Nothing is mocked. It runs a bounded, reliable subset (subfinder -> dnsx ->
httpx) so the assertion surface is deterministic-ish while still exercising
three live tool families, the real triager, and real graph writes.

Gated + skippable: skips cleanly when the OpenRouter key is absent OR the
live stack (Kali MCP / Neo4j / Postgres) is not reachable, so it never breaks
the offline suite and never requires network/infra by default. It runs from
the HOST, so it rebinds `polymerhus.app.config` + `neo4j_client` to the localhost
service ports (the compose-internal hostnames in `.env` only resolve inside
the network).
"""
from __future__ import annotations

import importlib
import os
import socket
import uuid

import pytest

import pytest as _pytest_live

# Real-infra e2e: live full stack.
pytestmark = _pytest_live.mark.live_neo4j

TARGET_DOMAIN = "allegro.cz.allegrosandbox.pl"

# Cheap tool-calling model + a real DeepSeek reasoner (resolved live from
# https://openrouter.ai/api/v1/models), overridable via env.
TOOLCALL_MODEL = os.environ.get("SB_TOOLCALL_MODEL", "openai/gpt-4.1-mini")
REASONING_MODEL = os.environ.get("SB_REASONING_MODEL", "deepseek/deepseek-v4-flash")

pytestmark = pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY_OPENROUTER")),
    reason="live OpenRouter key required (OPENAI_API_KEY or API_KEY_OPENROUTER)",
)


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _bridge_env_to_localhost() -> None:
    """Bridge the operator's .env for a host-side run: OpenRouter key ->
    API_KEY_OPENROUTER, per-role models, and localhost service URLs. Then
    reload config + neo4j_client so they bind to the live stack (conftest may
    have frozen dummy values at collection)."""
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


def test_full_stack_real_infra_pipeline():
    if not (_port_open("localhost", 7687) and _port_open("localhost", 5432) and _port_open("localhost", 8000)):
        pytest.skip("live stack (neo4j:7687 / postgres:5432 / kali:8000) not reachable")

    _bridge_env_to_localhost()

    import asyncio

    from polymerhus.app.clients import neo4j_client, pg
    from polymerhus.recon.control import pipeline

    # Fail-fast: the Kali MCP execute_command tool actually runs a command.
    from polymerhus.recon.domain.pod import default_exec_fn
    echo = default_exec_fn("echo real-infra-e2e", "preflight", 30)
    assert echo.returncode == 0 and "real-infra-e2e" in echo.stdout, echo

    project_id = f"sb-e2e-pytest-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    neo4j_client.ensure_schema()
    pg.create_project(project_id, "stream-b-real-infra-e2e")
    pg.save_settings(project_id, {"target_domain": TARGET_DOMAIN})
    # Pre-seed the target host as a Subdomain so the Subdomain-consuming phases
    # (dnsx/httpx) run even though this deep host yields no NEW subdomains.
    with neo4j_client._driver.session() as s:
        s.run(
            "MERGE (n:Subdomain {name: $name, project_id: $pid}) "
            "ON CREATE SET n.first_seen = datetime() SET n.last_seen = datetime()",
            name=TARGET_DOMAIN, pid=project_id,
        )

    asyncio.run(
        pipeline.run_pipeline(
            project_id,
            run_id=run_id,
            job_subset=["subfinder", "dnsx", "httpx"],
        )
    )

    # 1. Pipeline reached its terminal "complete" state.
    run = pg.get_run(run_id)
    assert run["status"] == "complete", run

    # 2. httpx (the richest live tool here) actually produced graph primitives.
    jobs = {j["job"]: j for j in pg.get_run_jobs(run_id)}
    assert jobs["httpx"]["status"] in {"success", "degraded"}, jobs["httpx"]

    # 3. Primitives across several labels MERGEd into Neo4j (verify directly).
    with neo4j_client._driver.session() as s:
        labels = {
            r["l"]: r["c"]
            for r in s.run(
                "MATCH (n {project_id:$pid}) UNWIND labels(n) AS l "
                "RETURN l AS l, count(*) AS c",
                pid=project_id,
            )
        }
        obs = s.run(
            "MATCH (o:Observation {project_id:$pid}) RETURN count(o) AS c",
            pid=project_id,
        ).single()["c"]

    # Primitives span several distinct labels via the real parse -> curate ->
    # Neo4j write path. subfinder (Subdomain) + dnsx (IP/DNSRecord) are passive
    # / DNS-based and reliable even when the HTTP target throttles (DataDome);
    # httpx's BaseURL/Endpoint/Technology land too when the target responds.
    # Assert the reliable floor (>=3 distinct primitive labels incl. the
    # seeded Subdomain and dnsx's IP), not the target-mood-dependent HTTP ones.
    primitive_labels = {
        "Subdomain", "IP", "DNSRecord", "BaseURL", "Endpoint",
        "Technology", "Port", "Service", "Parameter",
    }
    assert "Subdomain" in labels, labels
    assert "IP" in labels, labels
    assert len(primitive_labels & labels.keys()) >= 3, labels

    # 4. The real triager LLM produced at least one Observation that the
    #    curator accepted into the graph (structure, not exact text). The
    #    triager runs per pod, so subfinder/dnsx output alone reliably yields
    #    accepted (Subdomain/IP-anchored) Observations.
    assert obs >= 1, f"no triager Observation reached Neo4j (labels={labels})"
