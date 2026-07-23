"""Full-stack happy-path e2e driven by a REAL LLM via OpenRouter (SP4 live-LLM
follow-up).

Every prior e2e test (`test_pipeline_e2e.py`, `test_crawl_e2e.py`) fakes BOTH
LLM seams - the triager (`fake_triage_fn` -> `[]`) and the crawler
(`_ScriptedLLM`). This test keeps every other collaborator exactly as those
tests do (real `run_pipeline`, real `job_agent`/`run_job`, real pod graphs,
real parsers, real curator writing into an in-memory graph, canned kali
stdout, a fake Steel toolset) but swaps in the REAL triager LLM
(`polymerhus.recon.domain.pod.default_triage_fn`, unmodified) for the httpx job and the
REAL crawler LLM (`polymerhus.recon.crawl.crawl_agent.run_crawl`'s ReAct loop,
via `chat_model_for("crawler")`) driving a fake-but-real-`StructuredTool`
Steel toolset.

Requires a live OpenRouter key. The operator's `.env` carries the OpenRouter
key under `OPENAI_API_KEY` (not `API_KEY_OPENROUTER`, which is what
`polymerhus.app.llm.providers` actually reads) - `_bridge_openrouter_env` below
does that one-time env-var rename for the test process only; nothing is
written back to `.env`.

Gated + skippable: skips outright when neither key env var is present, so it
never breaks the offline suite and never requires network by default.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from polymerhus.recon.control import pipeline
from polymerhus.recon.crawl import crawl_agent
from polymerhus.recon.crawl import crawl_pod as crawl_pod_module
from polymerhus.recon.crawl.crawl_pod import build_crawl_pod
from polymerhus.recon.domain.curator import ANCHOR_ALLOWLIST, curate
from polymerhus.recon.domain.pod import default_triage_fn
from polymerhus.recon.domain import pod as pod_module
from polymerhus.recon.domain.pod import build_pod_graph
from polymerhus.recon.domain.types import ExecResult

from tests.recon.test_pipeline_e2e import (
    FakeRegistry,
    InMemoryGraph,
    _build_pod_invoke,
    SUBFINDER_STDOUT,
    DNSX_STDOUT,
    HTTPX_STDOUT,
)

pytestmark = pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY_OPENROUTER")),
    reason="live LLM key required (OPENAI_API_KEY or API_KEY_OPENROUTER)",
)

# Cheap, reliably tool-calling + structured-output model (confirmed live
# ahead of writing this test - see sp4-livellm-e2e-report.md).
_LIVE_MODEL = os.environ.get("LIVE_LLM_MODEL", "openai/gpt-4o-mini")

# Keep the run bounded/cheap: small pod-iteration and crawl-iteration caps.
os.environ.setdefault("MAX_POD_ITERS", "2")
_CRAWL_MAX_ITERS = 6


def _bridge_openrouter_env():
    """Bridge the operator's `.env` OpenRouter key (stored as OPENAI_API_KEY)
    into the names `polymerhus.app.llm.providers` actually reads
    (`API_KEY_OPENROUTER` + `LLM_MODEL_<ROLE>="openrouter:<model>"`). Only
    touches this process's os.environ - never writes to .env."""
    key = os.environ.get("API_KEY_OPENROUTER") or os.environ.get("OPENAI_API_KEY")
    assert key, "no OpenRouter/OpenAI key found in env"
    os.environ["API_KEY_OPENROUTER"] = key
    for role in ("configurator", "triager", "job_orchestrator", "crawler"):
        os.environ[f"LLM_MODEL_{role.upper()}"] = f"openrouter:{_LIVE_MODEL}"


def fake_upstream_exec_fn(command: str, session_id: str, timeout_s: int) -> ExecResult:
    """Canned stdout for the deterministic upstream jobs (subfinder/dnsx/
    httpx) - identical fixtures to test_pipeline_e2e.py/test_crawl_e2e.py.
    httpx's output is deliberately "rich" (a healthy BaseURL with tech/TLS
    plus a 403'd BaseURL) so the real triager LLM has something concrete to
    reason about."""
    if command.startswith("subfinder"):
        stdout = SUBFINDER_STDOUT
    elif "dnsx" in command:
        stdout = DNSX_STDOUT
    elif command.startswith("httpx"):
        stdout = HTTPX_STDOUT
    else:
        raise AssertionError(f"unexpected command in live-LLM e2e test: {command!r}")
    return ExecResult(stdout=stdout, stderr="", returncode=0, duration_ms=1)


def _real_triager_only_on_httpx(raw_observations: list):
    """Wrap the REAL `default_triage_fn` so only the httpx job pays for a
    live LLM call (subfinder/dnsx stdout carries nothing worth triaging and
    would just burn API calls/cost for no signal). Every Observation the
    real LLM returns - accepted or later dropped by the curator's anchor
    allowlist - is appended to `raw_observations` for the test/report to
    inspect."""

    def triage_fn(exec_result: ExecResult, assets: list, job) -> list:
        if job.tool != "httpx":
            return []
        observations = default_triage_fn(exec_result, assets, job)
        raw_observations.extend(observations)
        return observations

    return triage_fn


