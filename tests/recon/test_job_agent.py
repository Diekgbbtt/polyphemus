# tests/recon/test_job_agent.py
"""Per-job orchestrator agent: LLM-preprocess + Send fan-out to pods.

Fully mocked - no live pod graph, no live LLM. `pod_invoke` and
`preprocess_fn` are injected fakes; `build_job_agent` wires them into a
compiled StateGraph(JobState) exactly like production does with the real
Foundation `pod_graph` and `chat_model_for("job_orchestrator")`.
"""
import asyncio

from polymerhus.recon.control import job_agent as ja
from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain.types import PodExport


def make_recording_pod_invoke(fail_on_index: int | None = None):
    """A fake pod_invoke that records every pod_input it was called with,
    and (optionally) raises for one specific call index so tests can assert
    error-isolation."""
    calls: list[dict] = []

    def pod_invoke(pod_input, job, run_id, phase):
        idx = len(calls)
        calls.append(pod_input)
        if fail_on_index is not None and idx == fail_on_index:
            raise RuntimeError("boom")
        return PodExport(input_asset=pod_input["input_asset"], verdict="success")

    pod_invoke.calls = calls
    return pod_invoke


def base_state(job, input_assets, *, extra=None, run_id="run-1", phase=0):
    return {
        "job": job,
        "input_assets": input_assets,
        "asset_context": "",
        "extra": extra or {},
        "run_id": run_id,
        "phase": phase,
    }


def test_fanout_is_not_capped_by_max_pods(monkeypatch):
    # MAX_PODS is now the CONCURRENCY ceiling, not an asset cap: a small MAX_PODS
    # must NOT drop assets. All 5 assets become pods.
    monkeypatch.setattr(ja, "MAX_PODS", 2)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 100)
    pod_invoke = make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    job = JOBS["subfinder"]
    input_assets = [{"name": f"{i}.com"} for i in range(5)]
    result = agent.invoke(base_state(job, input_assets))

    assert len(result["pod_inputs"]) == 5  # all covered, not capped at MAX_PODS=2
    assert len(pod_invoke.calls) == 5


def test_fanout_capped_only_by_job_asset_budget(monkeypatch):
    # The only cap on coverage is the deliberate MAX_JOB_ASSETS budget, and it is
    # independent of MAX_PODS (concurrency).
    monkeypatch.setattr(ja, "MAX_PODS", 1)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 2)
    pod_invoke = make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    job = JOBS["subfinder"]
    input_assets = [{"name": "a.com"}, {"name": "b.com"}, {"name": "c.com"}]
    result = agent.invoke(base_state(job, input_assets))

    assert len(result["pod_inputs"]) == 2  # budget=2, NOT MAX_PODS=1
    assert len(pod_invoke.calls) == 2


def test_run_job_bounds_concurrency_to_max_pods(monkeypatch):
    # run_job must pass max_concurrency=MAX_PODS so LangGraph runs at most
    # MAX_PODS pod_runner Sends at a time (verified honored, langgraph 1.2.7).
    monkeypatch.setattr(ja, "MAX_PODS", 7)
    captured = {}

    class FakeGraph:
        def invoke(self, initial, config=None):
            captured["config"] = config or {}
            return {"pod_exports": []}

    out = asyncio.run(
        ja.run_job(JOBS["subfinder"], [{"name": "a.com"}],
                   run_id="r", phase=0, extra={}, agent=FakeGraph())
    )
    assert captured["config"].get("max_concurrency") == 7
    assert out == []


