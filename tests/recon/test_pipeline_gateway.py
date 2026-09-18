"""Pipeline tier: the auth gateway treatment in `run_pipeline` (#223, T3 #242).

Exercises the real pipeline/gateway boundary (no gateway injection seam):
the gateway runs deterministically before phase 0 under heartbeat, its typed
verdict prunes the plan and binds the account identifier, missing
credentials stop the run loudly, and every degradation fails open loudly.
The gateway actor is the production `ReconOrchestratorActor` (built through
the existing `orchestrator_factory` seam) with a scripted model and temp
stores underneath - the tier touches no live model and no live database.
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.auth.store import AuthStore
from polymerhus.app.llm.skills import SkillStore
from polymerhus.recon.control import pipeline
from polymerhus.recon.control.authn_loop import GatewayVerdict
from polymerhus.recon.control.orchestrator_agent import (
    GatewayStop,
    ReconOrchestratorActor,
)


class _FakeRegistry:
    def __init__(self):
        self.statuses = []

    def create_run(self, *a, **k): pass
    def set_run_status(self, *a, **k):
        self.statuses.append((a + tuple(k.values())) if k else a)
    def upsert_job(self, *a, **k): pass


def _script_model(*steps):
    cursor = {"i": 0}

    class _Step(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            step = steps[min(cursor["i"], len(steps) - 1)]
            cursor["i"] += 1
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{**c, "id": f"c{c['id']}", "type": "tool_call"}
                            for c in step],
            ))])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    return lambda role_id: _Step()


def _harness(tmp_path, *, model_steps, overview=None, accounts=None,
             gateway_cls=None):
    """The real boundary: a production `ReconOrchestratorActor` over temp
    stores with a scripted model, driven by the real `run_pipeline`."""
    store = AuthStore(tmp_path / "auth")
    store.replace_operator_state("p1", overview=overview or {},
                                 accounts=accounts or {})
    calls = {"order": [], "constructed": [], "stopped": []}

    def _factory(run_id):
        calls["constructed"].append(run_id)
        actor = ReconOrchestratorActor(
            run_id, project_id="p1", checkpointer=InMemorySaver(),
            model_factory=_script_model(*model_steps), observe=False,
            compaction=False, auth_store=store,
            skill_store=SkillStore(tmp_path / "skills"), kali_tools=[])
        return actor

    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        calls["order"].append(("job", job.tool))
        calls[job.tool] = {"assets": list(input_assets), "extra": dict(extra)}
        return []

    def fake_read_assets(node_type, project_id, where=None, *, driver=None):
        if node_type == "Subdomain":
            return [{"name": "app.example.com"}]
        if node_type == "BaseURL":
            return [{"url": "https://app.example.com"}]
        return []

    return store, calls, _factory, fake_run_job, fake_read_assets


def _verdict_call(**fields):
    base = {"outcome": "authenticated", "account": "alice", "branch": "request",
            "rationale": "proven live"}
    return {"name": "GatewayVerdict", "args": {**base, **fields}, "id": "v"}


def _account(name="alice"):
    return {name: {"credentials": {"username": "u", "password": "p",
                                   "login_url": "https://x/login"}}}


def _run(calls, factory, fake_run_job, fake_read_assets, *, registry=None,
         settings=None, subset=None, **kw):
    registry = registry or _FakeRegistry()
    asyncio.run(pipeline.run_pipeline(
        "p1", run_id="r1", job_subset=subset or ["subfinder", "httpx"],
        run_job=fake_run_job,
        load_settings=lambda pid: settings or {"target_domain": "*.example.com"},
        registry=registry, read_assets=fake_read_assets,
        read_steering_signals=lambda project_id, driver=None: [],
        orchestrator_factory=factory, **kw,
    ))
    return registry


# --- deterministic start --------------------------------------------------------


def test_gateway_runs_before_phase_zero_with_empty_signals(tmp_path):
    """The gateway is the deterministic first step: the actor is constructed
    on run start and its turn resolves before any job runs - and the retired
    empty-signal short-circuit cannot skip it (signals are empty here)."""
    store, calls, factory, fake_run_job, fake_read_assets = _harness(
        tmp_path, model_steps=[[_verdict_call()]],
        overview={"login_endpoint": "https://x/login"}, accounts=_account())

    order = []
    orig = ReconOrchestratorActor.run_gateway

    async def _spy(self, **kw):
        order.append("gateway")
        return await orig(self, **kw)

    ReconOrchestratorActor.run_gateway = _spy
    try:
        _run(calls, factory, fake_run_job, fake_read_assets)
    finally:
        ReconOrchestratorActor.run_gateway = orig

    assert calls["constructed"] == ["r1"]  # one actor per run, at start
    assert order == ["gateway"]
    assert calls["order"][0] == ("job", "subfinder")  # phases run after


def test_heartbeat_ticks_during_a_slow_gateway(tmp_path, monkeypatch):
    """D223-10: the run heartbeat starts BEFORE the gateway turn, so a long
    sign-in span never trips the stale-run reaper."""
    ticks = []
    monkeypatch.setattr(pipeline.config, "HEARTBEAT_TICK_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda rid: ticks.append(rid))

    async def _slow_gateway(*a, **k):
        await asyncio.sleep(0.06)
        return GatewayVerdict(outcome="anonymous", rationale="no surface")

    class _SlowFactory:
        def __init__(self, run_id):
            self._run_id = run_id

        async def run_gateway(self, **kw):
            return await _slow_gateway()

        async def stop(self): pass

    _, calls, _, fake_run_job, fake_read_assets = _harness(tmp_path, model_steps=[[]])
    registry = _run(calls, _SlowFactory, fake_run_job, fake_read_assets,
                    subset=["subfinder"])

    assert len(ticks) >= 2, "heartbeat never ticked during the slow gateway"


# --- verdict consumption ----------------------------------------------------------


def test_browser_only_verdict_prunes_to_the_steel_crawl(tmp_path):
    """The verdict releases or prunes: browser-only keeps the Steel crawl
    alone (D223-11, implemented literally - every request job pruned)."""
    store, calls, factory, fake_run_job, fake_read_assets = _harness(
        tmp_path, model_steps=[[_verdict_call(branch="browser_only")]],
        overview={"anti-bot": "waf:x", "http-client-replayability": False},
        accounts=_account())

    _run(calls, factory, fake_run_job, fake_read_assets,
         subset=["subfinder", "httpx", "katana", "steel_crawl"])

    ran = {tool for _, tool in calls["order"]}
    assert ran == {"steel_crawl"}


def test_browser_only_without_a_browser_path_fails_honestly(tmp_path, caplog):
    """A browser-only release over a plan with no Steel crawl prunes to
    nothing: zero phases running to a silent "complete" would be a lie, so
    the run is marked failed loudly - and request phases are NOT kept (the
    verdict said browser-only)."""
    import logging
    store, calls, factory, fake_run_job, fake_read_assets = _harness(
        tmp_path, model_steps=[[_verdict_call(branch="browser_only")]],
        overview={"anti-bot": "waf:x", "http-client-replayability": False},
        accounts=_account())

    registry = _FakeRegistry()
    with caplog.at_level(logging.ERROR):
        _run(calls, factory, fake_run_job, fake_read_assets,
             subset=["subfinder", "httpx"], registry=registry)

    assert calls["order"] == []  # nothing ran, and nothing was kept
    flat = [str(s) for s in registry.statuses]
    assert any("failed" in s for s in flat)
    assert not any(s[:2] == ("r1", "complete") for s in registry.statuses)
    assert "pruned every phase" in caplog.text.lower()


def test_account_identifier_bound_for_use_auth_jobs_only(tmp_path):
    """D223-19: the selected account's IDENTIFIER - never its material - is
    bound into the pipeline state for `use_auth` jobs; other jobs get
    nothing."""
    store, calls, factory, fake_run_job, fake_read_assets = _harness(
        tmp_path, model_steps=[[_verdict_call()]],
        overview={"login_endpoint": "https://x/login"}, accounts=_account())

    _run(calls, factory, fake_run_job, fake_read_assets)

    httpx_extra = calls["httpx"]["extra"]
    assert httpx_extra.get("auth_account") == "alice"
    subfinder_extra = calls["subfinder"]["extra"]
    assert "auth_account" not in subfinder_extra
    blob = repr(calls)
    assert "password" not in blob and "tokens" not in blob  # identifier only


def test_anonymous_verdict_runs_all_phases_without_account(tmp_path):
    """The no-surface finding runs the full plan anonymously: every job runs,
    no account rides the state."""
    store, calls, factory, fake_run_job, fake_read_assets = _harness(
        tmp_path, model_steps=[])

    _run(calls, factory, fake_run_job, fake_read_assets)

    assert {tool for _, tool in calls["order"]} == {"subfinder", "httpx"}
    assert all("auth_account" not in calls[job]["extra"]
               for job in ("subfinder", "httpx"))


def test_failed_verdict_runs_collection_loudly_without_account(tmp_path, caplog):
    """D223-2: a failed authentication is explicit and loud, never
    silent-anonymous - collection still runs, unauthenticated."""
    import logging
    store, calls, factory, fake_run_job, fake_read_assets = _harness(
        tmp_path, model_steps=[[_verdict_call(outcome="failed", account=None,
                                              rationale="space exhausted")]],
        overview={"login_endpoint": "https://x/login"}, accounts=_account())

    with caplog.at_level(logging.WARNING):
        _run(calls, factory, fake_run_job, fake_read_assets)

    assert {tool for _, tool in calls["order"]} == {"subfinder", "httpx"}
    assert all("auth_account" not in calls[job]["extra"]
               for job in ("subfinder", "httpx"))
    assert "unauthenticated" in caplog.text.lower()


# --- failure posture ------------------------------------------------------------------


def test_missing_credentials_stops_the_run_loudly(tmp_path, caplog):
    """D223-17 fail-close: a declared surface with no credentials stops the
    run - no job runs, the run is marked failed, never complete."""
    import logging

    class _Stopper:
        def __init__(self, run_id):
            self._run_id = run_id

        async def run_gateway(self, **kw):
            raise GatewayStop("no credentials")

        async def stop(self): pass

    _, calls, _, fake_run_job, fake_read_assets = _harness(tmp_path, model_steps=[[]])
    registry = _FakeRegistry()
    with caplog.at_level(logging.ERROR):
        _run(calls, _Stopper, fake_run_job, fake_read_assets, registry=registry)

    assert calls["order"] == []  # nothing ran
    flat = [str(s) for s in registry.statuses]
    assert any("failed" in s for s in flat)
    assert not any(s == ("r1", "complete") or s[:2] == ("r1", "complete") for s in registry.statuses)
    assert "fail-close" in caplog.text.lower() or "stopping the run" in caplog.text.lower()


def test_degraded_gateway_fails_open_with_all_phases(tmp_path, caplog):
    """D223-10 residual: a degraded gateway (no verdict) runs every phase
    unauthenticated, loudly."""
    import logging

    class _Degraded:
        def __init__(self, run_id):
            self._run_id = run_id

        async def run_gateway(self, **kw):
            return None

        async def stop(self): pass

    _, calls, _, fake_run_job, fake_read_assets = _harness(tmp_path, model_steps=[[]])
    with caplog.at_level(logging.WARNING):
        _run(calls, _Degraded, fake_run_job, fake_read_assets)

    assert {tool for _, tool in calls["order"]} == {"subfinder", "httpx"}
    assert "fail-open" in caplog.text.lower()


def test_legacy_routing_seam_is_not_consulted(tmp_path):
    """The per-phase routing turns are retired: an injected legacy
    `decide_routing` is never called and inputs pass unfiltered."""
    seen = []
    store, calls, factory, fake_run_job, fake_read_assets = _harness(
        tmp_path, model_steps=[[_verdict_call()]],
        overview={"login_endpoint": "https://x/login"}, accounts=_account())

    _run(calls, factory, fake_run_job, fake_read_assets,
         decide_routing=lambda sigs, jobs: seen.append((sigs, jobs)) or {"httpx": ["https://app.example.com"]})

    assert seen == []