# ---------------------------------------------------------------------------
# Real crawler LLM + a fake-but-real Steel toolset (langchain StructuredTool,
# not a bare stub) - the model actually has to emit valid tool-call JSON
# against a real `bind_tools` schema for these to be usable, exactly like the
# real Steel MCP tools it stands in for.
# ---------------------------------------------------------------------------

CANNED_MANIFEST = {
    "endpoints": [
        {
            "method": "GET",
            "url": "https://app.example.com/search?id=1",
            "query": ["id"],
            "body": [],
            "status": 200,
        },
    ],
    "js_urls": ["https://app.example.com/static/bundle.js"],
}


class _StartArgs(BaseModel):
    target: str
    scope: list[str] = Field(default_factory=list)
    user_id: str = ""
    max_depth: int = 3
    max_pages: int = 50


class _NavigateArgs(BaseModel):
    crawl_id: str
    url: str
    wait_ms: int = 800


class _FrontierArgs(BaseModel):
    crawl_id: str


class _FinishArgs(BaseModel):
    crawl_id: str


def _build_fake_steel_tools(manifest: dict, calls: dict[str, int]):
    """Fake Steel MCP toolset backed by real `StructuredTool`s so a real
    `ChatOpenAI.bind_tools([...])` produces genuine OpenAI-function-schema
    tool calls (a bare object with just `.name`/`.ainvoke`, as the older
    scripted-LLM tests use, does NOT round-trip through `bind_tools` against
    a real provider)."""

    async def start_fn(target: str, scope=None, user_id: str = "", max_depth: int = 3, max_pages: int = 50):
        calls["steel_crawl_start"] = calls.get("steel_crawl_start", 0) + 1
        return {"crawl_id": "c1", "viewer_url": ""}

    async def navigate_fn(crawl_id: str, url: str, wait_ms: int = 800):
        calls["steel_navigate"] = calls.get("steel_navigate", 0) + 1
        return {"new_links": [], "network_delta": []}

    async def frontier_fn(crawl_id: str):
        calls["steel_frontier"] = calls.get("steel_frontier", 0) + 1
        return {"frontier": []}

    async def finish_fn(crawl_id: str):
        calls["steel_crawl_finish"] = calls.get("steel_crawl_finish", 0) + 1
        return dict(manifest)

    return [
        StructuredTool.from_function(
            coroutine=start_fn, name="steel_crawl_start",
            description="Begin the crawl (call once, first).",
            args_schema=_StartArgs,
        ),
        StructuredTool.from_function(
            coroutine=navigate_fn, name="steel_navigate",
            description="Load a page from the frontier.",
            args_schema=_NavigateArgs,
        ),
        StructuredTool.from_function(
            coroutine=frontier_fn, name="steel_frontier",
            description="Re-check the current frontier.",
            args_schema=_FrontierArgs,
        ),
        StructuredTool.from_function(
            coroutine=finish_fn, name="steel_crawl_finish",
            description="End the crawl and emit the manifest. Always call this eventually.",
            args_schema=_FinishArgs,
        ),
    ]


def _run_crawl_fn_factory(tools):
    def run_crawl_fn(target: str, *, scope: list[str]) -> dict:
        # Real crawler LLM: llm=None so crawl_agent.run_crawl resolves it
        # itself via chat_model_for("crawler") - the actual production seam,
        # not a test-side substitute.
        return asyncio.run(
            crawl_agent.run_crawl(
                target, scope=scope, tools=tools, llm=None,
                model_role="crawler", max_iters=_CRAWL_MAX_ITERS,
            )
        )

    return run_crawl_fn


