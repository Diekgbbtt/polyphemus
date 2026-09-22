# tests/recon/test_pipeline.py
"""Pipeline orchestrator: phase barrier, best-effort status derivation, and
the auth channel.

Fully mocked - `run_job`, `load_settings`, `registry`, and `read_assets` are
all injected fakes. No live Neo4j/Postgres/pod graph involved.
"""
import asyncio

from polymerhus.recon.control import pipeline
from polymerhus.recon.domain.types import PodExport


class FakeRegistry:
    def __init__(self):
        self.create_run_calls = []
        self.set_run_status_calls = []
        self.upsert_job_calls = []

    def create_run(self, run_id, project_id):
        self.create_run_calls.append((run_id, project_id))

    def set_run_status(self, run_id, status, current_phase=None):
        self.set_run_status_calls.append((run_id, status, current_phase))

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        self.upsert_job_calls.append(
            {
                "run_id": run_id,
                "phase": phase,
                "job": job,
                "status": status,
                "stats": stats,
                "error": error,
            }
        )


def make_load_settings(settings):
    return lambda project_id: settings


def make_read_assets(default_name="seed"):
    calls = []

    # Mirror the real read_assets signature (node_type, project_id, where=None):
    # jobs with a `consumes_where` selector (jsluice, and D16-gated kiterunner)
    # are read via the 3-arg form, so the mock must accept `where` or it
    # TypeErrors and the job silently degrades. The selector itself is exercised
    # in test_selectors/test_jobs; here we just return an input so run_job fires.
    def read_assets(node_type, project_id, where=None):
        calls.append((node_type, project_id))
        return [{"name": default_name}]

    read_assets.calls = calls
    return read_assets


def test_phases_run_in_order_behind_a_barrier():
    """A phase-1 job's run_job must not be called until every phase-0 job's
    run_job has returned. Enforced by holding the sole phase-0 job open on
    an asyncio.Event the test controls."""
    call_order = []
    phase0_started = asyncio.Event()
    phase0_gate = asyncio.Event()

    async def run_job(job, input_assets, *, run_id, phase, extra):
        call_order.append((phase, job.tool))
        if phase == 0:
            phase0_started.set()
            await phase0_gate.wait()
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}

    async def scenario():
        task = asyncio.create_task(
            pipeline.run_pipeline(
                "proj1",
                run_id="run1",
                job_subset=["subfinder", "dnsx"],
                run_job=run_job,
                load_settings=make_load_settings(settings),
                registry=registry,
                read_assets=make_read_assets(),
            )
        )
        # Deterministic barrier, not a sleep: wait until phase-0's run_job has
        # actually started (the old fixed 50ms sleep was a timing race - under
        # load the pipeline might not have reached run_job yet and the assertion
        # flaked on an empty call_order).
        await phase0_started.wait()
        # Phase 1 (dnsx) must not have started while phase 0 is still gated.
        assert call_order == [(0, "subfinder")]

        phase0_gate.set()
        await task

    asyncio.run(scenario())

    assert call_order == [(0, "subfinder"), (1, "dnsx")]
    assert registry.set_run_status_calls[-1] == ("run1", "complete", None)


def test_same_phase_jobs_run_sequentially_not_concurrently():
    """Within a phase, one job's run_job must fully return before the next
    job's run_job is even called - peak concurrency inside a phase is one
    job's own pod fan-out (MAX_PODS), never (jobs in phase) x MAX_PODS. Phase
    0 has two scheduled jobs (subfinder/whois; amass is out of production);
    use both and have run_job track a running-count so any overlap (a second
    job starting before the first's run_job returns) would be caught."""
    running = 0
    max_running = 0
    order = []

    async def run_job(job, input_assets, *, run_id, phase, extra):
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        order.append(job.tool)
        # Yield to the event loop - if the orchestrator had started the next
        # job concurrently, its run_job would run here too and bump `running`.
        await asyncio.sleep(0.01)
        running -= 1
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "whois"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=make_read_assets(),
        )
    )

    assert max_running == 1
    # Sequential = job_configs insertion order = PHASES order.
    assert order == ["subfinder", "whois"]


