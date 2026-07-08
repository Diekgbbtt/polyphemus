"""Authenticated agentic crawl: steel_await_auth precreate + viewer URL
surfacing.

Fully mocked - no live Steel/LLM. Covers three seams:

  * `crawl_agent.run_crawl_authenticated` threads a fake `precreate_fn`
    result (`crawl_id`, `awaiting_status`) into `run_crawl`'s
    `pre_created_crawl_id` and returns both the manifest and the
    awaiting_status dict (which carries the viewer URL).
  * `crawl_pod`'s `crawl` node only calls the authenticated path (and
    therefore precreate) for a `use_auth` job whose `extra` carries an
    `auth_context` signal; a non-auth crawl (or an auth job with no
    `auth_context`) calls the plain `run_crawl_fn` and never precreates.
    The viewer URL, when present, is recorded on the pod export's `stats`.
  * `pipeline.run_pipeline` aggregates a crawl job's `viewer_url` (read off
    its pod exports' `stats`) into the job status row it upserts, so
    `GET /recon/{run_id}` surfaces it via `per_job[...]stats.viewer_url`.
"""
import asyncio

from agent.recon import pipeline
from agent.recon.crawl import crawl_agent, crawl_pod
from agent.recon.types import JobSpec, PodExport

AUTH_JOB = JobSpec(
    tool="steel_crawl",
    skill="agentic_crawl",
    command_template="",
    produces=["BaseURL", "Endpoint", "Parameter"],
    consumes="BaseURL",
    use_auth=True,
    configurator_mode="agent",
)

NON_AUTH_JOB = JobSpec(
    tool="steel_crawl",
    skill="agentic_crawl",
    command_template="",
    produces=["BaseURL", "Endpoint", "Parameter"],
    consumes="BaseURL",
    use_auth=False,
    configurator_mode="agent",
)

CANNED_MANIFEST = {
    "endpoints": [
        {"method": "GET", "url": "https://app.example.com/", "query": [], "body": [], "status": 200},
    ],
    "js_urls": [],
}


# ---------------------------------------------------------------------------
# crawl_agent.run_crawl_authenticated
# ---------------------------------------------------------------------------


def test_run_crawl_authenticated_threads_precreated_crawl_id_and_returns_awaiting_status():
    captured_pre_created_id = {}

    async def fake_precreate_fn(mcp_manager, body):
        return "crawl-123", {"status": "awaiting_auth", "viewer_url": "https://steel.example/v/abc", "crawl_id": "crawl-123"}

    class FakeTool:
        def __init__(self, name):
            self.name = name

    async def run_crawl_capture(target, *, scope, model_role="crawler", tools=None, llm=None,
                                 max_pages=None, max_depth=None, max_iters=None,
                                 pre_created_crawl_id=None):
        captured_pre_created_id["value"] = pre_created_crawl_id
        return dict(CANNED_MANIFEST)

    manifest, awaiting_status = asyncio.run(
        crawl_agent.run_crawl_authenticated(
            "https://app.example.com",
            scope=["https://app.example.com"],
            tools=[FakeTool("steel_crawl_start")],
            precreate_fn=fake_precreate_fn,
            _run_crawl_fn=run_crawl_capture,
        )
    )

    assert captured_pre_created_id["value"] == "crawl-123"
    assert manifest == CANNED_MANIFEST
    assert awaiting_status == {
        "status": "awaiting_auth",
        "viewer_url": "https://steel.example/v/abc",
        "crawl_id": "crawl-123",
    }


def test_run_crawl_authenticated_emits_viewer_url_before_blocking_crawl():
    # EARLY SURFACING: on_awaiting_auth must fire the instant the session is
    # precreated - BEFORE the blocking crawl runs - so job status can carry the
    # viewer_url while the operator still has the session window to log in.
    events = []

    async def fake_precreate_fn(mcp_manager, body):
        events.append("precreate")
        return "crawl-123", {"status": "awaiting_auth", "viewer_url": "https://steel.example/v/abc", "crawl_id": "crawl-123"}

    async def run_crawl_capture(target, *, scope, model_role="crawler", tools=None, llm=None,
                                 max_pages=None, max_depth=None, max_iters=None,
                                 pre_created_crawl_id=None):
        events.append("crawl")
        return dict(CANNED_MANIFEST)

    def on_awaiting_auth(awaiting_status):
        events.append(("surfaced", awaiting_status.get("viewer_url")))

    manifest, awaiting_status = asyncio.run(
        crawl_agent.run_crawl_authenticated(
            "https://app.example.com",
            scope=["https://app.example.com"],
            tools=[],
            precreate_fn=fake_precreate_fn,
            _run_crawl_fn=run_crawl_capture,
            on_awaiting_auth=on_awaiting_auth,
        )
    )

    # surfaced BEFORE the crawl ran
    assert events == ["precreate", ("surfaced", "https://steel.example/v/abc"), "crawl"]
    assert manifest == CANNED_MANIFEST


