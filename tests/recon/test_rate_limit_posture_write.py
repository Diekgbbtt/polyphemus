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
    def __init__(self):
        self.set_run_status_calls = []
        self.upsert_job_calls = []
        self.run_stats = {}

    def create_run(self, run_id, project_id):
        pass

    def set_run_status(self, run_id, status, current_phase=None):
        self.set_run_status_calls.append((run_id, status, current_phase))

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        self.upsert_job_calls.append((phase, job, status))

    def set_run_stats(self, run_id, stats):
        self.run_stats.update(stats)


def _profile(target_key: str = "acme.com") -> RateProfile:
    return RateProfile.conservative(
        target_key, [target_key], rate_limit_safety_budget(), "fixture",
    )


class _FakeOrchestrator:
    """A gateway that degrades (None) and a rate turn that returns the fixture
    profile - no LLM, no Kali, deterministic."""

    def __init__(self, profile: RateProfile):
        self._profile = profile

    async def run_gateway(self, *, project_id):
        return None

    async def run_rate_limit(self, **kwargs):
        return self._profile


async def _run(registry, profile, **kwargs):
    return await pipeline.run_pipeline(
        "proj-1",
        run_id="run-1",
        job_subset=["httpx"],
        registry=registry,
        load_settings=lambda project_id: {"target_seed": "acme.com"},
        read_assets=lambda *args, **kw: [],
        run_job=lambda *args, **kw: [PodExport(input_asset={}, verdict="success")],
        orchestrator_factory=lambda run_id: _FakeOrchestrator(profile),
        **kwargs,
    )


def test_the_posture_file_matches_the_run_stats(tmp_path):
    registry = FakeRegistry()
    profile = _profile()
    store = RateLimitPostureStore(root=tmp_path)

    asyncio.run(
        _run(
            registry, profile,
            write_posture=lambda pid, prof, rid: store.write(pid, prof, rid),
        )
    )

    stored = yaml.safe_load(
        (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert stored["profile"] == registry.run_stats["rate_limit"]


def test_a_failed_posture_write_fails_the_run_before_any_phase(tmp_path):
    registry = FakeRegistry()

    def _boom(project_id, profile, run_id):
        raise OSError("disk full")

    asyncio.run(_run(registry, _profile(), write_posture=_boom))

    assert registry.set_run_status_calls[-1] == ("run-1", "failed", None)
    assert registry.upsert_job_calls == []
