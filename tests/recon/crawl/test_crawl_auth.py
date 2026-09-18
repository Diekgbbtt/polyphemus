"""Profile-mount-only agentic crawl (#243, D223-19): the crawl runs under the
gateway-established auth state and carries no interactive auth path.

Fully mocked - no live Steel/LLM. Covers three seams:

* `crawl_pod`'s `crawl` node runs the plain `run_crawl_fn` for every crawl,
  forwarding the feed-projected `auth_context` cookies (resolved from the
  store through the bound account identifier) so the provider seeds the
  browser context - and nothing else. There is no precreate, no viewer URL,
  no operator prompt: a `use_auth` job with feed material crawls
  authenticated, a non-auth crawl (or an auth job with no material) crawls
  anonymously.
* `crawl_agent.run_crawl` forwards `auth_cookies` to `get_crawl_tools`
  (the provider seam), unchanged.
* `pipeline.run_pipeline` binds the persisted Steel profile key plus the
  cookie subset onto the crawl job's extra, and carries no `viewer_url`
  into the job status row.
"""
import asyncio

from polymerhus.recon.control import pipeline
from polymerhus.recon.crawl import crawl_agent, crawl_pod
from polymerhus.recon.domain.types import JobSpec, PodExport

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

COOKIES = [{"name": "sid", "value": "S"}]


def make_capturing_curate_fn():
    def curate_fn(assets, observations, project_id, scope_domain=None):
        return len(assets), len(observations), assets, observations

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


# ---------------------------------------------------------------------------
# crawl_pod: profile-mount only - feed cookies in, plain crawl out
# ---------------------------------------------------------------------------


def test_auth_job_with_feed_cookies_forwards_them_and_crawls_plain():
    run_calls = []

    def run_crawl_fn(target, *, scope, auth_cookies=None):
        run_calls.append((target, scope, auth_cookies))
        return dict(CANNED_MANIFEST)

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    result = pod.invoke(base_pod_state(AUTH_JOB, extra={"auth_context": {"cookies": COOKIES}}))
    export = result["export"]

    # scope folds to the registrable domain at the crawl-node resolution point
    assert run_calls == [("https://app.example.com", ["example.com"], COOKIES)]
    assert export.verdict == "success"
    assert not (export.stats or {}).get("viewer_url")  # no operator prompt, ever


def test_non_auth_crawl_runs_anonymous():
    run_calls = []

    def run_crawl_fn(target, *, scope, auth_cookies=None):
        run_calls.append(auth_cookies)
        return dict(CANNED_MANIFEST)

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    result = pod.invoke(base_pod_state(NON_AUTH_JOB, extra={}))
    assert result["export"].verdict == "success"
    assert run_calls == [[]]


def test_auth_job_without_material_runs_anonymous():
    # A use_auth job whose account resolved to nothing: no cookies present,
    # so the crawl runs anonymous (fail-open) rather than prompting.
    run_calls = []

    def run_crawl_fn(target, *, scope, auth_cookies=None):
        run_calls.append(auth_cookies)
        return dict(CANNED_MANIFEST)

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    result = pod.invoke(base_pod_state(AUTH_JOB, extra={}))
    assert result["export"].verdict == "success"
    assert run_calls == [[]]


def test_crawl_node_best_effort_on_run_failure():
    def run_crawl_fn(target, *, scope, auth_cookies=None):
        raise RuntimeError("steel down")

    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=make_capturing_curate_fn(),
    )

    result = pod.invoke(base_pod_state(AUTH_JOB, extra={"auth_context": {"cookies": COOKIES}}))
    assert result["export"].verdict == "failed"


# ---------------------------------------------------------------------------
# PodExport.stats
# ---------------------------------------------------------------------------


def test_pod_export_stats_defaults_to_none_and_accepts_dict():
    export = PodExport(input_asset={}, verdict="success")
    assert export.stats is None

    export_with_stats = PodExport(input_asset={}, verdict="success", stats={"commands": ["x"]})
    assert export_with_stats.stats == {"commands": ["x"]}


# ---------------------------------------------------------------------------
# pipeline: steel profile binding, and no viewer_url in job stats
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


def test_pipeline_binds_steel_profile_and_cookies_to_crawl(tmp_path):
    from polymerhus.app.auth.store import AuthStore
    from polymerhus.recon.control.authn_loop import GatewayVerdict

    store = AuthStore(tmp_path)
    store.replace_operator_state(
        "proj1", overview={"login_endpoint": "https://x/login"},
        accounts={"alice": {
            "credentials": {"username": "u", "password": "p",
                            "login_url": "https://x/login"},
            "steel": {"profile": "proj1-alice"},
            "snapshot": {"cookies": COOKIES},
        }})

    class _Gateway:
        async def run_gateway(self, **kw):
            return GatewayVerdict(outcome="authenticated", account="alice",
                                  branch="request", rationale="t")

        async def stop(self): pass

    seen = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        seen[job.tool] = extra
        return [PodExport(input_asset={}, verdict="success")]

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "httpx", "steel_crawl"],
            run_job=run_job,
            load_settings=lambda project_id: {"target_domain": "t.com"},
            registry=FakeRegistry(),
            read_assets=lambda node_type, project_id: [{"name": "seed"}],
            orchestrator_factory=lambda run_id: _Gateway(),
            auth_store=store,
        )
    )

    assert seen["steel_crawl"]["steel_profile"] == "proj1-alice"
    assert seen["steel_crawl"]["auth_context"] == {"cookies": COOKIES}
    assert seen["steel_crawl"]["auth_account"] == "alice"


def test_pipeline_carries_no_viewer_url_into_crawl_job_stats():
    async def run_job(job, input_assets, *, run_id, phase, extra):
        if job.tool == "steel_crawl":
            return [PodExport(input_asset={}, verdict="success")]
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
    assert not ((crawl_calls[-1]["stats"] or {}).get("viewer_url"))