def test_job_with_all_pods_failed_is_degraded_and_run_completes():
    async def run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="failed", error="boom")]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=make_read_assets(),
        )
    )

    statuses = [c["status"] for c in registry.upsert_job_calls if c["job"] == "subfinder"]
    assert statuses[-1] == "degraded"
    assert registry.set_run_status_calls[-1] == ("run1", "complete", None)


def test_feed_projects_store_material_only_to_use_auth_jobs(tmp_path):
    """#243: the lazy feed - the gateway verdict binds the account IDENTIFIER
    and each phase's tool configuration resolves the store material at
    assembly. Request jobs get the flat request projection (snapshot +
    located tokens); non-auth jobs are unchanged."""
    from polymerhus.app.auth.store import AuthStore
    from polymerhus.recon.control.authn_loop import GatewayVerdict

    store = AuthStore(tmp_path)
    store.replace_operator_state(
        "proj1", overview={"login_endpoint": "https://x/login"},
        accounts={"alice": {
            "credentials": {"username": "u", "password": "p",
                            "login_url": "https://x/login"},
            "tokens": {"Authorization": {"value": "Bearer T",
                                         "location": "header"}},
            "steel": {"profile": "proj1-alice"},
            "snapshot": {"cookies": [{"name": "sid", "value": "S"}]},
        }})

    class _Gateway:
        async def run_gateway(self, **kw):
            return GatewayVerdict(outcome="authenticated", account="alice",
                                  branch="request", rationale="t")

        async def stop(self): pass

    seen_extra = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        seen_extra[job.tool] = extra
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=make_read_assets(),
            orchestrator_factory=lambda run_id: _Gateway(),
            auth_store=store,
        )
    )

    # scope_domain rides in extra alongside project_id (D14/curator scope gate);
    # "*.t.com" -> seed_host "t.com".
    assert seen_extra["subfinder"] == {"project_id": "proj1", "scope_domain": "t.com"}
    assert seen_extra["httpx"]["auth_account"] == "alice"  # identifier rides
    assert seen_extra["httpx"]["auth_context"] == {  # store-resolved projection
        "cookies": [{"name": "sid", "value": "S"}],
        "Authorization": "Bearer T"}
    assert seen_extra["katana"]["auth_context"] == seen_extra["httpx"]["auth_context"]
    # the agent-driven crawl gets the persisted profile key plus cookies only
    assert seen_extra["steel_crawl"]["auth_account"] == "alice"
    assert seen_extra["steel_crawl"]["steel_profile"] == "proj1-alice"
    assert seen_extra["steel_crawl"]["auth_context"] == {
        "cookies": [{"name": "sid", "value": "S"}]}


def test_feed_absent_without_a_verdict_account():
    """#243: no gateway account (anonymous verdict) - use_auth jobs run with
    no auth keys at all, exactly like non-auth jobs."""
    from polymerhus.recon.control.authn_loop import GatewayVerdict

    class _Gateway:
        async def run_gateway(self, **kw):
            return GatewayVerdict(outcome="anonymous",
                                  rationale="no authenticated surface")

        async def stop(self): pass

    seen_extra = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        seen_extra[job.tool] = extra
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "dnsx", "naabu", "httpx"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=make_read_assets(),
            orchestrator_factory=lambda run_id: _Gateway(),
        )
    )

    assert seen_extra["httpx"] == {"project_id": "proj1", "scope_domain": "t.com"}


def test_run_job_exception_marks_job_degraded_and_pipeline_still_completes():
    async def run_job(job, input_assets, *, run_id, phase, extra):
        raise RuntimeError("boom")

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=make_read_assets(),
        )
    )

    statuses = [c["status"] for c in registry.upsert_job_calls if c["job"] == "subfinder"]
    assert statuses[-1] == "degraded"
    assert registry.set_run_status_calls[-1] == ("run1", "complete", None)


