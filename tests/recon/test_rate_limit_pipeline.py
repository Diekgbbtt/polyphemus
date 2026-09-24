"""Pipeline tier: the #238 rate-limit turn, its persistence, and the Steel fallback.

Exercises the REAL `run_pipeline` boundary: after the auth gateway resolves and
BEFORE phase 0, the same orchestrator actor takes the rate-limit turn, the
public `RateProfile` lands in `recon_runs.stats["rate_limit"]`, and every HTTP
job - plus the agent-driven Steel crawl - carries the serialized
`TrafficPolicy` through `extra["traffic_policy"]`. No live model, no live
database, no live Kali.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from polymerhus.recon.control import pipeline
from polymerhus.recon.control.authn_loop import GatewayVerdict
from polymerhus.recon.control.orchestrator_agent import GatewayStop
from polymerhus.recon.domain.rate_limit import (
    RateLimitSafetyBudget,
    RateProfile,
    TrafficPolicy,
)

SEED = "*.t.com"
TARGET_KEY = "t.com"
TARGET_URL = "https://t.com/"
ARTIFACT_REF = "rate-artifact/v1:proj1/run1/steady-0"


class _RecordingRegistry:
    """The `pg` registry seam: records the call ORDER and merges `set_run_stats`
    ADDITIVELY (the real `recon_runs.stats` JSONB behaves the same way)."""

    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.run_stats: dict = {}
        self.statuses: list = []

    def create_run(self, *a, **k):
        self.events.append("create_run")

    def set_run_status(self, *a, **k):
        self.statuses.append(a)
        self.events.append("set_run_status")

    def upsert_job(self, *a, **k):
        pass

    def set_run_stats(self, run_id, stats):
        self.events.append("set_run_stats")
        self.run_stats.update(stats)


def _profile(*, rate=4.0, refs=(ARTIFACT_REF,), outcome="mapped"):
    now = datetime.now(timezone.utc)
    return RateProfile(
        target_key=TARGET_KEY, host_patterns=[TARGET_KEY], outcome=outcome,
        artifact_refs=list(refs), bypass_outcome="no_bypass",
        safe_rate_per_s=rate,
        measured_at=now,
        expires_at=now + timedelta(seconds=3600),
        traffic_policy=TrafficPolicy(
            target_key=TARGET_KEY, host_patterns=[TARGET_KEY], rate_per_s=rate,
            burst=2, max_concurrency=1, min_delay_ms=1000.0 / rate,
            source="measured"),
    )


def _conservative_profile():
    return RateProfile.conservative(
        TARGET_KEY, [TARGET_KEY], RateLimitSafetyBudget(),
        "rate-limit turn failed: conservative fallback", outcome="failed")


class _FakeOrchestrator:
    """The two-turn actor seam: records each turn in the shared event log."""

    def __init__(self, *, events, verdict=None, profile=None, rate_error=None):
        self._events = events
        self._verdict = verdict if verdict is not None else GatewayVerdict(
            outcome="authenticated", account="alice", branch="request", rationale="t")
        self._profile = profile if profile is not None else _profile()
        self._rate_error = rate_error
        self.rate_kwargs: dict | None = None

    async def run_gateway(self, **kw):
        self._events.append("gateway")
        return self._verdict

    async def run_rate_limit(self, **kw):
        self._events.append("rate")
        self.rate_kwargs = dict(kw)
        if self._rate_error is not None:
            raise self._rate_error
        return self._profile

    async def stop(self):
        self._events.append("stop")


def _run(events, orchestrator, *, registry=None, store=None, job_subset=None,
         settings=None):
    """Wire the real `run_pipeline` over a recording orchestrator + registry."""
    registry = registry or _RecordingRegistry(events)
    seen: dict = {}

    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        events.append(f"job:{job.tool}")
        seen[job.tool] = {"assets": list(input_assets), "extra": dict(extra)}
        return []

    def fake_read_assets(node_type, project_id, where=None, *, driver=None):
        if node_type == "Subdomain":
            return [{"name": "app.t.com"}]
        if node_type == "BaseURL":
            return [{"url": "https://app.t.com"}]
        return []

    async def _drive():
        await pipeline.run_pipeline(
            "proj1", run_id="run1",
            job_subset=job_subset if job_subset is not None
            else ["subfinder", "httpx", "katana"],
            run_job=fake_run_job,
            load_settings=lambda pid: settings or {"target_domain": SEED},
            registry=registry, read_assets=fake_read_assets,
            orchestrator_factory=lambda run_id: orchestrator,
            auth_store=store, feed_mode="queued", with_analysis=False,
        )

    asyncio.run(_drive())
    return registry, seen


def _orchestrator(events, **kw):
    return _FakeOrchestrator(events=events, **kw)


def _auth_store(tmp_path, **overrides):
    from polymerhus.app.auth.store import AuthStore

    store = AuthStore(tmp_path)
    account = {
        "credentials": {"username": "u", "password": "PASSWORD",
                        "login_url": "https://x/login"},
        "tokens": {"Authorization": {"value": "Bearer T", "location": "header"}},
        "snapshot": {"cookies": [{"name": "sid", "value": "S"}]},
    }
    account.update(overrides)
    store.replace_operator_state("proj1", overview={"login_endpoint": "https://x/login"},
                                 accounts={"alice": account})
    return store


# --- Step 1: ordering and persistence -----------------------------------------


def test_rate_turn_runs_after_auth_and_persists_before_phase_zero():
    """`create_run -> auth -> rate -> set_run_stats(rate_limit) -> phase 0`."""
    events: list = []
    registry, _ = _run(events, _orchestrator(events))

    assert registry.run_stats["rate_limit"]["outcome"] == "mapped"
    index = {name: events.index(name) for name in (
        "create_run", "gateway", "rate", "set_run_stats")}
    assert index["create_run"] < index["gateway"] < index["rate"]
    assert index["rate"] < index["set_run_stats"]
    assert index["set_run_stats"] < min(
        i for i, event in enumerate(events) if event.startswith("job:"))


def test_rate_profile_is_persisted_as_json_with_refs_and_no_secrets():
    """JSON-mode serialization carries the artifact REFERENCES; the raw result
    bodies and credentials never reach the run stats."""
    events: list = []
    registry, _ = _run(events, _orchestrator(events))

    stored = registry.run_stats["rate_limit"]
    assert stored["artifact_refs"] == [ARTIFACT_REF]  # refs, not bodies
    assert stored["traffic_policy"]["target_key"] == TARGET_KEY
    blob = repr(stored)
    assert "password" not in blob and "Authorization" not in blob
    assert "Bearer" not in blob and "Cookie" not in blob


def test_rate_stats_are_additive_and_never_clobber_analysis_stats():
    """The pipeline writes ONLY the `rate_limit` key: a JSONB merge keeps the
    analysis stats another writer already put in the same run row."""
    events: list = []
    registry = _RecordingRegistry(events)
    registry.run_stats["analysis"] = {"passes": 3}
    _run(events, _orchestrator(events), registry=registry)

    assert registry.run_stats["analysis"] == {"passes": 3}
    assert set(registry.run_stats) == {"analysis", "rate_limit"}


def test_heartbeat_ticks_during_a_slow_rate_turn(monkeypatch):
    """Step 3: the heartbeat stays alive ACROSS both turns - a slow rate turn
    must not trip the stale-run reaper."""
    ticks: list = []
    monkeypatch.setattr(pipeline.config, "HEARTBEAT_TICK_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda rid: ticks.append(rid))

    events: list = []
    profile = _profile()

    class _SlowRate(_FakeOrchestrator):
        async def run_rate_limit(self, **kw):
            events.append("rate")
            await asyncio.sleep(0.06)
            return profile

    _run(events, _SlowRate(events=events, profile=profile))

    assert len(ticks) >= 2, "heartbeat never ticked during the rate turn"


# --- Step 2: the branches ------------------------------------------------------


def test_rate_turn_receives_the_canonical_target_and_the_resolved_auth(tmp_path):
    """The pipeline derives the canonical target from `resolve_seed` and
    resolves the gateway-selected account's request material LAZILY - the
    harness headers carry the stored session, never the login credentials."""
    events: list = []
    orchestrator = _orchestrator(events)
    _run(events, orchestrator, store=_auth_store(tmp_path))

    assert orchestrator.rate_kwargs["target_key"] == TARGET_KEY
    assert orchestrator.rate_kwargs["url"] == TARGET_URL
    assert orchestrator.rate_kwargs["headers"] == {
        "Authorization": "Bearer T", "Cookie": "sid=S"}
    assert orchestrator.rate_kwargs["browser_only"] is False
    assert "PASSWORD" not in repr(orchestrator.rate_kwargs)


def test_anonymous_verdict_still_measures_anonymously():
    """No authenticated surface: the rate turn still runs, with NO auth
    headers, and the policy still configures the request jobs."""
    events: list = []
    orchestrator = _orchestrator(events, verdict=GatewayVerdict(
        outcome="anonymous", rationale="no authenticated surface"))
    _, seen = _run(events, orchestrator)

    assert orchestrator.rate_kwargs["headers"] == {}
    assert seen["httpx"]["extra"]["traffic_policy"]["target_key"] == TARGET_KEY


def test_browser_only_prunes_and_paces_the_steel_crawl(tmp_path):
    """Browser-only: the rate turn is asked with `browser_only=True`, the plan
    is pruned to the Steel crawl, and the crawl job still carries the policy."""
    store = _auth_store(tmp_path)
    store.replace_operator_state(
        "proj1", overview={"anti-bot": "waf:x", "http-client-replayability": False},
        accounts={"alice": {"credentials": {"username": "u", "password": "p",
                                            "login_url": "https://x/login"}}})
    events: list = []
    orchestrator = _orchestrator(
        events, verdict=GatewayVerdict(outcome="authenticated", account="alice",
                                       branch="browser_only", rationale="t"),
        profile=_conservative_profile())
    _, seen = _run(events, orchestrator, store=store,
                   job_subset=["subfinder", "httpx", "katana", "steel_crawl"])

    assert orchestrator.rate_kwargs["browser_only"] is True
    assert set(seen) == {"steel_crawl"}
    assert seen["steel_crawl"]["extra"]["traffic_policy"]["rate_per_s"] <= 1.0


def test_gateway_stop_runs_no_rate_turn_and_no_job():
    """The fail-close missing-credentials path stops BEFORE the rate turn: the
    run is marked failed and nothing runs."""
    events: list = []

    class _Stopper(_FakeOrchestrator):
        async def run_gateway(self, **kw):
            events.append("gateway")
            raise GatewayStop("no credentials")

    registry = _RecordingRegistry(events)
    _run(events, _Stopper(events=events), registry=registry)

    assert "rate" not in events
    assert not any(event.startswith("job:") for event in events)
    assert any("failed" in status for status in registry.statuses)


def test_degraded_gateway_still_attempts_an_anonymous_rate_turn():
    """Auth fail-open (no verdict) still measures the target - anonymously -
    and the run keeps every phase."""
    events: list = []
    orchestrator = _orchestrator(events, verdict=None)
    _, seen = _run(events, orchestrator)

    assert events.index("gateway") < events.index("rate")
    assert orchestrator.rate_kwargs["headers"] == {}
    assert "traffic_policy" in seen["httpx"]["extra"]


def test_rate_turn_failure_degrades_to_the_conservative_policy():
    """A raising rate turn never releases unthrottled traffic: the run
    continues under the conservative fallback policy, loudly."""
    events: list = []
    orchestrator = _orchestrator(events, rate_error=RuntimeError("controller down"))
    registry, seen = _run(events, orchestrator)

    policy = registry.run_stats["rate_limit"]["traffic_policy"]
    assert policy["rate_per_s"] <= 1.0
    assert registry.run_stats["rate_limit"]["outcome"] == "failed"
    assert seen["httpx"]["extra"]["traffic_policy"]["rate_per_s"] <= 1.0
    assert any(event.startswith("job:") for event in events)  # phases still ran


def test_an_orchestrator_without_the_rate_turn_degrades_conservatively():
    """Retro-compatibility: an injected factory whose actor predates #238 keeps
    the run alive under the conservative policy instead of crashing."""
    events: list = []

    class _LegacyActor:
        async def run_gateway(self, **kw):
            events.append("gateway")
            return GatewayVerdict(outcome="anonymous", rationale="t")

        async def stop(self):
            events.append("stop")

    registry, seen = _run(events, _LegacyActor())

    assert registry.run_stats["rate_limit"]["traffic_policy"]["rate_per_s"] <= 1.0
    assert seen["httpx"]["extra"]["traffic_policy"]["rate_per_s"] <= 1.0


# --- Step 4: the policy feed, without touching the templates --------------------


def test_http_jobs_carry_only_the_traffic_policy_and_no_flag_strings():
    """HTTP jobs gain `extra["traffic_policy"]` and nothing else: no flag
    string, no `{rate_flags}` slot, no template edit."""
    events: list = []
    _, seen = _run(events, _orchestrator(events))

    policy = seen["httpx"]["extra"]["traffic_policy"]
    assert policy["version"] == "traffic-policy/v2"
    assert policy == seen["katana"]["extra"]["traffic_policy"]
    assert "traffic_policy" not in seen["subfinder"]["extra"]
    for job, payload in seen.items():
        assert "rate_flags" not in payload["extra"]
        assert not any(isinstance(v, str) and "--rate" in v
                       for v in payload["extra"].values()), job
    from polymerhus.recon.control.jobs import JOBS
    assert "{rate_flags}" not in JOBS["httpx"].command_template


def test_default_preprocess_fn_preserves_the_traffic_policy():
    """Step 4: the policy rides verbatim through the deterministic preprocess
    into every pod input - the seam the pod reads it from."""
    from polymerhus.recon.control.job_agent import default_preprocess_fn
    from polymerhus.recon.control.jobs import JOBS

    policy = _profile().traffic_policy.model_dump(mode="json")
    inputs = default_preprocess_fn(
        [{"url": "https://app.t.com"}], JOBS["httpx"],
        {"project_id": "proj1", "traffic_policy": policy}, "")

    assert inputs and all(pi["extra"]["traffic_policy"] == policy for pi in inputs)


# --- Step 5: conservative Steel pacing -----------------------------------------


def _conservative_policy_dict(rate=1.0, min_delay_ms=1000.0):
    return TrafficPolicy(
        target_key=TARGET_KEY, host_patterns=[TARGET_KEY], rate_per_s=rate,
        burst=1, max_concurrency=1, min_delay_ms=min_delay_ms,
        source="conservative-fallback").model_dump(mode="json")


def test_crawl_pacing_reduces_caps_and_never_increases_them():
    from polymerhus.recon.crawl.crawl_agentic import derive_crawl_pacing

    pacing = derive_crawl_pacing(
        _conservative_policy_dict(), max_pages=50, max_iterations=30,
        navigate_wait_ms=800)

    assert pacing["max_concurrent_crawls"] == 1        # one crawl per target
    assert pacing["min_delay_ms"] == 1000              # the policy's cadence
    assert pacing["max_pages"] <= 50                   # reduced, never raised
    assert pacing["max_iterations"] <= 30

    # a policy that allows a FASTER cadence never speeds the crawl up
    fast = derive_crawl_pacing(
        _conservative_policy_dict(rate=20.0, min_delay_ms=50.0),
        max_pages=50, max_iterations=30, navigate_wait_ms=800)
    assert fast["min_delay_ms"] == 800
    assert fast["max_pages"] == 50 and fast["max_iterations"] == 30


def test_crawl_pacing_without_a_policy_keeps_the_operator_defaults():
    from polymerhus.recon.crawl.crawl_agentic import derive_crawl_pacing

    pacing = derive_crawl_pacing(None, max_pages=50, max_iterations=30,
                                 navigate_wait_ms=800)
    assert pacing == {"max_pages": 50, "max_iterations": 30, "min_delay_ms": 0,
                      "max_concurrent_crawls": 1}


def test_crawl_pod_forwards_the_traffic_policy_to_the_crawl_seam():
    """The crawl node reads the policy from `extra` and hands it to the crawl
    seam (declared on the seam's signature), which is what applies the pacing."""
    from polymerhus.recon.crawl import crawl_pod
    from polymerhus.recon.domain.parsers.steel_parser import parse as steel_parse
    from polymerhus.recon.domain.traffic_admission import BOUNDED_HTTP_COST
    from polymerhus.recon.domain.types import JobSpec

    job = JobSpec(tool="steel_crawl", skill="agentic_crawl", command_template="",
                  produces=["BaseURL"], consumes="BaseURL", use_auth=True,
                  configurator_mode="agent", traffic_cost=BOUNDED_HTTP_COST)
    seen: dict = {}

    def run_crawl_fn(target, *, scope, auth_cookies=None, steel_profile=None,
                     traffic_policy=None):
        seen["policy"] = traffic_policy
        return {"endpoints": [], "js_urls": []}

    policy = _conservative_policy_dict()
    pod = crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn, parse_fn=steel_parse,
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=lambda assets, observations, project_id, **kw: (
            len(assets), len(observations), assets, observations),
    )
    pod.invoke({
        "job": job, "input_asset": {"url": "https://app.t.com"},
        "asset_context": "",
        "extra": {"project_id": "proj1", "traffic_policy": policy},
        "session_id": "s", "project_id": "proj1",
    })

    assert seen["policy"] == policy


def test_one_active_crawl_per_target():
    """Serialization guard: two crawls for the SAME target never overlap."""
    from polymerhus.recon.crawl import crawl_agent

    active = {"now": 0, "max": 0}

    class _Tool:
        name = "steel_crawl_finish"

        async def ainvoke(self, args):
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            await asyncio.sleep(0.05)
            active["now"] -= 1
            return {"endpoints": [], "js_urls": []}

    class _LLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                message = type("M", (), {"content": ""})()
                message.tool_calls = [{"name": "steel_crawl_finish",
                                       "args": {}, "id": "1"}]
                return message
            message = type("M", (), {"content": ""})()
            message.tool_calls = []
            return message

    def _run():
        return asyncio.run(crawl_agent.run_crawl(
            "https://app.t.com", scope=["t.com"], tools=[_Tool()], llm=_LLM()))

    import threading
    threads = [threading.Thread(target=_run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert active["max"] == 1, "two crawls for one target ran concurrently"
