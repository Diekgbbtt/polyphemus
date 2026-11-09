"""Crawl-pod variant: crawl -> parse -> triager -> curator.

Fully mocked - no live Steel/LLM/Neo4j. `run_crawl_fn`, `triage_fn`, and
`curate_fn` are injected fakes; `parse_fn` is the real `steel_parser.parse`
(pure, deterministic) so the assertion actually exercises the manifest ->
AssetDelta decomposition end to end.
"""
import json

from polymerhus.recon.crawl import crawl_pod
from polymerhus.recon.domain.parsers.steel_parser import parse as steel_parse
from polymerhus.recon.domain.types import JobSpec

STEEL_CRAWL_JOB = JobSpec(
    tool="steel_crawl",
    skill="steel_crawl",
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

    def curate_fn(assets, observations, project_id, scope_domain=None):
        calls.append({
            "assets": assets,
            "observations": observations,
            "project_id": project_id,
            "scope_domain": scope_domain,
        })
        return len(assets), len(observations), assets, observations

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
    def run_crawl_fn(target, *, scope, browser_context_ref=None, browser_auth=None):
        assert target == "https://app.example.com"
        # scope is folded to the registrable domain of the seed host (Change A)
        assert scope == ["example.com"]
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


def test_crawl_pod_generic_exception_yields_failed_export_no_crash():
    def run_crawl_fn(target, *, scope, browser_context_ref=None, browser_auth=None):
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


def test_crawl_pod_partial_v2_manifest_keeps_its_surface():
    """A partial crawl is evidence with reduced coverage, not a failed crawl.

    Iteration E captured 111 endpoints and 11 parameters but hit the session
    deadline. The old partial branch returned `manifest: None`, so the fail
    node discarded every one of them. The partial path must parse the captured
    surface and attach the reduced-coverage observation beside it.
    """
    partial = {
        "schema_version": "steel-crawl/v2",
        "run": {"stop_reason": "session_deadline", "partial": True},
        "endpoints": [
            {
                "endpoint_id": "ep_1",
                "method": "GET",
                "url": "https://app.example.com/one",
                "path": "/one",
            }
        ],
        "parameters": [
            {
                "name": "q",
                "position": "query",
                "endpoint_id": "ep_1",
                "endpoint_path": "/one",
                "baseurl": "https://app.example.com",
            }
        ],
        "stats": {"flows": 1},
    }

    def run_crawl_fn(target, *, scope, browser_context_ref=None, browser_auth=None):
        return dict(partial)

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
    assert export.error is None
    assets = curate_fn.calls[0]["assets"]
    assert {asset.type for asset in assets} == {"BaseURL", "Endpoint", "Parameter"}
    assert export.assets_merged == len(assets)
    observations = curate_fn.calls[0]["observations"]
    coverage = [
        observation
        for observation in observations
        if observation.macro_kind == "reduced_crawl_coverage"
    ]
    assert len(coverage) == 1
    assert coverage[0].evidence.endswith("session_deadline")


def _dedupe_curate_fn():
    calls = []

    def curate_fn(assets, observations, project_id, scope_domain=None):
        unique_assets = []
        seen_assets = set()
        for asset in assets:
            key = json.dumps(
                {"type": asset.type, "identity": asset.identity},
                sort_keys=True,
                default=str,
            )
            if key not in seen_assets:
                seen_assets.add(key)
                unique_assets.append(asset)
        unique_observations = []
        seen_observations = set()
        for observation in observations:
            key = (
                observation.macro_kind,
                observation.evidence,
                json.dumps(observation.anchor, sort_keys=True, default=str),
            )
            if key not in seen_observations:
                seen_observations.add(key)
                unique_observations.append(observation)
        calls.append(
            {
                "assets": unique_assets,
                "observations": unique_observations,
            }
        )
        return (
            len(unique_assets),
            len(unique_observations),
            unique_assets,
            unique_observations,
        )

    curate_fn.calls = calls
    return curate_fn


def _session_manifest(urls, *, account, role, partial=False):
    return {
        "schema_version": "steel-crawl/v2",
        "run": {
            "account": account,
            "role": role,
            "stop_reason": "session_deadline" if partial else "frontier_empty",
            "partial": partial,
        },
        "endpoints": [
            {"method": "GET", "url": url, "path": url.split("://", 1)[1].split("/", 1)[1]}
            for url in urls
        ],
        "stats": {"flows": 1},
    }


def test_crawl_pod_ingests_every_session_and_records_failures():
    batch = {
        "manifests": [
            _session_manifest(
                ["https://app.example.com/one"],
                account="admin",
                role="admin",
            ),
            _session_manifest(
                [
                    "https://app.example.com/one",
                    "https://app.example.com/two",
                ],
                account="member",
                role="member",
            ),
        ],
        "sessions": [
            {"account": "admin", "role": "admin", "error": None},
            {"account": "member", "role": "member", "error": None},
            {
                "account": "broken",
                "role": "auditor",
                "error": "auth_precondition_failed",
            },
        ],
    }

    def run_crawl_fn(target, *, scope, browser_context_ref=None, browser_auth=None):
        return batch

    curate_fn = _dedupe_curate_fn()
    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=curate_fn,
    )

    result = pod.invoke(base_pod_state())
    export = result["export"]

    assert export.verdict == "success"
    assets = curate_fn.calls[0]["assets"]
    endpoints = [asset for asset in assets if asset.type == "Endpoint"]
    paths = [asset.identity["path"] for asset in endpoints]
    assert paths.count("/one") == 1
    assert paths.count("/two") == 1
    coverage = [
        observation
        for observation in curate_fn.calls[0]["observations"]
        if observation.macro_kind == "reduced_crawl_coverage"
    ]
    assert len(coverage) == 1
    assert "auditor: auth_precondition_failed" in coverage[0].evidence