def test_no_pod_exports_marks_job_skipped():
    async def run_job(job, input_assets, *, run_id, phase, extra):
        return []

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=make_read_assets(),
        )
    )

    statuses = [c["status"] for c in registry.upsert_job_calls if c["job"] == "subfinder"]
    assert statuses[-1] == "skipped"


def test_read_assets_raising_degrades_only_that_job_and_run_still_completes():
    """F3: phase-setup (`read_assets`/`upsert_job(in_progress)`) must be
    best-effort per job too, not just `run_job` - a registry/Neo4j blip on
    one job's setup must not leave the whole run stuck non-terminal."""

    async def run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success")]

    def flaky_read_assets(node_type, project_id):
        if node_type == "Subdomain":
            raise RuntimeError("neo4j blip")
        return [{"name": "seed"}]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "dnsx"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=flaky_read_assets,
        )
    )

    dnsx_statuses = [c["status"] for c in registry.upsert_job_calls if c["job"] == "dnsx"]
    assert dnsx_statuses == ["degraded"]
    assert registry.upsert_job_calls[-1]["error"] == "neo4j blip"

    subfinder_statuses = [c["status"] for c in registry.upsert_job_calls if c["job"] == "subfinder"]
    assert subfinder_statuses[-1] == "success"

    assert registry.set_run_status_calls[-1] == ("run1", "complete", None)


def test_phase0_uses_seed_assets_later_phases_use_read_assets():
    seen_inputs = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        seen_inputs[job.tool] = input_assets
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}
    read_assets = make_read_assets(default_name="from-neo4j")

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "dnsx"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=read_assets,
        )
    )

    assert seen_inputs["subfinder"] == [{"name": "t.com"}]
    # D11/D14: the apex seed host is prepended into the Subdomain-consuming
    # job's input set (before the read_assets-sourced subdomains).
    assert seen_inputs["dnsx"] == [{"name": "t.com"}, {"name": "from-neo4j"}]
    assert ("Subdomain", "proj1") in read_assets.calls


def test_job_stats_records_consumed_and_produced_lineage():
    """D12: recon_jobs.stats must carry per-job data lineage - consumed
    (input-asset count) and produced (sum of pod assets_merged /
    observations_merged) - alongside the existing pod counts.

    Uses a wildcard target so discovery runs under the D14 scope gate; the
    D11 apex-prepend means dnsx consumes the apex plus the read_assets nodes."""
    async def run_job(job, input_assets, *, run_id, phase, extra):
        # Two pods, producing 3+2 assets and 1+4 observations merged.
        return [
            PodExport(input_asset={}, verdict="success",
                      assets_merged=3, observations_merged=1),
            PodExport(input_asset={}, verdict="success",
                      assets_merged=2, observations_merged=4),
        ]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}
    # read_assets returns 2 input assets for phase-1 dnsx.
    def read_assets(node_type, project_id):
        return [{"name": "a"}, {"name": "b"}]

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "dnsx"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=read_assets,
        )
    )

    # Phase-0 subfinder: consumed == 1 (the single Domain seed asset).
    subfinder = [c for c in registry.upsert_job_calls
                 if c["job"] == "subfinder" and c["stats"] is not None][-1]
    assert subfinder["stats"]["consumed"] == 1
    assert subfinder["stats"]["produced_assets"] == 5
    assert subfinder["stats"]["produced_observations"] == 5

    # Phase-1 dnsx: consumed == 3 (the D11 apex-prepend + read_assets' two).
    dnsx = [c for c in registry.upsert_job_calls
            if c["job"] == "dnsx" and c["stats"] is not None][-1]
    assert dnsx["stats"]["consumed"] == 3
    assert dnsx["stats"]["produced_assets"] == 5
    assert dnsx["stats"]["produced_observations"] == 5
    # Existing pod counts still present (not regressed).
    assert dnsx["stats"]["pods"] == 2