def test_run_crawl_authenticated_best_effort_on_precreate_failure():
    async def failing_precreate_fn(mcp_manager, body):
        raise RuntimeError("steel unreachable")

    manifest, awaiting_status = asyncio.run(
        crawl_agent.run_crawl_authenticated(
            "https://app.example.com",
            scope=["https://app.example.com"],
            tools=[],
            precreate_fn=failing_precreate_fn,
        )
    )

    assert manifest == {"endpoints": [], "js_urls": []}
    assert awaiting_status is None


# ---------------------------------------------------------------------------
# crawl_pod: auth-signal detection + viewer_url -> PodExport.stats
# ---------------------------------------------------------------------------


def make_capturing_curate_fn():
    def curate_fn(assets, observations, project_id):
        return len(assets), len(observations)

    return curate_fn


def base_pod_state(job, extra=None):
    return {
        "job": job,
        "input_asset": {"url": "https://app.example.com"},
        "asset_context": "",
        "extra": extra or {},
        "session_id": "run1-4-steel_crawl-abcd1234",
        "project_id": "proj-1",
    }


def test_auth_job_with_auth_context_calls_precreate_and_records_viewer_url():
    precreate_calls = []

    def run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        precreate_calls.append((target, scope))
        return dict(CANNED_MANIFEST), {"status": "awaiting_auth", "viewer_url": "https://steel.example/v/abc", "crawl_id": "crawl-123"}

    def run_crawl_fn(target, *, scope):
        raise AssertionError("non-auth run_crawl_fn must not be called on the auth path")

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        run_crawl_authenticated_fn=run_crawl_authenticated_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    result = pod.invoke(base_pod_state(AUTH_JOB, extra={"auth_context": {"cookies": []}}))
    export = result["export"]

    assert len(precreate_calls) == 1
    assert precreate_calls[0] == ("https://app.example.com", ["https://app.example.com"])
    assert export.verdict == "success"
    assert export.stats == {"viewer_url": "https://steel.example/v/abc"}


def test_non_auth_crawl_skips_precreate():
    precreate_calls = []

    def run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        precreate_calls.append((target, scope))
        return dict(CANNED_MANIFEST), {"viewer_url": "should-not-be-called"}

    def run_crawl_fn(target, *, scope):
        return dict(CANNED_MANIFEST)

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        run_crawl_authenticated_fn=run_crawl_authenticated_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    result = pod.invoke(base_pod_state(NON_AUTH_JOB, extra={}))
    export = result["export"]

    assert precreate_calls == []
    assert export.verdict == "success"
    assert not (export.stats or {}).get("viewer_url")


def test_auth_job_without_auth_context_skips_precreate():
    precreate_calls = []

    def run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        precreate_calls.append((target, scope))
        return dict(CANNED_MANIFEST), {"viewer_url": "should-not-be-called"}

    def run_crawl_fn(target, *, scope):
        return dict(CANNED_MANIFEST)

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        run_crawl_authenticated_fn=run_crawl_authenticated_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    result = pod.invoke(base_pod_state(AUTH_JOB, extra={}))
    export = result["export"]

    assert precreate_calls == []
    assert export.verdict == "success"


