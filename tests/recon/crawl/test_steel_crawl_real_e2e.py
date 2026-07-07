"""Real steel.dev crawl e2e: provider -> manifest -> steel_parser -> curate -> Neo4j.

Gated + skippable. These tests open a REAL steel.dev cloud-browser session
(over Playwright-CDP), so they skip cleanly unless `STEEL_API_KEY` is set AND the
live Neo4j is reachable - they never run in the offline suite.

`test_steel_crawl_real_session_flows_to_neo4j` is the AUTOMATIC unauthenticated
path: it drives the real `SteelCrawlProvider` tools (via the real
`steel_client.get_crawl_tools()` factory) against a stable public scraping
sandbox, then pushes the resulting manifest through the production
`get_parser("steel_crawl")` -> `curate` -> `neo4j_client.merge` path and verifies
the `BaseURL`/`Endpoint`/`Parameter` nodes landed in Neo4j by querying it
DIRECTLY (mirroring `test_full_stack_real_infra_e2e.py`). No LLM is needed - the
crawl is driven deterministically so the assertion surface is stable.

`test_steel_crawl_agentic_loop_flows_to_neo4j` additionally exercises the LLM
ReAct loop (`crawl_agent.run_crawl`) and is gated on an OpenRouter key too.

`test_steel_crawl_authenticated_manual` documents + exercises the interactive
`steel_await_auth` login flow; it needs a human at the Steel viewer, so it is
MANUAL (skips unless `STEEL_MANUAL_AUTH_E2E=1`).

Run (from the repo root, live stack up):

    STEEL_API_KEY=<key> .venv/bin/python -m pytest \
        tests/recon/crawl/test_steel_crawl_real_e2e.py -q -s
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import socket
import uuid

import pytest

# Stable public scraping sandbox. A query-string seed guarantees the manifest
# carries an endpoint with query params, so the Parameter merge path is covered.
TARGET_HOST = "books.toscrape.com"
SEED_URL = f"https://{TARGET_HOST}/?q=steele2e&page=1"

pytestmark = pytest.mark.skipif(
    not os.environ.get("STEEL_API_KEY"),
    reason="STEEL_API_KEY (steel.dev credential) required for a real crawl session",
)


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _bridge_neo4j_to_localhost():
    """Bind the recon config + neo4j_client to the host-reachable Neo4j and set
    the steel credential on `agent.recon.config` (compose hostnames only resolve
    inside the network; conftest may have frozen dummy values at collection)."""
    os.environ["NEO4J_URI"] = "bolt://localhost:7687"
    os.environ["NEO4J_USER"] = "neo4j"
    os.environ["NEO4J_PASSWORD"] = os.environ.get("SB_NEO4J_PASSWORD", "polymerhus")

    import agent.app.config as app_config
    importlib.reload(app_config)
    from agent.app.clients import neo4j_client
    importlib.reload(neo4j_client)

    import agent.recon.config as recon_config
    recon_config.STEEL_API_KEY = os.environ["STEEL_API_KEY"]
    return neo4j_client


def _graph_census(neo4j_client, project_id: str) -> dict:
    with neo4j_client._driver.session() as s:
        return {
            r["l"]: r["c"]
            for r in s.run(
                "MATCH (n {project_id:$pid}) UNWIND labels(n) AS l "
                "RETURN l AS l, count(*) AS c",
                pid=project_id,
            )
        }


def _cleanup(neo4j_client, project_id: str):
    with neo4j_client._driver.session() as s:
        s.run("MATCH (n {project_id:$pid}) DETACH DELETE n", pid=project_id)


async def _drive_real_crawl(seed: str, scope: list[str]) -> dict:
    """Drive the real steel_* tools (from the production factory) to a manifest."""
    from agent.recon.crawl import steel_client

    tools = {t.name: t for t in await steel_client.get_crawl_tools()}
    start = await tools["steel_crawl_start"].ainvoke(
        {"target": seed, "scope": scope, "max_depth": 1, "max_pages": 3}
    )
    assert start.get("crawl_id"), f"steel_crawl_start failed: {start}"
    cid = start["crawl_id"]
    assert start.get("viewer_url"), "expected a steel.dev viewer_url on session start"

    await tools["steel_navigate"].ainvoke({"crawl_id": cid, "url": seed})
    # follow one discovered in-scope link if present, for a richer manifest
    fr = await tools["steel_frontier"].ainvoke({"crawl_id": cid})
    if fr.get("frontier"):
        await tools["steel_navigate"].ainvoke(
            {"crawl_id": cid, "url": fr["frontier"][0]["url"]}
        )
    return await tools["steel_crawl_finish"].ainvoke({"crawl_id": cid})


def _parse_curate_and_verify(neo4j_client, manifest: dict, project_id: str):
    from agent.recon.curator import curate
    from agent.recon.parsers import get_parser

    assets = get_parser("steel_crawl")(json.dumps(manifest))
    types = {a.type for a in assets}
    assert {"BaseURL", "Endpoint"} <= types, f"parser produced {types}: {assets}"

    assets_merged, _ = curate(assets, [], project_id)
    assert assets_merged > 0, "curate merged nothing into Neo4j"

    labels = _graph_census(neo4j_client, project_id)
    assert labels.get("BaseURL", 0) >= 1, labels
    assert labels.get("Endpoint", 0) >= 1, labels
    assert labels.get("Parameter", 0) >= 1, labels
    return labels


def test_steel_crawl_real_session_flows_to_neo4j():
    if not _port_open("localhost", 7687):
        pytest.skip("live Neo4j (localhost:7687) not reachable")
    neo4j_client = _bridge_neo4j_to_localhost()
    neo4j_client.ensure_schema()

    project_id = f"steel-e2e-{uuid.uuid4().hex[:8]}"
    try:
        manifest = asyncio.run(_drive_real_crawl(SEED_URL, [TARGET_HOST]))
        assert manifest["endpoints"], f"empty manifest from real crawl: {manifest}"
        labels = _parse_curate_and_verify(neo4j_client, manifest, project_id)
        print(f"[real-session e2e] manifest endpoints={len(manifest['endpoints'])} "
              f"js_urls={len(manifest['js_urls'])} neo4j_labels={labels}")
    finally:
        _cleanup(neo4j_client, project_id)


def test_steel_crawl_agentic_loop_flows_to_neo4j():
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY_OPENROUTER")):
        pytest.skip("live OpenRouter key required for the agentic ReAct crawl loop")
    if not _port_open("localhost", 7687):
        pytest.skip("live Neo4j (localhost:7687) not reachable")

    key = os.environ.get("API_KEY_OPENROUTER") or os.environ.get("OPENAI_API_KEY")
    os.environ["API_KEY_OPENROUTER"] = key
    os.environ.setdefault("LLM_MODEL_CRAWLER", "openrouter:openai/gpt-4.1-mini")
    neo4j_client = _bridge_neo4j_to_localhost()
    neo4j_client.ensure_schema()

    from agent.recon.crawl import crawl_agent

    project_id = f"steel-agentic-e2e-{uuid.uuid4().hex[:8]}"
    try:
        manifest = asyncio.run(
            crawl_agent.run_crawl(SEED_URL, scope=[TARGET_HOST], max_pages=4, max_depth=1)
        )
        assert manifest["endpoints"], f"agentic loop produced empty manifest: {manifest}"
        labels = _parse_curate_and_verify(neo4j_client, manifest, project_id)
        print(f"[agentic-loop e2e] manifest endpoints={len(manifest['endpoints'])} "
              f"neo4j_labels={labels}")
    finally:
        _cleanup(neo4j_client, project_id)


@pytest.mark.skipif(
    os.environ.get("STEEL_MANUAL_AUTH_E2E") != "1",
    reason="interactive login required; set STEEL_MANUAL_AUTH_E2E=1 to run manually",
)
def test_steel_crawl_authenticated_manual():
    """MANUAL: exercise the interactive steel_await_auth flow end to end.

    How to run:
      1. Bring the live stack up and export STEEL_API_KEY + an OpenRouter key.
      2. Run: STEEL_MANUAL_AUTH_E2E=1 STEEL_AUTH_TARGET=https://<login-app> \\
              STEEL_API_KEY=<k> .venv/bin/python -m pytest -q -s \\
              tests/recon/crawl/test_steel_crawl_real_e2e.py -k authenticated_manual
      3. The test prints the Steel viewer URL. Open it in a browser and complete
         the login WITHIN the session window; the crawl resumes once
         steel_await_auth detects the in-scope session cookie.
    """
    target = os.environ.get("STEEL_AUTH_TARGET")
    if not target:
        pytest.skip("set STEEL_AUTH_TARGET=https://<login-protected-app> to run")
    host = target.split("://", 1)[-1].split("/", 1)[0]

    async def _run():
        from agent.recon.crawl import steel_client
        from agent.recon.crawl.crawl_agentic import AgenticCrawlRequest, precreate_auth_session

        tools = await steel_client.get_crawl_tools()

        class _MM:
            async def get_tools(self):
                return tools

        body = AgenticCrawlRequest(target=target, scope=[host], model="crawler", auth_required=True)
        crawl_id, awaiting = await precreate_auth_session(_MM(), body)
        assert awaiting and awaiting.get("viewer_url")
        print("\n>>> OPEN THIS STEEL VIEWER AND LOG IN NOW:", awaiting["viewer_url"], "\n")
        by_name = {t.name: t for t in tools}
        auth = await by_name["steel_await_auth"].ainvoke({"crawl_id": crawl_id, "timeout_s": 240})
        print("steel_await_auth ->", auth)
        manifest = await by_name["steel_crawl_finish"].ainvoke({"crawl_id": crawl_id})
        return awaiting, manifest

    awaiting, manifest = asyncio.run(_run())
    assert awaiting["viewer_url"].startswith("http")
    # manifest may be sparse depending on how far the operator navigated; the
    # point of this manual test is that the viewer URL was surfaced BEFORE the
    # blocking await, and the authenticated session produced a drainable manifest.
    assert isinstance(manifest, dict) and "endpoints" in manifest
