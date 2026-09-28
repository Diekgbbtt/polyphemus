"""The pipeline projects the SAME validated profile into the project bucket,
after Postgres and before any phase. Fully mocked (the FakeRegistry shape from
tests/recon/test_pipeline.py): no live Neo4j/Postgres/pod graph."""
import asyncio

import yaml

from polymerhus.app.rate_limit.store import RateLimitPostureStore
from polymerhus.recon.config import rate_limit_safety_budget
from polymerhus.recon.control import pipeline
from polymerhus.recon.domain.rate_limit import RateProfile
from polymerhus.recon.domain.types import PodExport


class FakeRegistry:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.set_run_status_calls = []
        self.upsert_job_calls = []
        self.run_stats = {}

    def create_run(self, run_id, project_id):
        self.events.append("create_run")

    def set_run_status(self, run_id, status, current_phase=None):
        self.set_run_status_calls.append((run_id, status, current_phase))
        self.events.append("set_run_status")

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        self.upsert_job_calls.append((phase, job, status))
        self.events.append("upsert_job")

    def set_run_stats(self, run_id, stats):
        self.events.append("set_run_stats")
        self.run_stats.update(stats)


def _profile(target_key: str = "acme.com") -> RateProfile:
    return RateProfile.conservative(
        target_key, [target_key], rate_limit_safety_budget(), "fixture",
    )


class _FakeOrchestrator:
    """A gateway that degrades (None); mapping is pipeline-owned."""

    async def run_gateway(self, *, project_id):
        return None


async def _run(registry, profile, **kwargs):
    async def map_rate_profile(
        project_id, run_id, target_key, url, headers, host_patterns
    ):
        registry.events.append("map")
        return profile

    return await pipeline.run_pipeline(
        "proj-1",
        run_id="run-1",
        job_subset=["httpx"],
        registry=registry,
        load_settings=lambda project_id: {"target_seed": "acme.com"},
        read_assets=lambda *args, **kw: [],
        run_job=lambda *args, **kw: [PodExport(input_asset={}, verdict="success")],
        orchestrator_factory=lambda run_id: _FakeOrchestrator(),
        map_rate_profile=map_rate_profile,
        **kwargs,
    )


def test_the_posture_file_matches_the_run_stats(tmp_path):
    events: list = []
    registry = FakeRegistry(events)
    profile = _profile()
    store = RateLimitPostureStore(root=tmp_path)

    def write_posture(project_id, prof, run_id):
        events.append("write_posture")
        return store.write(project_id, prof, run_id)

    asyncio.run(
        _run(
            registry, profile,
            write_posture=write_posture,
        )
    )

    stored = yaml.safe_load(
        (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert stored["profile"] == registry.run_stats["rate_limit"]
    assert events.index("set_run_stats") < events.index("write_posture")


def test_a_failed_posture_write_fails_the_run_before_any_phase(tmp_path):
    registry = FakeRegistry()

    def _boom(project_id, profile, run_id):
        raise OSError("disk full")

    asyncio.run(_run(registry, _profile(), write_posture=_boom))

    assert registry.set_run_status_calls[-1] == ("run-1", "failed", None)
    assert registry.upsert_job_calls == []
