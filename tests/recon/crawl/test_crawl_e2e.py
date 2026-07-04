"""End-to-end agentic-crawl integration test (Sub-plan 4 Task 6).

Wires the REAL crawl pod (`agent.recon.crawl.crawl_pod.build_crawl_pod`) ->
REAL steel parser (`agent.recon.parsers.steel_parser.parse`) -> REAL curator
(`agent.recon.curator.curate`, captured in-memory) -> REAL
`agent.recon.job_agent`/`agent.recon.pipeline` dispatch, exactly mirroring
`tests/recon/test_pipeline_e2e.py`'s pattern for the deterministic-tool
chain, but extended one phase into the `steel_crawl` (`configurator_mode
== "agent"`) job.

The ONLY fakes are:
  * the Steel MCP toolset (`_FakeTool`s, mirroring `test_crawl_agent.py`) -
    the crawl loop's real `_run_agentic_crawl` drives them via a scripted
    tool-call sequence;
  * the crawler LLM (`_ScriptedLLM`, same fake as `test_crawl_agent.py`);
  * the triager LLM (fixed to `[]`, same convention as `test_pipeline_e2e.py`);
  * Neo4j (`InMemoryGraph`, imported from `test_pipeline_e2e.py`), the
    Postgres registry (`FakeRegistry`), and tool exec for the upstream
    subfinder/dnsx/httpx jobs whose real output is what actually produces
    the BaseURL that `read_assets` feeds `steel_crawl` (identical fixture
    reuse to `test_pipeline_e2e.py`'s arjun extension - `steel_crawl`
    consumes `BaseURL` just like `arjun` consumes `Endpoint`, so the same
    real curate() -> read_assets() seam is exercised, not a stub).

`run_crawl_fn`, wired into a `build_crawl_pod` instance, calls the REAL
`agent.recon.crawl.crawl_agent.run_crawl` ReAct loop synchronously with the
fake `tools`/`llm` injected - so the real bounded tool-call loop, not just
its return value, is exercised end to end. Both the crawl-pod's and the
deterministic pod's module-level compiled graphs are monkeypatched (same
technique as `test_crawl_pod.py::test_crawl_pod_invoke_builds_pod_state_and_scopes_project_id`)
so `job_agent.default_pod_invoke`'s real `configurator_mode` branch - the
seam this task exists to exercise - runs completely unmodified.
"""
from __future__ import annotations

import asyncio
import json

from agent.recon import pipeline
from agent.recon.crawl import crawl_agent
from agent.recon.crawl import crawl_pod as crawl_pod_module
from agent.recon.crawl.crawl_pod import build_crawl_pod
from agent.recon.curator import curate
from agent.recon.job_agent import default_preprocess_fn, run_job as real_run_job
from agent.recon.parsers.steel_parser import parse as steel_parse
from agent.recon import pod as pod_module
from agent.recon.pod import build_pod_graph
from agent.recon.types import ExecResult

from tests.recon.test_pipeline_e2e import (
    FakeRegistry,
    InMemoryGraph,
    _build_pod_invoke,
    fake_triage_fn,
    SUBFINDER_STDOUT,
    DNSX_STDOUT,
    HTTPX_STDOUT,
)


def fake_upstream_exec_fn(command: str, session_id: str, timeout_s: int) -> ExecResult:
    """Real tool exec for the upstream subfinder/dnsx/httpx jobs whose real
    BaseURL output is what feeds `steel_crawl` via `read_assets` - the same
    canned fixtures `test_pipeline_e2e.py` uses. `steel_crawl` itself never
    calls this (its `command_template` is empty; it never reaches
    `pod.py`'s exec node)."""
    if command.startswith("subfinder"):
        stdout = SUBFINDER_STDOUT
    elif "dnsx" in command:
        stdout = DNSX_STDOUT
    elif command.startswith("httpx"):
        stdout = HTTPX_STDOUT
    else:
        raise AssertionError(f"unexpected command in crawl e2e test: {command!r}")
    return ExecResult(stdout=stdout, stderr="", returncode=0, duration_ms=1)


class _AIMessage:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


class _ScriptedLLM:
    """Fake crawler LLM: scripted tool-call batches, mirroring
    `test_crawl_agent.py`'s fake."""

    def __init__(self, script):
        self.script = list(script)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        tool_calls = self.script.pop(0) if self.script else []
        return _AIMessage(tool_calls)


class _FakeTool:
    def __init__(self, name, result):
        self.name = name
        self._result = result

    async def ainvoke(self, args):
        return self._result


# One endpoint with a query param, one js_url - per the brief's canned
# manifest shape.
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


def _fake_steel_tools_and_llm(manifest: dict):
    tools = [
        _FakeTool("steel_crawl_start", {"crawl_id": "c1"}),
        _FakeTool("steel_crawl_finish", manifest),
    ]
    llm = _ScriptedLLM(
        [
            [{"name": "steel_crawl_start", "args": {}, "id": "1"}],
            [{"name": "steel_crawl_finish", "args": {}, "id": "2"}],
        ]
    )
    return tools, llm


def _looping_steel_tools_and_llm():
    """A crawler LLM that never calls `steel_crawl_finish` - the loop drains
    to the empty manifest bounded by `max_iters`, exercising the Steel
    degrade-gracefully path without needing `SteelNotConfigured`."""
    tools = [_FakeTool("steel_navigate", {"new_links": [], "network_delta": []})]

    class _LoopingLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            return _AIMessage([{"name": "steel_navigate", "args": {}, "id": "n"}])

    return tools, _LoopingLLM()


