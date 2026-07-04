# tests/recon/test_job_agent.py
"""Per-job orchestrator agent: LLM-preprocess + Send fan-out to pods.

Fully mocked - no live pod graph, no live LLM. `pod_invoke` and
`preprocess_fn` are injected fakes; `build_job_agent` wires them into a
compiled StateGraph(JobState) exactly like production does with the real
Foundation `pod_graph` and `chat_model_for("job_orchestrator")`.
"""
import asyncio

from agent.recon import job_agent as ja
from agent.recon.jobs import JOBS
from agent.recon.types import PodExport


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


def test_fanout_is_capped_at_max_pods(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 2)
    pod_invoke = make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    job = JOBS["subfinder"]
    input_assets = [{"name": "a.com"}, {"name": "b.com"}, {"name": "c.com"}]
    result = agent.invoke(base_state(job, input_assets))

    assert len(result["pod_inputs"]) == 2
    assert len(result["pod_exports"]) == 2
    assert len(pod_invoke.calls) == 2


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


def test_non_auth_job_strips_auth_context_from_pod_inputs(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    pod_invoke = make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    job = JOBS["subfinder"]
    assert job.use_auth is False
    input_assets = [{"name": "a.com"}]
    extra = {"auth_context": "Bearer xyz"}

    agent.invoke(base_state(job, input_assets, extra=extra))

    assert len(pod_invoke.calls) == 1
    assert "auth_context" not in pod_invoke.calls[0]["extra"]


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


def test_default_pod_invoke_routes_agent_configurator_mode_jobs_to_crawl_pod(monkeypatch):
    from agent.recon.crawl import crawl_pod as crawl_pod_module
    from agent.recon.types import JobSpec, PodExport

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
    from agent.recon import pod as pod_module
    from agent.recon.types import PodExport

    class FakePodGraph:
        def invoke(self, state):
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