def test_reprofile_job_stats_surface_endpoints_total():
    """#208: the reprofile pod is ONE pod for the WHOLE pass - the export's
    `endpoints_total` (the probe-set size) must surface into recon_jobs.stats
    so the phase's lineage is verifiable from persisted state (the D12
    `consumed` count is the pre-dedup endpoint population)."""
    async def run_job(job, input_assets, *, run_id, phase, extra):
        if job.tool == "httpx_reprofile":
            return [PodExport(
                input_asset={"endpoints": [{"url": "https://h/a"}, {"url": "https://h/b"}]},
                verdict="success",
                stats={"command": "httpx -l ...", "endpoints_total": 2},
            )]
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "*.t.com"}
    def read_assets(node_type, project_id):
        return [{"url": "https://h/a"}, {"url": "https://h/b"}]

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run-rp",
            job_subset=["subfinder", "httpx", "httpx_reprofile"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=read_assets,
        )
    )

    rp = [c for c in registry.upsert_job_calls
          if c["job"] == "httpx_reprofile" and c["stats"] is not None][-1]
    assert rp["stats"]["pods"] == 1
    assert rp["stats"]["endpoints_total"] == 2


def test_batched_jsluice_job_gets_filtered_read_and_apex_for_downstream_batching():
    """D17/Q5+Q6 + C3: the jsluice job's read is filtered by its `consumes_where`
    (only `.js`/`.mjs` Endpoints reach it) - the pipeline's job - and the pipeline
    supplies `extra["apex_registrable"]` for the reduce+pack the JOB AGENT now
    performs downstream (asserted in test_job_agent.py). jsluice is not a
    discovery job, so it runs even though the bare `houseofhr.com` target is
    exact-mode under the D14 scope gate."""
    seen_inputs = {}
    seen_extra = {}
    where_seen = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        seen_inputs[job.tool] = input_assets
        seen_extra[job.tool] = extra
        return [PodExport(input_asset={}, verdict="success")]

    # A read_assets that honors the optional `where` selector, returning a mix
    # of many .js bundles across two first-party hosts plus non-JS noise.
    def read_assets(node_type, project_id, where=None):
        where_seen[node_type] = where
        if node_type != "Endpoint":
            return [{"name": "www.houseofhr.com"}]
        assets = [{"path": "/app.css", "url": "https://a.houseofhr.com/app.css"}]
        for i in range(60):
            assets.append({"path": f"/b{i}.js", "url": f"https://a.houseofhr.com/b{i}.js"})
        from polymerhus.recon.domain.selectors import apply_selector
        return apply_selector(assets, where)

    registry = FakeRegistry()
    settings = {"target_domain": "houseofhr.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "projX",
            run_id="runX",
            job_subset=["subfinder", "httpx", "jsluice"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=read_assets,
        )
    )

    # The Endpoint read carried the jsluice path-suffix selector.
    sel = where_seen["Endpoint"]
    assert sel is not None and sel.field == "path" and set(sel.values) == {".js", ".mjs"}

    # C3: the pipeline passes the RAW filtered .js assets (no .css noise) to
    # run_job and supplies apex_registrable in extra; the batch reduce+pack now
    # happens inside the job agent's preprocess (not the pipeline).
    js_inputs = seen_inputs["jsluice"]
    assert len(js_inputs) == 60
    assert all(pi["url"].endswith(".js") for pi in js_inputs)
    assert seen_extra["jsluice"]["apex_registrable"] == "houseofhr.com"


# --- D14 scope gate + D11 apex probe --------------------------------------


def _run_and_capture(settings, *, job_subset=None):
    """Drive a fully-mocked pipeline, returning (call_order, seen_inputs)."""
    call_order = []
    seen_inputs = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        call_order.append(job.tool)
        seen_inputs[job.tool] = input_assets
        return [PodExport(input_asset={}, verdict="success")]

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=job_subset,
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=FakeRegistry(),
            read_assets=make_read_assets(default_name="discovered.t.com"),
        )
    )
    return call_order, seen_inputs


