# tests/recon/test_pipeline.py
"""Pipeline orchestrator: phase barrier, best-effort status derivation, and
the auth channel.

Fully mocked - `run_job`, `load_settings`, `registry`, and `read_assets` are
all injected fakes. No live Neo4j/Postgres/pod graph involved.
"""
import asyncio

from agent.recon import pipeline
from agent.recon.types import PodExport


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

    def read_assets(node_type, project_id):
        calls.append((node_type, project_id))
        return [{"name": default_name}]

    read_assets.calls = calls
    return read_assets


def test_phases_run_in_order_behind_a_barrier():
    """A phase-1 job's run_job must not be called until every phase-0 job's
    run_job has returned. Enforced by holding the sole phase-0 job open on
    an asyncio.Event the test controls."""
    call_order = []
    phase0_gate = asyncio.Event()

    async def run_job(job, input_assets, *, run_id, phase, extra):
        call_order.append((phase, job.tool))
        if phase == 0:
            await phase0_gate.wait()
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "t.com"}

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
        await asyncio.sleep(0.05)
        # Phase 1 (dnsx) must not have started while phase 0 is still gated.
        assert call_order == [(0, "subfinder")]

        phase0_gate.set()
        await task

    asyncio.run(scenario())

    assert call_order == [(0, "subfinder"), (1, "dnsx")]
    assert registry.set_run_status_calls[-1] == ("run1", "complete", None)


def test_job_with_all_pods_failed_is_degraded_and_run_completes():
    async def run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="failed", error="boom")]

    registry = FakeRegistry()
    settings = {"target_domain": "t.com"}

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


def test_auth_context_only_passed_to_use_auth_jobs():
    seen_extra = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        seen_extra[job.tool] = extra
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "t.com", "auth_context": {"cookies": []}}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=make_read_assets(),
        )
    )

    assert seen_extra["subfinder"] == {"project_id": "proj1"}
    assert seen_extra["httpx"] == {"project_id": "proj1", "auth_context": {"cookies": []}}
    assert seen_extra["katana"] == {"project_id": "proj1", "auth_context": {"cookies": []}}
    assert seen_extra["kiterunner"] == {"project_id": "proj1"}


def test_auth_context_absent_when_settings_have_none():
    seen_extra = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        seen_extra[job.tool] = extra
        return [PodExport(input_asset={}, verdict="success")]

    registry = FakeRegistry()
    settings = {"target_domain": "t.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "dnsx", "naabu", "httpx"],
            run_job=run_job,
            load_settings=make_load_settings(settings),
            registry=registry,
            read_assets=make_read_assets(),
        )
    )

    assert seen_extra["httpx"] == {"project_id": "proj1"}


def test_run_job_exception_marks_job_degraded_and_pipeline_still_completes():
    async def run_job(job, input_assets, *, run_id, phase, extra):
        raise RuntimeError("boom")

    registry = FakeRegistry()
    settings = {"target_domain": "t.com"}

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
    settings = {"target_domain": "t.com"}

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
    settings = {"target_domain": "t.com"}

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
    settings = {"target_domain": "t.com"}
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
    assert seen_inputs["dnsx"] == [{"name": "from-neo4j"}]
    assert ("Subdomain", "proj1") in read_assets.calls


def test_job_stats_records_consumed_and_produced_lineage():
    """D12: recon_jobs.stats must carry per-job data lineage - consumed
    (input-asset count) and produced (sum of pod assets_merged /
    observations_merged) - alongside the existing pod counts."""
    async def run_job(job, input_assets, *, run_id, phase, extra):
        # Two pods, producing 3+2 assets and 1+4 observations merged.
        return [
            PodExport(input_asset={}, verdict="success",
                      assets_merged=3, observations_merged=1),
            PodExport(input_asset={}, verdict="success",
                      assets_merged=2, observations_merged=4),
        ]

    registry = FakeRegistry()
    settings = {"target_domain": "t.com"}
    # read_assets returns 2 input assets for phase-1 dnsx (consumed == 2).
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

    # Phase-0 subfinder: consumed == 1 (the single seed asset).
    subfinder = [c for c in registry.upsert_job_calls
                 if c["job"] == "subfinder" and c["stats"] is not None][-1]
    assert subfinder["stats"]["consumed"] == 1
    assert subfinder["stats"]["produced_assets"] == 5
    assert subfinder["stats"]["produced_observations"] == 5

    # Phase-1 dnsx: consumed == 2 (read_assets returned two assets).
    dnsx = [c for c in registry.upsert_job_calls
            if c["job"] == "dnsx" and c["stats"] is not None][-1]
    assert dnsx["stats"]["consumed"] == 2
    assert dnsx["stats"]["produced_assets"] == 5
    assert dnsx["stats"]["produced_observations"] == 5
    # Existing pod counts still present (not regressed).
    assert dnsx["stats"]["pods"] == 2