def test_crawl_node_status_sink_writes_viewer_url_early_to_registry():
    # The crawl node, on the interactive-auth path, must call the injected
    # status_sink(run_id, phase, job, viewer_url) as soon as the session is
    # precreated - the mid-flight registry write that surfaces viewer_url to
    # GET /recon/{run_id} before the blocking crawl finishes.
    sink_calls = []

    def run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        # emulate the real fn: fire the early callback, THEN "block" and return
        if on_awaiting_auth is not None:
            on_awaiting_auth({"viewer_url": "https://steel.example/v/early", "crawl_id": "c1"})
        return dict(CANNED_MANIFEST), {"viewer_url": "https://steel.example/v/early", "crawl_id": "c1"}

    def status_sink(run_id, phase, job, viewer_url):
        sink_calls.append((run_id, phase, job, viewer_url))

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=lambda target, *, scope: (_ for _ in ()).throw(AssertionError("auth path expected")),
        run_crawl_authenticated_fn=run_crawl_authenticated_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
        status_sink=status_sink,
    )

    state = base_pod_state(AUTH_JOB, extra={"auth_context": {"cookies": []}})
    state["run_id"] = "run-9"
    state["phase"] = 4
    result = pod.invoke(state)

    assert sink_calls == [("run-9", 4, "steel_crawl", "https://steel.example/v/early")]
    assert result["export"].stats == {"viewer_url": "https://steel.example/v/early"}


# ---------------------------------------------------------------------------
# PodExport.stats
# ---------------------------------------------------------------------------


def test_pod_export_stats_defaults_to_none_and_accepts_dict():
    export = PodExport(input_asset={}, verdict="success")
    assert export.stats is None

    export_with_stats = PodExport(input_asset={}, verdict="success", stats={"viewer_url": "x"})
    assert export_with_stats.stats == {"viewer_url": "x"}


# ---------------------------------------------------------------------------
# pipeline: viewer_url pass-through into recon_jobs.stats
# ---------------------------------------------------------------------------


class FakeRegistry:
    def __init__(self):
        self.upsert_job_calls = []

    def create_run(self, run_id, project_id):
        pass

    def set_run_status(self, run_id, status, current_phase=None):
        pass

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        self.upsert_job_calls.append(
            {"run_id": run_id, "phase": phase, "job": job, "status": status, "stats": stats, "error": error}
        )


def test_pipeline_surfaces_crawl_job_viewer_url_in_job_stats():
    async def run_job(job, input_assets, *, run_id, phase, extra):
        if job.tool == "steel_crawl":
            return [
                PodExport(
                    input_asset={},
                    verdict="success",
                    stats={"viewer_url": "https://steel.example/v/abc"},
                )
            ]
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "httpx", "steel_crawl"],
            run_job=run_job,
            load_settings=lambda project_id: settings,
            registry=registry,
            read_assets=lambda node_type, project_id: [{"name": "seed"}],
        )
    )

    crawl_calls = [c for c in registry.upsert_job_calls if c["job"] == "steel_crawl" and c["status"] != "in_progress"]
    assert crawl_calls, "expected a terminal upsert_job call for steel_crawl"
    assert crawl_calls[-1]["stats"]["viewer_url"] == "https://steel.example/v/abc"


# ---------------------------------------------------------------------------
# crawl_pod: non-interactive cookie injection (cookies present -> skip viewer)
# ---------------------------------------------------------------------------


def test_auth_job_with_cookies_injects_and_skips_precreate():
    precreate_calls = []
    run_calls = []

    def run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        precreate_calls.append(target)
        return dict(CANNED_MANIFEST), {"viewer_url": "should-not-be-used"}

    def run_crawl_fn(target, *, scope, auth_cookies=None):
        run_calls.append((target, scope, auth_cookies))
        return dict(CANNED_MANIFEST)

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        run_crawl_authenticated_fn=run_crawl_authenticated_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    cookies = [{"name": ".AspNet.Cookies", "value": "TOK"}]
    result = pod.invoke(base_pod_state(AUTH_JOB, extra={"auth_context": {"cookies": cookies}}))

    assert precreate_calls == []  # non-interactive path, no human viewer
    assert run_calls == [("https://app.example.com", ["https://app.example.com"], cookies)]
    assert result["export"].verdict == "success"


def test_auth_job_empty_cookies_still_uses_interactive_path():
    precreate_calls = []

    def run_crawl_authenticated_fn(target, *, scope, on_awaiting_auth=None):
        precreate_calls.append(target)
        return dict(CANNED_MANIFEST), {"viewer_url": "https://steel.example/v/abc", "crawl_id": "c1"}

    def run_crawl_fn(target, *, scope, auth_cookies=None):
        raise AssertionError("empty cookies must fall to the interactive path")

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        run_crawl_authenticated_fn=run_crawl_authenticated_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    result = pod.invoke(base_pod_state(AUTH_JOB, extra={"auth_context": {"cookies": []}}))
    assert precreate_calls == ["https://app.example.com"]
    assert result["export"].stats == {"viewer_url": "https://steel.example/v/abc"}
