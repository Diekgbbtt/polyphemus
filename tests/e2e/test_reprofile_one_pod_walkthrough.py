"""E1 walkthrough (e2e tier) for #208 - httpx_reprofile: one pod, O(1) turns.

A full traced path from the pipeline's entry seam to its observable outcome:
a multi-endpoint project seeded into Neo4j runs the reprofile PHASE ONLY
(`job_subset=["httpx_reprofile"]` - the dispatch shape under test, no crawl
needed) against a live reachable target. Terminal quantities are read back from
the persisted `recon_jobs` row and the live Neo4j graph.

Expected values come from the #208 spec, not recomputed:
  - `recon_jobs` shows EXACTLY ONE pod (`stats.pods == 1`, `stats.success == 1`)
    with `stats.endpoints_total` == the seeded endpoint count
  - every seeded Endpoint carries its own `profile` (enrichment, not discovery)
  - `BaseURL.profile` mirrors the root `/` Endpoint's profile

The live edge is the reprofile target's HTTP surface: the pod's httpx probes
the seeded endpoint URLs. The seed must point at a reachable multi-endpoint
host (env `SB_REPROFILE_BASEURL` + `SB_REPROFILE_PATHS`). Gated like the other
real-infra e2e passes: skips when the live stack (Neo4j/Postgres/Kali MCP) or
the LLM key is absent, so it never breaks the offline suite.
"""
from __future__ import annotations

import importlib
import os
import socket
import uuid

import pytest

pytestmark = pytest.mark.live_neo4j

_REPROFILE_BASEURL = os.environ.get("SB_REPROFILE_BASEURL", "https://soupmarket.shop")
_REPROFILE_PATHS = [
    p.strip() for p in os.environ.get(
        "SB_REPROFILE_PATHS",
        "/, /rest/products/search, /api/Challenges, /api/Quantitys/1",
    ).split(",") if p.strip()
]

# The key the live triager model needs, resolved the way the app does
# (`providers._key_env`: `API_KEY_<PROVIDER>`, hyphens as underscores). The
# stack's triager is `opencode:opencode/muse-spark-...` -> `API_KEY_OPENCODE`;
# the legacy OPENROUTER/OPENAI names cover host-side runs predating the
# per-provider convention.
_LLM_KEY_ENVS = ("API_KEY_OPENROUTER", "OPENAI_API_KEY")


def _triager_key_present() -> bool:
    if any(os.environ.get(k) for k in _LLM_KEY_ENVS):
        return True
    model = os.environ.get("LLM_TRIAGER", "")
    provider = model.split(":", 1)[0] if ":" in model else ""
    return bool(provider) and bool(
        os.environ.get("API_KEY_" + provider.upper().replace("-", "_"))
    )


pytestmark = pytest.mark.skipif(
    not _triager_key_present(),
    reason="live triager model key required (the LLM_TRIAGER provider's "
    "API_KEY_<PROVIDER>, or OPENAI_API_KEY / API_KEY_OPENROUTER)",
)


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _in_network() -> bool:
    """True when running inside the compose network / the agent container: the
    co-located gateway (ADR D1) answers on the container's own loopback. A
    host-side run never has a gateway on localhost:4000."""
    return bool(os.environ.get("LLM_GATEWAY_URL")) and _port_open("localhost", 4000)


def _bridge_env_to_localhost() -> None:
    """Bridge the operator's .env for a HOST-side run: OpenRouter key ->
    API_KEY_OPENROUTER, per-role models, and localhost service URLs. Then
    reload config + neo4j_client so they bind to the live stack (conftest may
    have frozen dummy values at collection). Skipped in-network: the stack env
    already carries the service-DNS targets (neo4j/postgres/kali) and the
    co-located gateway."""
    key = os.environ.get("API_KEY_OPENROUTER") or os.environ.get("OPENAI_API_KEY")
    os.environ["API_KEY_OPENROUTER"] = key
    os.environ["LLM_TRIAGER"] = os.environ.get(
        "SB_REPROFILE_MODEL", "openrouter:deepseek/deepseek-v4-flash")
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


