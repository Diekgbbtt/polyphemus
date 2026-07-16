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

    def curate_fn(assets, observations, project_id, scope_domain=None):
        calls.append({
            "assets": assets,
            "observations": observations,
            "project_id": project_id,
            "scope_domain": scope_domain,
        })
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
        def invoke(self, state, config=None):
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


def test_crawl_pod_fires_notify_on_awaiting_auth():
    from agent.recon.crawl.crawl_pod import build_crawl_pod
    from agent.recon.types import JobSpec

    notified = []

    def fake_run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        on_awaiting_auth({"viewer_url": "https://app.steel.dev/sessions/xyz"})
        return {"pages": [{"url": target}]}, {"viewer_url": "https://app.steel.dev/sessions/xyz"}

    graph = build_crawl_pod(
        run_crawl_fn=lambda *a, **k: {"pages": []},
        parse_fn=lambda s: [],
        triage_fn=lambda e, a, j: [],
        curate_fn=lambda a, o, pid, **k: (0, 0),
        run_crawl_authenticated_fn=fake_run_crawl_authenticated_fn,
        status_sink=lambda *a, **k: None,
        notify_fn=lambda run_id, phase, job, vu: notified.append((run_id, phase, job, vu)),
    )
    job = JobSpec(tool="steel_crawl", skill="agentic_crawl", command_template="",
                  produces=["BaseURL"], consumes="BaseURL", use_auth=True,
                  configurator_mode="agent")
    state = {"job": job, "input_asset": {"url": "https://t.example.com"},
             "extra": {"auth_context": {"cookies": []}}, "project_id": "p1",
             "run_id": "run-1", "phase": 4}
    graph.invoke(state)
    assert notified == [("run-1", 4, "steel_crawl", "https://app.steel.dev/sessions/xyz")]


def test_credentials_apply_to_target_gates_on_host():
    from agent.recon.crawl.crawl_pod import credentials_apply_to_target
    creds = {"login_url": "https://login.example.com/", "domain": "example.com"}
    assert credentials_apply_to_target(creds, "https://app.example.com") is True
    assert credentials_apply_to_target(creds, "https://other.org") is False
    # no explicit domain -> fall back to the login_url host's registrable domain
    assert credentials_apply_to_target({"login_url": "https://login.example.com/"},
                                       "https://app.example.com") is True


def test_crawl_scope_folds_to_registrable_domain_of_seed_host():
    """Change A: scope entries are folded to the registrable domain of the
    seed host, so the crawl frontier admits any subdomain of it."""
    from agent.recon.crawl.crawl_pod import build_crawl_pod
    from agent.recon.types import JobSpec

    captured = {}

    def run_crawl_fn(target, *, scope):
        captured["target"] = target
        captured["scope"] = scope
        return dict(CANNED_MANIFEST)

    graph = build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda s: [],
        triage_fn=lambda e, a, j: [],
        curate_fn=lambda a, o, pid, **k: (0, 0),
    )
    job = JobSpec(tool="steel_crawl", skill="agentic_crawl", command_template="",
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
    def run_crawl_fn(target, *, scope):
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


def test_crawl_node_falls_back_to_anonymous_when_credentials_off_target():
    """Change C: credentials present but for a DIFFERENT registrable domain
    (and no cookies) must fall through to the anonymous run_crawl_fn, not
    block on the interactive human-viewer path."""
    from agent.recon.crawl.crawl_pod import build_crawl_pod
    from agent.recon.types import JobSpec

    anon_called = {}
    interactive_called = {"hit": False}

    def run_crawl_fn(target, *, scope):
        anon_called["target"] = target
        anon_called["scope"] = scope
        return dict(CANNED_MANIFEST)

    def run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        interactive_called["hit"] = True
        return dict(CANNED_MANIFEST), None

    graph = build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda s: [],
        triage_fn=lambda e, a, j: [],
        curate_fn=lambda a, o, pid, **k: (0, 0),
        run_crawl_authenticated_fn=run_crawl_authenticated_fn,
    )
    job = JobSpec(tool="steel_crawl", skill="agentic_crawl", command_template="",
                  produces=["BaseURL"], consumes="BaseURL", use_auth=True,
                  configurator_mode="agent")
    state = {"job": job, "input_asset": {"url": "https://app.daytona.io"},
             "extra": {"auth_context": {"credentials": {
                 "username": "u", "password": "pw",
                 "login_url": "https://login.example.com/", "domain": "example.com"}}},
             "project_id": "p1", "run_id": "r", "phase": 4}
    graph.invoke(state)
    assert anon_called["target"] == "https://app.daytona.io"
    assert interactive_called["hit"] is False


def test_crawl_node_takes_interactive_path_with_no_credentials():
    """Change C (unchanged behavior): use_auth signalled with NO credentials
    and NO cookies still runs the interactive human-viewer path."""
    from agent.recon.crawl.crawl_pod import build_crawl_pod
    from agent.recon.types import JobSpec

    interactive_called = {"hit": False}
    anon_called = {"hit": False}

    def run_crawl_fn(target, *, scope):
        anon_called["hit"] = True
        return dict(CANNED_MANIFEST)

    def run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        interactive_called["hit"] = True
        return dict(CANNED_MANIFEST), None

    graph = build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda s: [],
        triage_fn=lambda e, a, j: [],
        curate_fn=lambda a, o, pid, **k: (0, 0),
        run_crawl_authenticated_fn=run_crawl_authenticated_fn,
    )
    job = JobSpec(tool="steel_crawl", skill="agentic_crawl", command_template="",
                  produces=["BaseURL"], consumes="BaseURL", use_auth=True,
                  configurator_mode="agent")
    state = {"job": job, "input_asset": {"url": "https://app.daytona.io"},
             "extra": {"auth_context": {"cookies": []}},
             "project_id": "p1", "run_id": "r", "phase": 4}
    graph.invoke(state)
    assert interactive_called["hit"] is True
    assert anon_called["hit"] is False


def test_crawl_node_takes_credentialed_path_for_matching_host():
    from agent.recon.crawl.crawl_pod import build_crawl_pod
    from agent.recon.types import JobSpec

    called = {}

    graph = build_crawl_pod(
        run_crawl_fn=lambda *a, **k: {"pages": []},
        parse_fn=lambda s: [],
        triage_fn=lambda e, a, j: [],
        curate_fn=lambda a, o, pid, **k: (0, 0),
        run_crawl_credentialed_fn=lambda target, scope, credentials: called.update(
            target=target, credentials=credentials) or {"pages": [{"url": target}]},
    )
    job = JobSpec(tool="steel_crawl", skill="agentic_crawl", command_template="",
                  produces=["BaseURL"], consumes="BaseURL", use_auth=True, configurator_mode="agent")
    state = {"job": job, "input_asset": {"url": "https://app.example.com"},
             "extra": {"auth_context": {"credentials": {
                 "username": "u", "password": "pw",
                 "login_url": "https://login.example.com/", "domain": "example.com"}}},
             "project_id": "p1", "run_id": "r", "phase": 4}
    graph.invoke(state)
    assert called["target"] == "https://app.example.com"
    assert called["credentials"]["username"] == "u"
