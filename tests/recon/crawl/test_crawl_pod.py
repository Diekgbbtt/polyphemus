"""Crawl-pod variant: crawl -> parse -> triager -> curator.

Fully mocked - no live Steel/LLM/Neo4j. `run_crawl_fn`, `triage_fn`, and
`curate_fn` are injected fakes; `parse_fn` is the real `steel_parser.parse`
(pure, deterministic) so the assertion actually exercises the manifest ->
AssetDelta decomposition end to end.
"""
import json

from agent.recon.crawl import crawl_pod
from agent.recon.crawl.steel_client import SteelNotConfigured
from agent.recon.parsers.steel_parser import parse as steel_parse
from agent.recon.types import JobSpec

STEEL_CRAWL_JOB = JobSpec(
    tool="steel_crawl",
    skill="agentic_crawl",
    command_template="",
    produces=["BaseURL", "Endpoint", "Parameter"],
    consumes="BaseURL",
    use_auth=True,
    configurator_mode="agent",
)

CANNED_MANIFEST = {
    "endpoints": [
        {"method": "GET", "url": "https://app.example.com/search?id=1", "query": ["id"], "body": [], "status": 200},
        {"method": "POST", "url": "https://app.example.com/login", "query": [], "body": ["username"], "status": 200},
    ],
    "js_urls": ["https://app.example.com/static/bundle.js"],
}


def make_capturing_curate_fn():
    calls = []

    def curate_fn(assets, observations, project_id):
        calls.append({"assets": assets, "observations": observations, "project_id": project_id})
        return len(assets), len(observations)

    curate_fn.calls = calls
    return curate_fn


def base_pod_state(extra=None):
    return {
        "job": STEEL_CRAWL_JOB,
        "input_asset": {"url": "https://app.example.com"},
        "asset_context": "",
        "extra": extra or {},
        "session_id": "run1-4-steel_crawl-abcd1234",
        "project_id": "proj-1",
    }


def test_crawl_pod_success_merges_baseurl_endpoint_parameter():
    def run_crawl_fn(target, *, scope):
        assert target == "https://app.example.com"
        assert scope == [target]
        return dict(CANNED_MANIFEST)

    curate_fn = make_capturing_curate_fn()
    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=curate_fn,
    )

    result = pod.invoke(base_pod_state())
    export = result["export"]

    assert export.verdict == "success"
    assert len(curate_fn.calls) == 1
    assets = curate_fn.calls[0]["assets"]
    types = {a.type for a in assets}
    assert types == {"BaseURL", "Endpoint", "Parameter"}
    assert export.assets_merged == len(assets)


def test_crawl_pod_steel_not_configured_yields_failed_export_and_coverage_observation():
    def run_crawl_fn(target, *, scope):
        raise SteelNotConfigured("STEEL_API_KEY (steel.dev credential) must be set")

    curate_fn = make_capturing_curate_fn()
    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=curate_fn,
    )

    result = pod.invoke(base_pod_state())
    export = result["export"]

    assert export.verdict == "failed"
    assert len(curate_fn.calls) == 1
    observations = curate_fn.calls[0]["observations"]
    assert len(observations) == 1
    obs = observations[0]
    assert obs.macro_kind == "reduced_crawl_coverage"
    assert obs.severity == "info"
    assert obs.anchor == {"type": "BaseURL", "identity": {"url": "https://app.example.com"}}


def test_crawl_pod_generic_exception_yields_failed_export_no_crash():
    def run_crawl_fn(target, *, scope):
        raise RuntimeError("boom")

    curate_fn = make_capturing_curate_fn()
    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=curate_fn,
    )

    result = pod.invoke(base_pod_state())
    export = result["export"]

    assert export.verdict == "failed"
    observations = curate_fn.calls[0]["observations"]
    assert observations[0].macro_kind == "reduced_crawl_coverage"


def test_crawl_pod_empty_manifest_yields_failed_export():
    def run_crawl_fn(target, *, scope):
        return {"endpoints": [], "js_urls": []}

    curate_fn = make_capturing_curate_fn()
    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=curate_fn,
    )

    result = pod.invoke(base_pod_state())
    export = result["export"]

    assert export.verdict == "failed"
    assert export.error == "empty crawl manifest"


def test_crawl_pod_invoke_builds_pod_state_and_scopes_project_id(monkeypatch):
    captured = {}

    class FakeCrawlPod:
        def invoke(self, state):
            captured.update(state)
            from agent.recon.types import PodExport
            return {"export": PodExport(input_asset=state["input_asset"], verdict="success")}

    monkeypatch.setattr(crawl_pod, "crawl_pod", FakeCrawlPod())

    pod_input = {
        "input_asset": {"url": "https://app.example.com"},
        "asset_context": "",
        "extra": {"project_id": "proj-42"},
    }
    export = crawl_pod.crawl_pod_invoke(pod_input, STEEL_CRAWL_JOB, run_id="run-9", phase=4)

    assert export.verdict == "success"
    assert captured["project_id"] == "proj-42"
    assert captured["input_asset"] == {"url": "https://app.example.com"}
    assert captured["job"] is STEEL_CRAWL_JOB


def test_default_crawl_pod_module_level_instance_is_import_safe():
    assert crawl_pod.crawl_pod is not None
    assert callable(crawl_pod.crawl_pod_invoke)
    assert callable(crawl_pod.default_run_crawl_fn)