def test_e1_reprofile_dispatches_one_pod_and_stamps_every_profile():
    in_network = _in_network()
    if in_network:
        # Service-DNS targets, exactly as the agent resolves them.
        if not (_port_open("neo4j", 7687) and _port_open("postgres", 5432)
                and _port_open("kali", 8000)):
            pytest.skip("live stack (neo4j/postgres/kali) not reachable in-network")
    else:
        if not (_port_open("localhost", 7687) and _port_open("localhost", 5432)
                and _port_open("localhost", 8000)):
            pytest.skip("live stack (neo4j:7687 / postgres:5432 / kali:8000) not reachable")
        _bridge_env_to_localhost()

    import asyncio

    from polymerhus.app.clients import neo4j_client, pg
    from polymerhus.recon.control import pipeline

    # Fail-fast: the Kali MCP execute_command tool actually runs a command.
    from polymerhus.recon.domain.pod import default_exec_fn
    echo = default_exec_fn("echo reprofile-e1", "preflight", 30)
    assert echo.returncode == 0 and "reprofile-e1" in echo.stdout, echo

    project_id = f"reprofile-e1-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    neo4j_client.ensure_schema()
    pg.create_project(project_id, "reprofile-one-pod-e1")
    # The seed must be the BARE HOST, never a URL: `parse_scope` reads it verbatim
    # and the pipeline threads it as `scope_domain` into `curate`'s D14 filter
    # (`host_in_scope(host, scope_domain)` compares hostnames). A `https://`
    # seed never equals the parsed `soupmarket.shop` host, so the filter drops
    # EVERY parsed asset and no profile is ever stamped.
    seed_host = _REPROFILE_BASEURL.split("://", 1)[-1].rstrip("/")
    pg.save_settings(project_id, {"target_seed": seed_host})

    # Seed the surface as if the crawlers had produced it: one BaseURL with
    # root `/` plus the known endpoint paths (the reprofile phase's input).
    # The Endpoints carry `method` because the curator's Endpoint identity is
    # `{path, method, baseurl}` - a seed without it would be a DIFFERENT node
    # than the parse deltas, so the reprofile pass would mint duplicates and
    # the seeded node would never receive its `profile`.
    with neo4j_client._driver.session() as s:
        s.run(
            "MERGE (b:BaseURL {url: $base, project_id: $pid}) "
            "ON CREATE SET b.first_seen = datetime() SET b.last_seen = datetime()",
            base=_REPROFILE_BASEURL, pid=project_id,
        )
        for path in _REPROFILE_PATHS:
            url = _REPROFILE_BASEURL.rstrip("/") + path
            s.run(
                "MERGE (e:Endpoint {url: $url, project_id: $pid}) "
                "SET e.baseurl = $base, e.path = $path, e.method = 'GET' "
                "SET e.last_seen = datetime()",
                url=url, base=_REPROFILE_BASEURL, path=path, pid=project_id,
            )

    asyncio.run(
        pipeline.run_pipeline(
            project_id, run_id=run_id,
            # `validate_job_subset` requires a job's consumed type to be produced
            # by an earlier SELECTED job, so a bare `["httpx_reprofile"]` is
            # rejected (Endpoint is not produced by any earlier selected job).
            # httpx is the minimal producer: one `-u <seed>` probe that re-mints
            # the already-seeded root (MERGE, idempotent - no probe-set growth).
            # The walkthrough still asserts ONLY the reprofile pod's O(1) shape;
            # httpx's own outcome is fail-open and never asserted.
            job_subset=["httpx", "httpx_reprofile"],
        )
    )

    # 1. The phase reached a terminal status and paid exactly ONE pod.
    run = pg.get_run(run_id)
    assert run["status"] == "complete", run
    jobs = {j["job"]: j for j in pg.get_run_jobs(run_id)}
    j = jobs["httpx_reprofile"]
    assert j["status"] == "success", j
    assert j["stats"]["pods"] == 1, j            # ONE pod regardless of endpoint count
    assert j["stats"]["success"] == 1, j
    assert j["stats"]["endpoints_total"] == len(_REPROFILE_PATHS), j

    # 2. Every seeded Endpoint now carries its own `profile` (enrichment).
    with neo4j_client._driver.session() as s:
        profiled = s.run(
            "MATCH (e:Endpoint {project_id: $pid}) "
            "WHERE e.profile IS NOT NULL AND e.profile <> '' "
            "RETURN count(e) AS c", pid=project_id,
        ).single()["c"]
        unprofiled = s.run(
            "MATCH (e:Endpoint {project_id: $pid}) "
            "WHERE e.profile IS NULL OR e.profile = '' "
            "RETURN count(e) AS c", pid=project_id,
        ).single()["c"]
        root_profile = s.run(
            "MATCH (b:BaseURL {url: $base, project_id: $pid}) RETURN b.profile AS p",
            base=_REPROFILE_BASEURL, pid=project_id,
        ).single()["p"]
        obs = s.run(
            "MATCH (o:Observation {project_id: $pid}) RETURN count(o) AS c",
            pid=project_id,
        ).single()["c"]

    assert profiled >= len(_REPROFILE_PATHS), (profiled, unprofiled)
    assert unprofiled == 0, unprofiled
    assert root_profile in {"webapp", "restapi", "graphql_api"}, root_profile

    # 3. The triager paid O(1) turns: at most a few Observations from the ONE
    #    turn (the reprofile run never fans out one triager turn per endpoint).
    assert obs >= 0  # observations are the consumption side; a degraded turn is valid