def test_pod_failure_is_isolated_other_pods_still_succeed(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    pod_invoke = make_recording_pod_invoke(fail_on_index=1)
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    job = JOBS["subfinder"]
    input_assets = [{"name": "a.com"}, {"name": "b.com"}, {"name": "c.com"}]
    result = agent.invoke(base_state(job, input_assets))

    exports = result["pod_exports"]
    assert len(exports) == 3  # job not aborted by the one failure

    verdicts = [e.verdict for e in exports]
    assert verdicts.count("success") == 2
    assert verdicts.count("failed") == 1

    failed = [e for e in exports if e.verdict == "failed"][0]
    assert failed.error == "boom"


def test_use_auth_job_threads_auth_context_into_pod_inputs(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    pod_invoke = make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    job = JOBS["httpx"]
    assert job.use_auth is True
    input_assets = [{"name": "a.com"}]
    extra = {"auth_context": "Bearer xyz"}

    agent.invoke(base_state(job, input_assets, extra=extra, phase=3))

    assert len(pod_invoke.calls) == 1
    assert pod_invoke.calls[0]["extra"].get("auth_context") == "Bearer xyz"


def test_job_agent_passes_extra_through_without_restripping_auth(monkeypatch):
    # C1 single-owner: auth-eligibility is decided ONCE, in the pipeline, which
    # injects auth_context only for use_auth jobs. The job agent no longer
    # re-decides it - it threads `extra` through as the pipeline built it. The
    # pipeline-level guarantee is covered by test_pipeline.py::
    # test_auth_context_only_passed_to_use_auth_jobs.
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    pod_invoke = make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    job = JOBS["subfinder"]
    extra = {"auth_context": "Bearer xyz"}
    agent.invoke(base_state(job, [{"name": "a.com"}], extra=extra))

    assert len(pod_invoke.calls) == 1
    assert pod_invoke.calls[0]["extra"].get("auth_context") == "Bearer xyz"


def test_run_job_convenience_wrapper_returns_pod_exports(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    pod_invoke = make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    job = JOBS["subfinder"]
    input_assets = [{"name": "a.com"}, {"name": "b.com"}]

    exports = asyncio.run(
        ja.run_job(job, input_assets, run_id="run-2", phase=0, extra={}, agent=agent)
    )

    assert len(exports) == 2
    assert all(isinstance(e, PodExport) for e in exports)


def test_run_job_offloads_blocking_invoke_so_gather_is_concurrent():
    """Regression: the pod graph's `.invoke` is blocking (LLM triage, sync
    Neo4j curate, exec bridge). `run_job` must offload it via
    `asyncio.to_thread` so the pipeline's per-job `asyncio.gather` truly runs
    concurrently AND the API event loop stays responsive during a run.

    Before the fix, `.invoke` ran directly on the loop: two gathered jobs
    serialized (~2x one job's time) and a concurrent coroutine could not tick.
    """
    import time

    SLEEP = 0.3

    class BlockingAgent:
        def invoke(self, state, config=None):
            time.sleep(SLEEP)  # simulate blocking pod work
            return {"pod_exports": []}

    agent = BlockingAgent()

    async def scenario():
        # 1) two concurrent run_jobs overlap (concurrent, not serialized)
        t0 = time.perf_counter()
        await asyncio.gather(
            ja.run_job(None, [], run_id="c1", phase=0, extra={}, agent=agent),
            ja.run_job(None, [], run_id="c2", phase=0, extra={}, agent=agent),
        )
        elapsed = time.perf_counter() - t0

        # 2) the loop stays responsive while a job runs (ticker keeps advancing)
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(SLEEP / 10)
                ticks += 1

        tk = asyncio.create_task(ticker())
        await ja.run_job(None, [], run_id="c3", phase=0, extra={}, agent=agent)
        tk.cancel()
        return elapsed, ticks

    elapsed, ticks = asyncio.run(scenario())

    # Concurrent: ~1x SLEEP (+thread overhead), comfortably below the 2x that
    # serialized execution would take.
    assert elapsed < SLEEP * 1.6, f"run_jobs serialized (elapsed={elapsed:.3f}s)"
    # Loop not blocked during a job: the ticker advanced several times.
    assert ticks >= 3, f"event loop was blocked during run_job (ticks={ticks})"


def test_default_pod_invoke_routes_agent_configurator_mode_jobs_to_crawl_pod(monkeypatch):
    from polymerhus.recon.crawl import crawl_pod as crawl_pod_module
    from polymerhus.recon.domain.types import JobSpec, PodExport

    calls = []

    def fake_crawl_pod_invoke(pod_input, job, run_id, phase):
        calls.append((pod_input, job, run_id, phase))
        return PodExport(input_asset=pod_input["input_asset"], verdict="success")

    monkeypatch.setattr(crawl_pod_module, "crawl_pod_invoke", fake_crawl_pod_invoke)

    agent_job = JobSpec(
        tool="steel_crawl", skill="agentic_crawl", command_template="",
        produces=["BaseURL"], consumes="BaseURL", configurator_mode="agent",
    )
    pod_input = {"input_asset": {"url": "https://app.example.com"}, "extra": {}}
    export = ja.default_pod_invoke(pod_input, agent_job, "run-1", 4)

    assert export.verdict == "success"
    assert len(calls) == 1


def test_default_pod_invoke_uses_template_pod_for_deterministic_jobs(monkeypatch):
    from polymerhus.recon.domain import pod as pod_module
    from polymerhus.recon.domain.types import PodExport

    class FakePodGraph:
        def invoke(self, state, config=None):
            return {"export": PodExport(input_asset=state["input_asset"], verdict="success")}

    monkeypatch.setattr(pod_module, "pod_graph", FakePodGraph())

    job = JOBS["subfinder"]
    assert job.configurator_mode == "deterministic"
    pod_input = {"input_asset": {"name": "a.com"}, "extra": {}}
    export = ja.default_pod_invoke(pod_input, job, "run-1", 0)

    assert export.verdict == "success"


def test_default_job_agent_is_import_safe_module_level_instance():
    # Importing job_agent must not perform any LLM/network I/O; the module-
    # level `job_agent` compiled graph should simply exist and be usable
    # with the deterministic default_preprocess_fn (no I/O needed since
    # inputs never exceed MAX_PODS in this fake scenario, and pod_invoke is
    # never exercised here beyond existing as an attribute).
    assert ja.job_agent is not None
    assert callable(ja.default_pod_invoke)
    assert callable(ja.default_preprocess_fn)


def test_steering_preprocess_applies_throttle(monkeypatch):
    from polymerhus.recon.control import job_agent
    from polymerhus.recon.domain.types import JobSpec

    # The job agent decides ONLY throttling now; it returns a set of throttle urls
    # and NEVER drops an asset.
    monkeypatch.setattr(
        "polymerhus.recon.control.job_agent.decide_pod_selection",
        lambda signals, job_name, assets, llm=None: {"https://a"},
    )
    job = JobSpec(tool="katana", skill="crawl", command_template="katana -u {target}",
                  produces=["Endpoint"], consumes="BaseURL")
    pod_inputs = job_agent.steering_preprocess_fn(
        [{"url": "https://a"}, {"url": "https://b"}], job,
        {"project_id": "p1", "steering": [{"url": "https://a", "macro_kind": "waf_protected", "evidence": "e"}]},
        "",
    )
    # ALL assets become pods (none dropped); only the throttled one carries rate_profile.
    assert [pi["input_asset"]["url"] for pi in pod_inputs] == ["https://a", "https://b"]
    assert pod_inputs[0]["extra"]["rate_profile"] == "throttle"
    assert "rate_profile" not in pod_inputs[1]["extra"]
    assert "steering" not in pod_inputs[0]["extra"]  # steering is orchestration-only
    assert "steering" not in pod_inputs[1]["extra"]


def test_steering_preprocess_never_drops_assets(monkeypatch):
    # Responsibility-model regression (the katana-zeroing bug): with signals
    # present, the recon-job agent must build a pod for EVERY budget-capped asset
    # - asset selection belongs to the orchestrator (decide_routing), not here.
    # Even a flagged host still runs; only its rate_profile differs.
    from polymerhus.recon.control import job_agent
    from polymerhus.recon.domain.types import JobSpec

    monkeypatch.setattr(
        "polymerhus.recon.control.job_agent.decide_pod_selection",
        lambda signals, job_name, assets, llm=None: {"https://a"},
    )
    job = JobSpec(tool="katana", skill="crawl", command_template="katana -u {target}",
                  produces=["Endpoint"], consumes="BaseURL")
    assets = [{"url": f"https://h{i}"} for i in range(7)] + [{"url": "https://a"}]
    signals = [{"url": "https://a", "macro_kind": "waf_protected", "evidence": "e"}]
    pod_inputs = job_agent.steering_preprocess_fn(
        assets, job, {"project_id": "p1", "steering": signals}, "")
    # All 8 covered (the bug zeroed this to 0 pods).
    assert len(pod_inputs) == len(assets)
    assert [pi["input_asset"]["url"] for pi in pod_inputs] == [a["url"] for a in assets]
    throttled = [pi["input_asset"]["url"] for pi in pod_inputs
                 if pi["extra"].get("rate_profile") == "throttle"]
    assert throttled == ["https://a"]


def test_steering_preprocess_no_signal_falls_back_to_default():
    from polymerhus.recon.control import job_agent
    from polymerhus.recon.domain.types import JobSpec
    job = JobSpec(tool="katana", skill="crawl", command_template="katana -u {target}",
                  produces=["Endpoint"], consumes="BaseURL")
    pod_inputs = job_agent.steering_preprocess_fn(
        [{"url": "https://a"}], job, {"project_id": "p1"}, "")
    assert [pi["input_asset"]["url"] for pi in pod_inputs] == ["https://a"]
    assert "rate_profile" not in pod_inputs[0]["extra"]


# --- recon-job agent per-asset throttle decision (decide_pod_selection) ---
# A fake LLM is injected so no provider/network is touched. The job agent decides
# ONLY throttling now - it returns a set of throttle urls and never drops an asset.


class _FakeStructured:
    def __init__(self, result): self._result = result
    def invoke(self, messages): return self._result


class _FakeLLM:
    def __init__(self, result): self._result = result
    def with_structured_output(self, schema, **kw): return _FakeStructured(self._result)


def test_decide_pod_selection_returns_throttle_set():
    from polymerhus.recon.control.job_agent import decide_pod_selection, PodThrottlePlan, _AssetPlan
    result = PodThrottlePlan(plan=[
        _AssetPlan(url="https://a", throttle=True),
        _AssetPlan(url="https://b", throttle=False),
    ])
    throttle = decide_pod_selection(
        [{"url": "https://a", "macro_kind": "waf_protected", "evidence": "e"}],
        "katana", [{"url": "https://a"}, {"url": "https://b"}], llm=_FakeLLM(result),
    )
    assert throttle == {"https://a"}


def test_decide_pod_selection_never_drops_asset_omitted_from_plan():
    # Contract regression: the job agent decides ONLY throttling. An asset the LLM
    # does not mention is simply not throttled; it is NEVER dropped (selection is
    # the orchestrator's decide_routing concern). Only 'a' is in the plan.
    from polymerhus.recon.control.job_agent import decide_pod_selection, PodThrottlePlan, _AssetPlan
    result = PodThrottlePlan(plan=[_AssetPlan(url="https://a", throttle=True)])
    throttle = decide_pod_selection(
        [{"url": "https://a", "macro_kind": "waf_protected", "evidence": "e"}],
        "katana", [{"url": "https://a"}, {"url": "https://b"}], llm=_FakeLLM(result),
    )
    assert throttle == {"https://a"}  # b omitted -> just not throttled, still a candidate


def test_decide_pod_selection_fail_open_throttles_nothing():
    from polymerhus.recon.control.job_agent import decide_pod_selection

    class Boom:
        def with_structured_output(self, *a, **k): raise RuntimeError("llm down")

    throttle = decide_pod_selection(
        [{"url": "https://a", "macro_kind": "waf_protected", "evidence": "e"}],
        "katana", [{"url": "https://a"}], llm=Boom())
    assert throttle == set()


def test_batched_job_preprocess_reduces_and_packs_into_max_pods(monkeypatch):
    # C3: batching (reduce first-party + dedup, then pack into <= MAX_PODS batch
    # pods) is the job agent's concern, done in default_preprocess_fn. It reads
    # apex_registrable from extra and never leaks it to the pod.
    monkeypatch.setattr(ja, "MAX_PODS", 8)
    job = JOBS["jsluice"]
    assert job.batch is True
    assets = [{"path": f"/b{i}.js", "url": f"https://a.houseofhr.com/b{i}.js"} for i in range(60)]
    pod_inputs = ja.default_preprocess_fn(assets, job, {"apex_registrable": "houseofhr.com"}, "")

    assert 0 < len(pod_inputs) <= 8
    assert all("batch" in pi["input_asset"] for pi in pod_inputs)
    all_urls = [u for pi in pod_inputs for u in pi["input_asset"]["batch"]]
    assert len(all_urls) == 60  # all bundles covered, none dropped
    assert "apex_registrable" not in pod_inputs[0]["extra"]  # orchestration-only, not leaked