def test_exact_mode_suppresses_subdomain_discovery_jobs():
    """D14: an exact host suppresses subfinder/amass/puredns/dnsx entirely."""
    call_order, _ = _run_and_capture({"target_domain": "app.t.com"})

    assert "subfinder" not in call_order
    assert "amass" not in call_order
    assert "puredns" not in call_order
    assert "dnsx" not in call_order
    # Non-discovery jobs still run.
    assert "whois" in call_order
    assert "httpx" in call_order
    assert "naabu" in call_order


def test_exact_mode_keeps_subdomain_takeover():
    """D14 carve-out: takeover scanning stays enabled in exact mode."""
    call_order, seen_inputs = _run_and_capture({"target_domain": "app.t.com"})

    assert "subdomain_takeover" in call_order
    # It runs against the seeded exact host even though discovery is off
    # (prepended; the mocked read_assets adds a stray node after it).
    assert seen_inputs["subdomain_takeover"][0] == {"name": "app.t.com"}


def test_exact_mode_seeds_single_host_into_httpx_and_naabu():
    """D14: in exact mode the single host must reach the Subdomain-consuming
    probes even though no discovery job produced it. read_assets returns a
    stray node; only the seeded exact host should be probed here (prepended)."""
    _, seen_inputs = _run_and_capture({"target_domain": "app.t.com"})

    assert seen_inputs["httpx"][0] == {"name": "app.t.com"}
    assert seen_inputs["naabu"][0] == {"name": "app.t.com"}
    # D14 Q2: in exact mode the Domain-consuming phase-0 root is the exact
    # seed host (NOT the registrable apex), so ungated passive harvesters
    # (gau/paramspider) stay confined to the in-scope host.
    assert seen_inputs["whois"] == [{"name": "app.t.com"}]


def test_seed_domain_host_exact_mode_is_single_in_scope_host():
    """D14/D19: a later-phase Domain-consuming harvester must run EXACTLY ONE pod
    against the in-scope exact host - one host, never fanned out per discovered
    subdomain (the wildcard rate-ban risk). Tested directly on `_seed_domain_host`
    because its former exemplar (paramspider) is temporarily out of production
    (withdrawn from PHASES); the seeding logic it guards is unchanged."""
    from polymerhus.recon.control.scope import parse_scope

    assert pipeline._seed_domain_host(parse_scope("app.t.com")) == [{"name": "app.t.com"}]


def test_seed_domain_host_wildcard_mode_is_single_apex_host():
    """D14/D19: in wildcard mode the harvest runs ONCE against the registrable
    apex - still exactly one pod, never one per discovered subdomain. Direct test
    (see the exact-mode case re: paramspider being out of production)."""
    from polymerhus.recon.control.scope import parse_scope

    assert pipeline._seed_domain_host(parse_scope("*.t.com")) == [{"name": "t.com"}]


def test_wildcard_mode_runs_discovery_and_probes_apex():
    """D11+D14: wildcard keeps discovery AND injects the apex into the probe
    input so the apex's own web origin is enriched, not left a stub."""
    call_order, seen_inputs = _run_and_capture({"target_domain": "*.t.com"})

    assert "subfinder" in call_order and "dnsx" in call_order
    # httpx sees the apex (prepended) ahead of discovered subdomains.
    assert seen_inputs["httpx"][0] == {"name": "t.com"}
    assert {"name": "discovered.t.com"} in seen_inputs["httpx"]


def test_seed_assets_exact_mode_uses_seed_host_wildcard_uses_apex():
    """D14 Q2: the phase-0 Domain root is the exact host in exact mode (so
    ungated gau/paramspider stay in-scope) and the registrable apex in
    wildcard mode (so subfinder/amass enumerate the zone)."""
    # Exact subdomain: seed the host itself, not the registrable parent.
    assert pipeline.seed_assets({"target_domain": "app.example.com"}) == [
        {"name": "app.example.com"}
    ]
    # Exact apex: host == apex anyway.
    assert pipeline.seed_assets({"target_domain": "example.com"}) == [
        {"name": "example.com"}
    ]
    # Wildcard: the registrable apex (never the literal '*.example.com').
    assert pipeline.seed_assets({"target_domain": "*.example.com"}) == [
        {"name": "example.com"}
    ]