def test_full_stack_live_llm_happy_path():
    _bridge_openrouter_env()

    # --- 1. Smoke-check the bridged config before spending a full run's
    # worth of live calls: build the triager role and fire one trivial
    # prompt. If this fails (bad key/network/model), fail loudly and early
    # rather than let the real assertions below produce a confusing trace.
    from polymerhus.app.llm.roles import chat_model_for

    smoke = chat_model_for("triager").invoke("Reply with exactly the word: pong")
    assert "pong" in smoke.content.lower(), (
        f"OpenRouter smoke-check failed: expected 'pong', got {smoke.content!r}"
    )

    graph = InMemoryGraph()

    def curate_fn(assets, observations, project_id, scope_domain=None):
        return curate(assets, observations, project_id,
                      merge_fn=graph.merge_fn, scope_domain=scope_domain)

    raw_triager_observations: list = []
    deterministic_pod_graph = build_pod_graph(
        exec_fn=fake_upstream_exec_fn,
        curate_fn=curate_fn,
        triage_fn=_real_triager_only_on_httpx(raw_triager_observations),
    )

    steel_calls: dict[str, int] = {}
    steel_tools = _build_fake_steel_tools(CANNED_MANIFEST, steel_calls)
    crawl_pod_fixture = build_crawl_pod(
        run_crawl_fn=_run_crawl_fn_factory(steel_tools),
        parse_fn=__import__(
            "polymerhus.recon.domain.parsers.steel_parser", fromlist=["parse"]
        ).parse,
        triage_fn=lambda exec_result, assets, job: [],  # crawl-pod's own post-crawl triage stays deterministic
        curate_fn=curate_fn,
    )

    original_pod_graph = pod_module.pod_graph
    original_crawl_pod = crawl_pod_module.crawl_pod
    pod_module.pod_graph = deterministic_pod_graph
    crawl_pod_module.crawl_pod = crawl_pod_fixture
    try:
        registry = FakeRegistry()

        def load_settings(project_id):
            return {"target_domain": "app.example.com"}

        asyncio.run(
            pipeline.run_pipeline(
                "proj-live-llm-e2e",
                run_id="run-live-llm-e2e",
                job_subset=["subfinder", "dnsx", "httpx", "steel_crawl"],
                run_job=None,  # real polymerhus.recon.control.job_agent.run_job -> real default_pod_invoke dispatch
                load_settings=load_settings,
                registry=registry,
                read_assets=graph.read_assets,
            )
        )
    finally:
        pod_module.pod_graph = original_pod_graph
        crawl_pod_module.crawl_pod = original_crawl_pod

    final_status = {call["job"]: call["status"] for call in registry.upsert_job_calls}

    # --- report-friendly dump (visible with `-s`) ---
    print(f"\n[live-llm-e2e] model={_LIVE_MODEL}")
    print(f"[live-llm-e2e] final job statuses: {final_status}")
    print(f"[live-llm-e2e] steel tool call counts: {steel_calls}")
    print(f"[live-llm-e2e] raw triager observations ({len(raw_triager_observations)}):")
    for obs in raw_triager_observations:
        anchor_ok = obs.anchor.get("type") in ANCHOR_ALLOWLIST
        print(f"    - macro_kind={obs.macro_kind!r} anchor={obs.anchor!r} "
              f"{'ACCEPTED' if anchor_ok else 'DROPPED (anchor not in allowlist)'}")

    # --- 2. Pipeline reached its terminal "complete" state.
    assert registry.set_run_status_calls[-1] == ("run-live-llm-e2e", "complete", None)
    assert final_status["subfinder"] == "success"
    assert final_status["dnsx"] == "success"
    assert final_status["httpx"] == "success"

    # --- 3. The real crawler LLM actually drove the ReAct loop to
    # completion (not a degrade-to-empty-manifest): it must have called
    # steel_crawl_start and steel_crawl_finish at least once, and the job
    # must have recorded "success" (build_crawl_pod only reaches "success"
    # via a non-empty manifest).
    assert steel_calls.get("steel_crawl_start", 0) >= 1, "crawler LLM never called steel_crawl_start"
    assert steel_calls.get("steel_crawl_finish", 0) >= 1, "crawler LLM never called steel_crawl_finish"
    assert final_status["steel_crawl"] == "success", (
        f"crawl pod degraded instead of completing: {final_status}"
    )

    # --- 4. The canned manifest's endpoint/param/js reached the curator as
    # real BaseURL/Endpoint/Parameter merges (same structural check as
    # test_crawl_e2e.py, just fed by a real LLM this time).
    cyphers = [cy for cy, _ in graph.merges]
    assert any(":BaseURL" in cy for cy in cyphers)
    assert any(":Endpoint" in cy for cy in cyphers)
    assert any(":Parameter" in cy for cy in cyphers)
    assert any(":Subdomain" in cy for cy in cyphers)  # subfinder
    assert any(":IP" in cy for cy in cyphers)  # dnsx

    # --- 5. The real triager LLM produced at least one well-formed
    # Observation with a valid broad anchor (Domain/Subdomain/BaseURL/IP/
    # Service) that the curator actually accepted (reached a MERGE, not
    # dropped). Assert STRUCTURE, not exact text - LLMs are nondeterministic.
    assert raw_triager_observations, "real triager LLM produced zero Observations on httpx's rich output"
    for obs in raw_triager_observations:
        assert obs.macro_kind and obs.severity and obs.evidence and obs.rationale
        assert obs.anchor.get("type") and obs.anchor.get("identity")
        assert obs.source_job and obs.source_tool

    observation_merges = [
        (cy, params) for cy, params in graph.merges
        if cy.splitlines()[0].startswith("MERGE (a:") and "Observation" in cy
    ]
    accepted_anchor_types = {
        cy.splitlines()[0].split("(a:")[1].split(" ")[0] for cy, _ in observation_merges
    }
    assert observation_merges, (
        "no Observation was accepted by the curator - either the real triager LLM "
        "produced nothing, or every Observation anchored on a type outside "
        f"ANCHOR_ALLOWLIST={sorted(ANCHOR_ALLOWLIST)} (raw: "
        f"{[o.anchor for o in raw_triager_observations]!r})"
    )
    assert accepted_anchor_types <= ANCHOR_ALLOWLIST