def _run_crawl_fn_factory(tools, llm):
    def run_crawl_fn(target: str, *, scope: list[str]) -> dict:
        return asyncio.run(
            crawl_agent.run_crawl(target, scope=scope, tools=tools, llm=llm, max_iters=5)
        )

    return run_crawl_fn


def _run_recon_pipeline(*, crawl_tools, crawl_llm):
    """Shared harness: real subfinder->dnsx->httpx->steel_crawl chain, the
    only variable between the success/degraded tests is the fake Steel
    tools/LLM passed in."""
    graph = InMemoryGraph()

    def curate_fn(assets, observations, project_id):
        return curate(assets, observations, project_id, merge_fn=graph.merge_fn)

    deterministic_pod_graph = build_pod_graph(
        exec_fn=fake_upstream_exec_fn, curate_fn=curate_fn, triage_fn=fake_triage_fn
    )

    crawl_pod_fixture = build_crawl_pod(
        run_crawl_fn=_run_crawl_fn_factory(crawl_tools, crawl_llm),
        parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=curate_fn,
    )

    # Monkeypatch the module-level compiled-graph singletons so the REAL
    # `job_agent.default_pod_invoke` dispatch (which imports `pod_graph`/
    # `crawl_pod` fresh on each call) routes to our instrumented fixtures
    # without touching any of its own branching logic.
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
                "proj-crawl-e2e",
                run_id="run-crawl-e2e",
                job_subset=["subfinder", "dnsx", "httpx", "steel_crawl"],
                run_job=None,  # real agent.recon.job_agent.run_job -> real default_pod_invoke dispatch
                load_settings=load_settings,
                registry=registry,
                read_assets=graph.read_assets,
            )
        )
    finally:
        pod_module.pod_graph = original_pod_graph
        crawl_pod_module.crawl_pod = original_crawl_pod

    return graph, registry


def test_crawl_e2e_success_dispatches_to_crawl_pod_and_merges_manifest():
    tools, llm = _fake_steel_tools_and_llm(CANNED_MANIFEST)
    graph, registry = _run_recon_pipeline(crawl_tools=tools, crawl_llm=llm)

    final_status = {call["job"]: call["status"] for call in registry.upsert_job_calls}

    # 1. steel_crawl dispatched through the CRAWL pod (configurator_mode ==
    # "agent" routing), not the deterministic template pod: only the crawl
    # pod's fake steel tools could have produced the manifest's BaseURL/
    # Endpoint/Parameter merges below, and the job recorded success - a
    # dispatch mismatch (e.g. routed to the template pod, which has no
    # command_template to fill) would have raised/degraded instead.
    assert final_status["steel_crawl"] == "success"

    # 2. The manifest's endpoint + query param + js_url reached the curator
    # as BaseURL/Endpoint/Parameter merges.
    cyphers = [cy for cy, _ in graph.merges]
    assert any(":BaseURL" in cy for cy in cyphers)
    assert any(":Endpoint" in cy for cy in cyphers)
    assert any(":Parameter" in cy for cy in cyphers)

    endpoint_merges = [
        params for cy, params in graph.merges if cy.splitlines()[0].startswith("MERGE (n:Endpoint")
    ]
    assert any(params.get("id_path") == "/search" for params in endpoint_merges)
    assert any(params.get("id_baseurl") == "https://app.example.com" for params in endpoint_merges)
    assert any(
        params.get("props", {}).get("source") == "steel-js" for params in endpoint_merges
    )

    param_merges = [
        params for cy, params in graph.merges if cy.splitlines()[0].startswith("MERGE (n:Parameter")
    ]
    assert any(params.get("id_name") == "id" and params.get("id_position") == "query" for params in param_merges)

    # 3. The pipeline reached its terminal "complete" state.
    assert registry.set_run_status_calls[-1] == ("run-crawl-e2e", "complete", None)
    assert final_status["subfinder"] == "success"
    assert final_status["dnsx"] == "success"
    assert final_status["httpx"] == "success"


def test_crawl_e2e_empty_manifest_degrades_job_but_pipeline_completes():
    tools, llm = _looping_steel_tools_and_llm()
    graph, registry = _run_recon_pipeline(crawl_tools=tools, crawl_llm=llm)

    final_status = {call["job"]: call["status"] for call in registry.upsert_job_calls}

    # 4. The Steel-unconfigured / empty-manifest path: the crawl pod exports
    # a "failed" verdict + a reduced_crawl_coverage Observation, which the
    # pipeline (all pods failed -> failed == total) records as job
    # "degraded" - the run still completes.
    assert final_status["steel_crawl"] == "degraded"
    assert registry.set_run_status_calls[-1] == ("run-crawl-e2e", "complete", None)

    observation_cyphers = [
        (cy, params) for cy, params in graph.merges if "Observation" in cy
    ]
    assert observation_cyphers, "expected a reduced_crawl_coverage Observation merge"
    assert any(
        params.get("macro_kind") == "reduced_crawl_coverage"
        for _, params in observation_cyphers
    )

    # The unrelated upstream jobs still succeeded - one job's degradation
    # never aborts the run.
    assert final_status["subfinder"] == "success"
    assert final_status["dnsx"] == "success"
    assert final_status["httpx"] == "success"