def test_exact_mode_logs_discovery_suppression(caplog):
    """D14 Q1: an exact-scope run records why it is small at run start."""
    import logging

    with caplog.at_level(logging.INFO, logger="polymerhus.recon.control.pipeline"):
        _run_and_capture({"target_domain": "app.t.com"})

    suppression_logs = [
        r.getMessage() for r in caplog.records if "scope=exact" in r.getMessage()
    ]
    assert suppression_logs, "expected an exact-scope suppression log line"
    msg = suppression_logs[0]
    assert "discovery suppressed" in msg
    assert "app.t.com" in msg
    for job in ("subfinder", "amass", "puredns", "dnsx"):
        assert job in msg


def test_job_stats_include_per_pod_commands(monkeypatch):
    import asyncio
    from polymerhus.recon.control import pipeline
    from polymerhus.recon.domain.types import PodExport

    captured = {}

    class FakeRegistry:
        def create_run(self, *a, **k): pass
        def set_run_status(self, *a, **k): pass
        def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
            if status not in ("in_progress",):
                captured[job] = stats

    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        return [
            PodExport(input_asset=input_assets[0], verdict="success",
                      stats={"command": "subfinder -d example.com -all -json -silent"}),
        ]

    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda run_id: None)

    asyncio.run(pipeline.run_pipeline(
        "p1", run_id="r1", job_subset=["subfinder"],
        run_job=fake_run_job,
        load_settings=lambda pid: {"target_domain": "*.example.com"},
        registry=FakeRegistry(),
        read_assets=lambda *a, **k: [{"name": "example.com"}],
    ))

    assert captured["subfinder"]["commands"] == ["subfinder -d example.com -all -json -silent"]


def test_capture_job_stats_folds_every_pod_fragment():
    """#196: the pod's capture outcome (`sent`/`refs`/`warning`) must survive the
    aggregation into `recon_jobs.stats` - it was silently dropped, so a recon run
    whose traffic was never recorded still read as a fully successful run.

    The fold is additive and can never launder a partial capture into a complete
    one: refs add, `sent` is true when at least ONE pod asked for capture, and no
    pod's warning is dropped in favour of another pod's clean result."""
    from polymerhus.recon.domain.types import PodExport as _PodExport

    def pod(capture=None, **extra):
        stats = dict(extra)
        if capture is not None:
            stats["capture"] = capture
        return _PodExport(input_asset={}, verdict="success", stats=stats)

    merged = pipeline.capture_job_stats([
        pod({"sent": True, "refs": 2, "warning": None}),
        pod({"sent": True, "refs": 3, "warning": None}),
    ])
    assert merged == {"sent": True, "refs": 5, "warning": None}

    # "asked and got nothing" is NOT the same fact as "never asked".
    assert pipeline.capture_job_stats([
        pod({"sent": False, "refs": 0, "warning": None}),
    ]) == {"sent": False, "refs": 0, "warning": None}

    assert pipeline.capture_job_stats([
        pod({"sent": False, "refs": 0, "warning": None}),
        pod({"sent": True, "refs": 1, "warning": None}),
    ])["sent"] is True

    # A pool-exhausted pod and a pod whose ref lookup failed: no pod's warning is
    # dropped, so the operator sees every partial-capture reason the job produced.
    merged_warning = pipeline.capture_job_stats([
        pod({"sent": True, "refs": 1, "warning": "capture unavailable: pool exhausted"}),
        pod({"sent": True, "refs": 1, "warning": "capture lookup failed: timeout"}),
    ])["warning"]
    assert "pool exhausted" in merged_warning and "timeout" in merged_warning, merged_warning

    # Additive: a job whose pods carry no capture fragment at all (an older pod,
    # or a job that never reaches the terminal) gains no capture claim.
    assert pipeline.capture_job_stats([pod(command="httpx -u x")]) == {}
    assert pipeline.capture_job_stats([]) == {}