def test_crawl_pod_complete_v2_manifest_is_not_reduced():
    complete = {
        "schema_version": "steel-crawl/v2",
        "run": {"stop_reason": "frontier_empty", "partial": False},
        "endpoints": [
            {"method": "GET", "url": "https://app.example.com/one", "path": "/one"}
        ],
        "stats": {"flows": 1},
    }

    def run_crawl_fn(target, *, scope, browser_context_ref=None, browser_auth=None):
        return dict(complete)

    curate_fn = make_capturing_curate_fn()
    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=curate_fn,
    )

    result = pod.invoke(base_pod_state())

    assert result["export"].verdict == "success"


def test_crawl_pod_empty_manifest_yields_failed_export():
    def run_crawl_fn(target, *, scope, browser_context_ref=None, browser_auth=None):
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
        def invoke(self, state, config=None):
            captured.update(state)
            from polymerhus.recon.domain.types import PodExport
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


def test_crawl_scope_folds_to_registrable_domain_of_seed_host():
    """Change A: scope entries are folded to the registrable domain of the
    seed host, so the crawl frontier admits any subdomain of it."""
    from polymerhus.recon.crawl.crawl_pod import build_crawl_pod
    from polymerhus.recon.domain.types import JobSpec

    captured = {}

    def run_crawl_fn(target, *, scope, browser_context_ref=None, browser_auth=None):
        captured["target"] = target
        captured["scope"] = scope
        return dict(CANNED_MANIFEST)

    graph = build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda s: [],
        triage_fn=lambda e, a, j: [],
        curate_fn=lambda a, o, pid, **k: (0, 0, [], []),
    )
    job = JobSpec(tool="steel_crawl", skill="steel_crawl", command_template="",
                  produces=["BaseURL"], consumes="BaseURL", use_auth=False,
                  configurator_mode="agent")
    # Anonymous path: no auth_context signal.
    state = {"job": job, "input_asset": {"url": "https://app.daytona.io"},
             "extra": {}, "project_id": "p1", "run_id": "r", "phase": 4}
    graph.invoke(state)
    assert captured["target"] == "https://app.daytona.io"
    assert captured["scope"] == ["daytona.io"]


def test_curator_threads_registrable_scope_domain_to_curate_fn():
    """D14/D15 at the crawl curator: the curator node must thread the SAME
    registrable-domain scope the crawl frontier uses as `scope_domain` into
    `curate_fn`, so out-of-scope BaseURLs (js.stripe.com, *.auth0.com, ...)
    are dropped by the agnostic noise filter. For target app.daytona.io the
    threaded scope_domain is the registrable domain daytona.io."""
    def run_crawl_fn(target, *, scope, browser_context_ref=None, browser_auth=None):
        return dict(CANNED_MANIFEST)

    curate_fn = make_capturing_curate_fn()
    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=curate_fn,
    )

    state = base_pod_state()
    state["input_asset"] = {"url": "https://app.daytona.io"}
    result = pod.invoke(state)
    export = result["export"]

    assert export.verdict == "success"
    assert len(curate_fn.calls) == 1
    assert curate_fn.calls[0]["scope_domain"] == "daytona.io"


def test_crawl_node_forwards_browser_auth():
    """The gate metadata rides into run_crawl_fn - no interactive path, no
    prompt, and no retired state-file plumbing."""
    from polymerhus.recon.crawl.crawl_pod import build_crawl_pod
    from polymerhus.recon.domain.types import JobSpec

    seen = {}

    def run_crawl_fn(target, *, scope, browser_auth=None):
        seen["browser_auth"] = browser_auth
        return dict(CANNED_MANIFEST)

    graph = build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda s: [],
        triage_fn=lambda e, a, j: [],
        curate_fn=lambda a, o, pid, **k: (0, 0, [], []),
    )
    job = JobSpec(tool="steel_crawl", skill="steel_crawl", command_template="",
                  produces=["BaseURL"], consumes="BaseURL", use_auth=True,
                  configurator_mode="agent")
    material = {"auth_probe": "https://app.test/api/me",
                "login_url": "https://app.test/login"}
    state = {"job": job, "input_asset": {"url": "https://app.example.com"},
             "extra": {"browser_auth": material},
             "project_id": "p1"}
    result = graph.invoke(state)
    assert seen["browser_auth"] == material
    assert "browser_context_ref" not in seen
    assert result["export"].verdict == "success"
