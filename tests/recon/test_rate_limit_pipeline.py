"""Pipeline tier: direct rate mapping, persistence, and the Steel fallback.

Exercises the REAL `run_pipeline` boundary: after the auth gateway resolves and
BEFORE phase 0, the PIPELINE invokes the rate mapper directly, the public
`RateProfile` lands in `recon_runs.stats["rate_limit"]`, and every HTTP job -
plus the agent-driven Steel crawl - carries the serialized `TrafficPolicy`
through `extra["traffic_policy"]`. No live model, no live database, no live
Kali.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from polymerhus.recon.control import pipeline
from polymerhus.recon.control import configurator as C
from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.control.authn_loop import GatewayVerdict
from polymerhus.recon.control.orchestrator_agent import GatewayStop
from polymerhus.recon.domain.rate_limit import (
    RateLimitSafetyBudget,
    RateProfile,
    RateLoopVerdict,
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
        self.job_rows: list = []

    def create_run(self, *a, **k):
        self.events.append("create_run")

    def set_run_status(self, *a, **k):
        self.statuses.append(a)
        self.events.append("set_run_status")

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        self.job_rows.append(
            {"run_id": run_id, "phase": phase, "job": job, "status": status}
        )

    def set_run_stats(self, run_id, stats):
        # One event per written key, so the tests can assert the ORDER of the
        # two additive writes (rate_limit vs traffic_admission) against the
        # first runner.
        for key in stats:
            self.events.append(f"set_run_stats:{key}")
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
    """The auth-only actor seam. `run_rate_limit` is a forbidden sentinel: the
    pipeline must use the injected mapper even if this method still exists."""

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
        self._events.append("rate_turn_forbidden")
        self.rate_kwargs = dict(kw)
        return RateProfile.conservative(
            TARGET_KEY, [TARGET_KEY], RateLimitSafetyBudget(),
            "the actor rate turn is forbidden after direct mapping",
            outcome="failed",
        )

    async def stop(self):
        self._events.append("stop")


def _mapper(events, *, profile=None, error=None, calls=None):
    """The pipeline-owned mapping seam, with compact kwargs recording."""

    async def map_rate_profile(
        project_id, run_id, target_key, url, headers, host_patterns
    ):
        events.append("map")
        if calls is not None:
            calls.update(
                project_id=project_id,
                run_id=run_id,
                target_key=target_key,
                url=url,
                headers=dict(headers),
                host_patterns=list(host_patterns),
            )
        if error is not None:
            raise error
        return profile if profile is not None else _profile()

    return map_rate_profile


def _run(events, orchestrator, *, registry=None, store=None, job_subset=None,
         settings=None, prepare_inputs=None, pod_exports_for=None,
         fetch_capabilities=None, map_rate_profile=None, mapper_kwargs=None,
         write_posture=None, configure_phase=None):
    """Wire the real `run_pipeline` over a recording orchestrator + registry."""
    registry = registry or _RecordingRegistry(events)
    seen: dict = {}
    if map_rate_profile is None:
        map_rate_profile = _mapper(
            events,
            profile=getattr(orchestrator, "_profile", None),
            error=getattr(orchestrator, "_rate_error", None),
            calls=mapper_kwargs,
        )

    async def fake_run_job(job, input_assets, *, run_id, phase, extra, prepared_pod_inputs=None):
        events.append(f"job:{job.tool}")
        seen[job.tool] = {
            "assets": list(input_assets),
            "extra": dict(extra),
            "prepared": prepared_pod_inputs,
        }
        if pod_exports_for is None:
            return []
        return pod_exports_for(job, input_assets)

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
            prepare_inputs=prepare_inputs,
            fetch_capabilities=fetch_capabilities,
            map_rate_profile=map_rate_profile,
            write_posture=write_posture,
            configure_phase=configure_phase,
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


def test_mapping_runs_after_auth_and_persists_before_phase_zero():
    """`create_run -> auth -> mapper -> set_run_stats(rate_limit) -> phase 0`."""
    events: list = []
    registry, _ = _run(events, _orchestrator(events))

    assert registry.run_stats["rate_limit"]["outcome"] == "mapped"
    index = {name: events.index(name) for name in (
        "create_run", "gateway", "map", "set_run_stats:rate_limit")}
    assert index["create_run"] < index["gateway"] < index["map"]
    assert index["map"] < index["set_run_stats:rate_limit"]
    assert index["set_run_stats:rate_limit"] < min(
        i for i, event in enumerate(events) if event.startswith("job:"))
    assert "rate_turn_forbidden" not in events


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
    """The pipeline adds the `rate_limit` key through the additive JSONB seam:
    a merge keeps the analysis stats another writer already put in the row."""
    events: list = []
    registry = _RecordingRegistry(events)
    registry.run_stats["analysis"] = {"passes": 3}
    _run(events, _orchestrator(events), registry=registry)

    assert registry.run_stats["analysis"] == {"passes": 3}
    assert set(registry.run_stats) == {"analysis", "rate_limit"}


def test_heartbeat_ticks_during_a_slow_rate_turn(monkeypatch):
    """The heartbeat stays alive during a slow DIRECT mapper call."""
    ticks: list = []
    monkeypatch.setattr(pipeline.config, "HEARTBEAT_TICK_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda rid: ticks.append(rid))

    events: list = []
    profile = _profile()

    async def slow_mapper(*args, **kwargs):
        events.append("map")
        await asyncio.sleep(0.06)
        return profile

    _run(events, _orchestrator(events), map_rate_profile=slow_mapper)

    assert len(ticks) >= 2, "heartbeat never ticked during the mapper call"


def test_default_mapper_builds_the_harness_and_uses_the_baseline_profile(monkeypatch):
    """The production mapper is controller-owned and LLM-free: it builds the
    Kali executor, runs `map()`, then builds the baseline profile."""
    from polymerhus.recon.control import rate_limit_runner as runner_module

    calls: list[tuple] = []
    profile = _profile()

    class _Harness:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        async def map(self):
            calls.append(("map", None))
            return object()

        def build_baseline_profile(self):
            calls.append(("baseline", None))
            return profile

    monkeypatch.setattr(runner_module, "RateLimitHarness", _Harness)
    monkeypatch.setattr(runner_module, "build_kali_execute", lambda **kw: "EXEC")

    result = asyncio.run(pipeline._default_map_rate_profile(
        "proj1", "run1", TARGET_KEY, TARGET_URL,
        {"Authorization": "Bearer T"}, [TARGET_KEY],
    ))

    assert result is profile
    assert [name for name, _ in calls] == ["init", "map", "baseline"]
    init = calls[0][1]
    assert init["target_key"] == TARGET_KEY
    assert init["url"] == TARGET_URL
    assert init["headers"] == {"Authorization": "Bearer T"}
    assert init["host_patterns"] == [TARGET_KEY]
    assert init["execute"] == "EXEC"
    assert init["project_id"] == "proj1"
    assert init["run_id"] == "run1"


# --- Step 2: the branches ------------------------------------------------------


def test_mapper_receives_the_canonical_target_and_the_resolved_auth(tmp_path):
    """The pipeline derives the canonical target from `resolve_seed` and
    resolves the gateway-selected account's request material LAZILY - the
    harness headers carry the stored session, never the login credentials."""
    events: list = []
    orchestrator = _orchestrator(events)
    mapper_kwargs: dict = {}
    _run(events, orchestrator, store=_auth_store(tmp_path),
         mapper_kwargs=mapper_kwargs)

    assert mapper_kwargs["target_key"] == TARGET_KEY
    assert mapper_kwargs["url"] == TARGET_URL
    assert mapper_kwargs["headers"] == {
        "Authorization": "Bearer T", "Cookie": "sid=S"}
    assert mapper_kwargs["host_patterns"] == [TARGET_KEY]
    assert "PASSWORD" not in repr(mapper_kwargs)
    assert "rate_turn_forbidden" not in events


def test_domain_target_can_explicitly_use_http():
    """#238 B5: a DNS-name target may legitimately speak HTTP. When the project
    declares `target_scheme=http`, the mapping replays over HTTP - the scheme is
    taken from the configured value, not the seed KIND."""
    events: list = []
    orchestrator = _orchestrator(events)
    mapper_kwargs: dict = {}
    _run(events, orchestrator,
         settings={"target_domain": SEED, "target_scheme": "http"},
         mapper_kwargs=mapper_kwargs)

    assert mapper_kwargs["url"] == f"http://{TARGET_KEY}/"
    assert mapper_kwargs["target_key"] == TARGET_KEY


def test_legacy_inference_is_unchanged_when_no_scheme_is_configured():
    """Absent `target_scheme`, a domain still infers HTTPS (the pre-#238
    behaviour) - only an EXPLICIT setting changes the transport."""
    events: list = []
    orchestrator = _orchestrator(events)
    mapper_kwargs: dict = {}
    _run(events, orchestrator, settings={"target_domain": SEED},
         mapper_kwargs=mapper_kwargs)

    assert mapper_kwargs["url"] == f"https://{TARGET_KEY}/"


def test_invalid_target_scheme_fails_loudly():
    """A scheme that is neither http nor https is a configuration error, not a
    silent fallback to a guessed transport."""
    events: list = []
    with pytest.raises(ValueError):
        _run(events, _orchestrator(events),
             settings={"target_domain": SEED, "target_scheme": "ftp"})


def test_anonymous_verdict_still_measures_anonymously():
    """No authenticated surface: the rate turn still runs, with NO auth
    headers, and the policy still configures the request jobs."""
    events: list = []
    orchestrator = _orchestrator(events, verdict=GatewayVerdict(
        outcome="anonymous", rationale="no authenticated surface"))
    mapper_kwargs: dict = {}
    _, seen = _run(events, orchestrator, mapper_kwargs=mapper_kwargs)

    assert mapper_kwargs["headers"] == {}
    assert seen["httpx"]["extra"]["traffic_policy"]["target_key"] == TARGET_KEY


def test_browser_only_never_calls_the_mapper_and_uses_conservative_posture(tmp_path):
    """Browser-only cannot be replayed over HTTP: the mapper is never called,
    the profile is conservative/inconclusive, and only Steel remains."""
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
    registry, seen = _run(
        events, orchestrator, store=store,
        job_subset=["subfinder", "httpx", "katana", "steel_crawl"],
    )

    assert "map" not in events
    assert "rate_turn_forbidden" not in events
    stored = registry.run_stats["rate_limit"]
    assert stored["outcome"] == "inconclusive"
    assert stored["traffic_policy"]["rate_per_s"] <= 1.0
    assert set(seen) == {"steel_crawl"}
    assert seen["steel_crawl"]["extra"]["traffic_policy"]["rate_per_s"] <= 1.0


def test_gateway_stop_runs_no_mapper_and_no_job():
    """The fail-close missing-credentials path stops BEFORE the mapper: the run
    is marked failed and nothing runs."""
    events: list = []

    class _Stopper(_FakeOrchestrator):
        async def run_gateway(self, **kw):
            events.append("gateway")
            raise GatewayStop("no credentials")

    registry = _RecordingRegistry(events)
    _run(events, _Stopper(events=events), registry=registry)

    assert "map" not in events
    assert "rate_turn_forbidden" not in events
    assert not any(event.startswith("job:") for event in events)
    assert any("failed" in status for status in registry.statuses)


def test_degraded_gateway_still_attempts_an_anonymous_mapping():
    """Auth fail-open (no verdict) still measures the target - anonymously -
    and the run keeps every phase."""
    events: list = []
    orchestrator = _orchestrator(events, verdict=None)
    mapper_kwargs: dict = {}
    _, seen = _run(events, orchestrator, mapper_kwargs=mapper_kwargs)

    assert events.index("gateway") < events.index("map")
    assert mapper_kwargs["headers"] == {}
    assert "traffic_policy" in seen["httpx"]["extra"]


def test_mapper_failure_degrades_to_the_conservative_policy():
    """A raising mapper never releases unthrottled traffic: the run
    continues under the conservative fallback policy, loudly."""
    events: list = []
    orchestrator = _orchestrator(events, rate_error=RuntimeError("controller down"))
    registry, seen = _run(events, orchestrator)

    policy = registry.run_stats["rate_limit"]["traffic_policy"]
    assert policy["rate_per_s"] <= 1.0
    assert registry.run_stats["rate_limit"]["outcome"] == "failed"
    assert seen["httpx"]["extra"]["traffic_policy"]["rate_per_s"] <= 1.0
    assert any(event.startswith("job:") for event in events)  # phases still ran


def test_an_orchestrator_without_the_rate_turn_still_uses_the_pipeline_mapper():
    """The pipeline owns mapping: an auth-only actor needs no rate method."""
    events: list = []

    class _LegacyActor:
        async def run_gateway(self, **kw):
            events.append("gateway")
            return GatewayVerdict(outcome="anonymous", rationale="t")

        async def stop(self):
            events.append("stop")

    registry, seen = _run(events, _LegacyActor())

    assert "map" in events
    assert "rate_turn_forbidden" not in events
    assert registry.run_stats["rate_limit"]["outcome"] == "mapped"
    assert seen["httpx"]["extra"]["traffic_policy"]["rate_per_s"] == 4.0


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


# --- Task 6: Configurator materialization at the phase boundary ------------------


def _configure(
    events,
    *,
    selected: set[str] | None = None,
    command: str = "httpx -u {target} -rate-limit 2",
):
    def configure_phase(project_id, run_id, phase, target_key, offers):
        events.append(f"configure:{phase}")
        pods = []
        for offer in offers.offers:
            if selected is not None and offer.input_id not in selected:
                continue
            pods.append(C.ReconPodProposal(
                job_name=offer.job_name,
                input_id=offer.input_id,
                command=(
                    None if offer.configurator_mode == "agent"
                    else (offer.command_template or command)
                ),
                rationale="test",
            ))
        return C.ConfiguratorDecision(
            phase=phase,
            target_key=target_key,
            posture_status="known_target",
            pods=pods,
            rationale="test",
        )

    return configure_phase


def test_configurator_plan_controls_materialized_jobs_and_commands():
    events: list = []
    registry, seen = _run(
        events,
        _orchestrator(events),
        job_subset=["subfinder", "httpx"],
        configure_phase=_configure(events, selected={"httpx:0"}),
    )

    assert "configure:0" in events
    assert "job:httpx" in events
    assert "job:subfinder" not in events
    assert seen["httpx"]["prepared"][0]["configured_command"] == (
        JOBS["httpx"].command_template
    )
    assert "traffic_admission" not in registry.run_stats


def test_empty_configurator_plan_runs_no_phase_jobs():
    events: list = []
    registry, seen = _run(
        events,
        _orchestrator(events),
        job_subset=["subfinder", "httpx"],
        configure_phase=_configure(events, selected=set()),
    )

    assert "configure:0" in events
    assert not any(event.startswith("job:") for event in events)
    assert seen == {}
    assert registry.statuses[-1][1] == "complete"
    assert "traffic_admission" not in registry.run_stats


def test_invalid_configurator_decision_fails_before_any_job_runs():
    events: list = []
    registry = _RecordingRegistry(events)

    def invalid_configure(project_id, run_id, phase, target_key, offers):
        events.append(f"configure:{phase}")
        return C.ConfiguratorDecision(
            phase=phase,
            target_key=target_key,
            posture_status="known_target",
            pods=[
                C.ReconPodProposal(
                    job_name="httpx",
                    input_id="httpx:0",
                    command="httpx -u {target}",
                    rationale="valid",
                ),
                C.ReconPodProposal(
                    job_name="httpx",
                    input_id="unknown:0",
                    command="httpx -u {target}",
                    rationale="invalid",
                ),
            ],
            rationale="mixed",
        )

    _run(
        events,
        _orchestrator(events),
        registry=registry,
        job_subset=["httpx"],
        configure_phase=invalid_configure,
    )

    assert "configure:0" in events
    assert not any(event.startswith("job:") for event in events)
    assert any(status[1] == "failed" for status in registry.statuses)


def test_each_candidate_is_derived_exactly_once_and_prepared_inputs_reach_run_job():
    events: list = []
    derived: list[str] = []

    def recording_prepare(inputs, job, extra, asset_context):
        derived.append(job.tool)
        return [{"input_asset": {"url": "https://a"}, "asset_context": "", "extra": dict(extra)}]

    _, seen = _run(
        events, _orchestrator(events),
        job_subset=["subfinder", "httpx", "katana"],
        prepare_inputs=recording_prepare,
    )

    assert derived.count("httpx") == 1
    assert derived.count("katana") == 1
    prepared = seen["httpx"]["prepared"]
    assert prepared is not None and len(prepared) == 1
    assert prepared[0]["input_asset"] == {"url": "https://a"}
    assert isinstance(prepared[0]["extra"], dict) and prepared[0]["extra"]


def test_model_facing_verdicts_cannot_carry_admission_fields():
    """The LLM cannot raise or reintroduce anything: neither model-facing verdict
    type accepts a rate, concurrency, budget, or phase-list field."""
    from pydantic import ValidationError

    for model in (GatewayVerdict, RateLoopVerdict):
        for field in (
            "rate_per_s", "max_concurrency", "budget",
            "candidate_jobs", "materialized_phases",
        ):
            with pytest.raises(ValidationError):
                model(**{field: 1})


# --- #238 A9: Kali runtime-capability negotiation --------------------------------


def _incompatible_status() -> dict:
    return {
        "ok": True,
        "traffic_governor": {
            "governor_enabled": False,
            "supported_policy_versions": ["traffic-policy/v1"],
        },
        "build": {"revision": "x", "vegeta_version": "v12.12.0"},
        "wordlists": {},
    }


def test_incompatible_runtime_skips_mapping_and_runs_only_selected_safe_work():
    events: list = []
    orchestrator = _orchestrator(events)
    registry, _ = _run(
        events,
        orchestrator,
        job_subset=["subfinder", "httpx", "katana", "ffuf"],
        fetch_capabilities=_incompatible_status,
        configure_phase=_configure(events, selected={"subfinder:0"}),
    )

    assert "map" not in events
    assert "job:subfinder" in events
    assert "job:httpx" not in events
    assert "job:katana" not in events
    assert "job:ffuf" not in events
    assert "traffic_admission" not in registry.run_stats


def test_a_compatible_runtime_proceeds_normally():
    events: list = []
    registry, _ = _run(
        events,
        _orchestrator(events),
        job_subset=["subfinder", "httpx", "katana"],
        fetch_capabilities=lambda: {
            "traffic_governor": {
                "governor_enabled": True,
                "supported_policy_versions": ["traffic-policy/v2"],
            },
            "build": {"revision": "x", "vegeta_version": "v12.13.0"},
            "wordlists": {
                "/usr/share/seclists/Discovery/Web-Content/common.txt": 4750
            },
        },
        configure_phase=_configure(events, selected={"httpx:0"}),
    )
    assert "map" in events
    assert "job:httpx" in events
    assert "traffic_admission" not in registry.run_stats


def test_an_unreadable_capability_surface_runs_only_selected_safe_work():
    events: list = []

    def boom():
        raise RuntimeError("kali MCP unavailable")

    _run(
        events,
        _orchestrator(events),
        job_subset=["subfinder", "httpx"],
        fetch_capabilities=boom,
        configure_phase=_configure(events, selected={"subfinder:0"}),
    )
    assert "job:subfinder" in events
    assert "job:httpx" not in events