def test_job_stats_surface_pod_capture_coverage(monkeypatch):
    """The persisted per-job stats carry what the pod reported about #196
    capture, for BOTH outcomes: a captured job and a pod that asked and got
    nothing."""
    captured: dict = {}
    # The heartbeat driver is a background thread; the unit tier stubs it out
    # (same as test_job_stats_include_per_pod_commands) so the assertions are
    # about stats, not about the scheduler.
    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda run_id: None)

    class CaptureRegistry(FakeRegistry):
        def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
            super().upsert_job(run_id, phase, job, status, stats=stats, error=error)
            if status not in ("in_progress",):
                captured.setdefault(job, stats)

    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        capture = (
            {"sent": True, "refs": 2, "warning": None}
            if job.tool == "subfinder"
            else {"sent": False, "refs": 0, "warning": None}
        )
        return [
            PodExport(input_asset=input_assets[0], verdict="success",
                      stats={"command": job.command_template, "capture": capture}),
        ]

    asyncio.run(pipeline.run_pipeline(
        "p1", run_id="r1", job_subset=["subfinder", "dnsx"],
        run_job=fake_run_job,
        load_settings=lambda pid: {"target_domain": "*.example.com"},
        registry=CaptureRegistry(),
        read_assets=lambda *a, **k: [{"name": "example.com"}],
    ))

    assert captured["subfinder"]["capture"] == {"sent": True, "refs": 2, "warning": None}
    assert captured["dnsx"]["capture"] == {"sent": False, "refs": 0, "warning": None}


def test_no_mid_run_steering_inputs_pass_unfiltered_and_no_steering_key(monkeypatch):
    """#243 (T4): the mid-run steering machinery is removed entirely - no
    per-phase routing turn, no signal refresh, no per-job steering input.
    Inputs pass unfiltered and no `steering` key rides any job's extra."""
    import asyncio
    from polymerhus.recon.control import pipeline

    X = "https://ib.example.com"
    Y = "https://app.example.com"

    def fake_read_assets(node_type, project_id, where=None, *, driver=None):
        if node_type == "Subdomain":
            return [{"name": "app.example.com"}]
        if node_type == "BaseURL":
            return [{"url": X}, {"url": Y}]
        return []

    captured_inputs = {}
    captured_extras = {}

    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        captured_inputs[job.tool] = [a.get("url") or a.get("name") for a in input_assets]
        captured_extras[job.tool] = dict(extra)
        return []

    class FakeRegistry:
        def create_run(self, *a, **k): pass
        def set_run_status(self, *a, **k): pass
        def upsert_job(self, *a, **k): pass

    class _Gateway:
        async def run_gateway(self, **kw):
            from polymerhus.recon.control.authn_loop import GatewayVerdict
            return GatewayVerdict(outcome="authenticated", account="alice",
                                  branch="request", rationale="t")

        async def stop(self): pass

    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda run_id: None)

    asyncio.run(pipeline.run_pipeline(
        "p1", run_id="r1",
        job_subset=["subfinder", "httpx", "katana", "steel_crawl"],
        run_job=fake_run_job,
        load_settings=lambda pid: {"target_domain": "*.example.com"},
        registry=FakeRegistry(),
        read_assets=fake_read_assets,
        orchestrator_factory=lambda run_id: _Gateway(),
    ))

    assert set(captured_inputs["katana"]) == {X, Y}  # inputs pass unfiltered
    for tool, extra in captured_extras.items():
        assert "steering" not in extra, f"{tool} carries a steering key"  # T4 removed
    assert "read_steering_signals" not in dir(pipeline)  # the reader is gone too


def test_pipeline_default_seam_is_the_gateway_actor_and_reaps_it(monkeypatch, tmp_path):
    """#223 T3 (#242): with no `orchestrator_factory` injected, the pipeline's
    production default is the recon-orchestrator GATEWAY actor - constructed
    once for the run through the module default factory, its single turn
    resolving before any phase, STOPPED on the run's exit path - and the
    verdict's account identifier rides the `use_auth` jobs' state."""
    import asyncio
    from langgraph.checkpoint.memory import InMemorySaver

    from polymerhus.recon.control import pipeline
    from polymerhus.recon.control.orchestrator_agent import ReconOrchestratorActor

    def fake_read_assets(node_type, project_id, where=None, *, driver=None):
        if node_type == "Subdomain":
            return [{"name": "app.example.com"}]
        return []

    captured_extras = {}

    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        captured_extras[job.tool] = dict(extra)
        return []

    class FakeRegistry:
        def create_run(self, *a, **k): pass
        def set_run_status(self, *a, **k): pass
        def upsert_job(self, *a, **k): pass

    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from polymerhus.app.auth.store import AuthStore
    from polymerhus.app.llm.skills import SkillStore

    class _ToolFake(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{"name": "GatewayVerdict",
                             "args": {"outcome": "authenticated", "account": "alice",
                                      "branch": "request", "rationale": "live"},
                             "id": "c1", "type": "tool_call"}],
            ))])

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    store = AuthStore(tmp_path)
    store.replace_operator_state(
        "p1", overview={"login_endpoint": "https://x/login"},
        accounts={"alice": {"credentials": {"username": "u", "password": "p",
                                            "login_url": "https://x/login"}}})

    spawned = []
    stopped = []
    real_default = pipeline._default_orchestrator_factory

    class _SpyActor(ReconOrchestratorActor):
        async def stop(self):
            stopped.append(self.thread_id)
            await super().stop()

    def _recording_default(run_id):
        spawned.append(run_id)
        return _SpyActor(
            run_id, project_id="p1", checkpointer=InMemorySaver(),
            model_factory=lambda role_id: _ToolFake(), observe=False,
            compaction=False, auth_store=store,
            skill_store=SkillStore(tmp_path), kali_tools=[],
        )

    monkeypatch.setattr(pipeline, "_default_orchestrator_factory", _recording_default)
    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda run_id: None)
    assert real_default("probe") is not None  # the production default builds

    asyncio.run(pipeline.run_pipeline(
        "p1", run_id="r1",
        job_subset=["subfinder", "httpx"],
        run_job=fake_run_job,
        load_settings=lambda pid: {"target_domain": "*.example.com"},
        registry=FakeRegistry(),
        read_assets=fake_read_assets,
    ))

    assert spawned == ["r1"]                    # ONE actor per run (production default)
    assert stopped == ["r1:job_orchestrator"]   # actor reaped on the run's exit path
    assert captured_extras["httpx"].get("auth_account") == "alice"  # verdict bound
    assert "auth_account" not in captured_extras["subfinder"]

def test_pipeline_terminal_runs_the_shared_run_scoped_flush(monkeypatch):
    """#211 C8/P7c: the pipeline terminal archives THIS run's threads through the
    SHARED run-scoped seam - exactly one `flush_module_index("recon", run_id)`
    call per terminal, never a second ad-hoc path."""
    from polymerhus.app.llm.checkpoints import FlushResult
    import polymerhus.app.llm.checkpoints as checkpoints

    calls = []
    monkeypatch.setattr(
        checkpoints, "flush_module_index",
        lambda module, run_id=None: (
            calls.append((module, run_id)),
            FlushResult(committed=0, archived=0, dropped=0, dropped_thread_ids=[]),
        )[1],
    )

    async def run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success")]

    asyncio.run(pipeline.run_pipeline(
        "proj1", run_id="run1", job_subset=["subfinder"],
        run_job=run_job,
        load_settings=make_load_settings({"target_domain": "*.t.com"}),
        registry=FakeRegistry(),
        read_assets=make_read_assets(),
    ))

    assert calls == [("recon", "run1")]
