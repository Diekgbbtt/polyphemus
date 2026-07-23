"""FR-RECONREQ unit tier — the AnalyserReconRequest contract + the
request_targeted_recon executor's pure control flow, with an injected fake
run_job/registry (no live kali/LLM/DB). Store-level assertions are the
integration tier (tests/integration/test_targeted_roundtrip.py).

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md §5).
"""
import asyncio

import pytest

from polymerhus.recon.control.targeted import (
    AnalyserReconRequest,
    ReconScope,
    TargetedReconResult,
    request_targeted_recon,
)
from polymerhus.recon.domain.types import PodExport


class _FakeRegistry:
    """Captures record_targeted_job calls in place of the pg client."""

    def __init__(self):
        self.calls = []

    def record_targeted_job(self, run_id, tool, status, *, correlation_id, requester_id, origin, stats=None, error=None):
        self.calls.append({
            "run_id": run_id, "tool": tool, "status": status,
            "correlation_id": correlation_id, "requester_id": requester_id,
            "origin": origin, "stats": stats, "error": error,
        })


def _run(coro):
    return asyncio.run(coro)


# --- contract: AnalyserReconRequest shape + defaults (L1D-26) ---

def test_contract_defaults_and_required_fields():
    req = AnalyserReconRequest(job="graphql-cop", requester_id="analyser-1")
    assert req.origin == "analyser"  # default
    assert req.skill_id is None
    assert isinstance(req.correlation_id, str) and req.correlation_id  # auto uuid
    # two requests get distinct correlation ids
    assert req.correlation_id != AnalyserReconRequest(job="x", requester_id="r").correlation_id


def test_contract_requester_id_is_required():
    with pytest.raises(Exception):  # pydantic ValidationError - requester_id missing
        AnalyserReconRequest(job="graphql-cop")


def test_contract_anatomy_skill_origin_carries_skill_id():
    req = AnalyserReconRequest(
        job="katana", requester_id="skill-run-1", origin="anatomy_skill",
        skill_id="webpage_profile",
        scope=ReconScope(service_id="sales-analysis", targets=["https://a/dash"]),
    )
    assert req.origin == "anatomy_skill" and req.skill_id == "webpage_profile"
    assert req.scope.service_id == "sales-analysis"


# --- AST-RECONREQ-01: runs exactly one job outside the barrier, returns result ---

def test_sync_roundtrip_runs_one_job_and_returns_observations():
    calls = {"n": 0, "phase": None}

    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        calls["n"] += 1
        calls["phase"] = phase
        calls["job_tool"] = job.tool
        calls["input_assets"] = input_assets
        calls["extra"] = extra
        return [PodExport(input_asset=input_assets[0], verdict="success", assets_merged=3, observations_merged=2)]

    reg = _FakeRegistry()
    req = AnalyserReconRequest(
        job="graphql-cop", requester_id="analyser-1", correlation_id="cid-1",
        scope=ReconScope(targets=["https://a/graphql"]),
    )
    result = _run(request_targeted_recon(req, "run-1", "proj-1", run_job=fake_run_job, registry=reg))

    assert calls["n"] == 1  # exactly one job
    assert calls["phase"] == -1  # outside the phase barrier (TARGETED_PHASE)
    assert calls["job_tool"] == "graphql-cop"
    # project_id must reach the pod via extra (job_agent derives write scope from
    # extra["project_id"]); without it the targeted job orphans its L0 nodes.
    assert calls["extra"]["project_id"] == "proj-1"
    assert isinstance(result, TargetedReconResult)
    assert result.status == "success"
    assert result.assets_merged == 3 and result.observations_merged == 2  # observations routed back in-process
    assert result.correlation_id == "cid-1" and result.requester_id == "analyser-1"


def test_registry_recorded_with_correlation_requester_origin():
    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success", assets_merged=1, observations_merged=0)]

    reg = _FakeRegistry()
    req = AnalyserReconRequest(job="katana", requester_id="req-9", origin="anatomy_skill",
                              skill_id="webpage_profile", correlation_id="corr-9")
    _run(request_targeted_recon(req, "run-2", "proj-1", run_job=fake_run_job, registry=reg))

    assert len(reg.calls) == 1
    c = reg.calls[0]
    assert c["status"] == "success"
    assert c["correlation_id"] == "corr-9"
    assert c["requester_id"] == "req-9"
    assert c["origin"] == "anatomy_skill"
    assert c["stats"]["skill_id"] == "webpage_profile"


# --- AST-RECONREQ-04: fail-open — a failure degrades, never raises ---

def test_run_job_exception_is_degraded_not_raised():
    async def boom_run_job(job, input_assets, *, run_id, phase, extra):
        raise RuntimeError("kali exec exploded")

    reg = _FakeRegistry()
    req = AnalyserReconRequest(job="graphql-cop", requester_id="r", correlation_id="cid-err")
    result = _run(request_targeted_recon(req, "run-3", "proj-1", run_job=boom_run_job, registry=reg))

    assert result.status == "error"  # degraded, not raised
    assert "kali exec exploded" in result.error
    assert result.pod_exports == []
    assert reg.calls[0]["status"] == "failed"
    assert "kali exec exploded" in reg.calls[0]["error"]


def test_unknown_tool_is_degraded_not_raised():
    async def unused_run_job(*a, **k):  # must never be called for an unknown tool
        raise AssertionError("run_job should not be invoked for an unknown tool")

    reg = _FakeRegistry()
    req = AnalyserReconRequest(job="not-a-real-tool", requester_id="r", correlation_id="cid-unk")
    result = _run(request_targeted_recon(req, "run-4", "proj-1", run_job=unused_run_job, registry=reg))

    assert result.status == "error"
    assert "unknown targeted job" in result.error
    assert reg.calls[0]["status"] == "skipped"


def test_registry_write_failure_does_not_crash_caller():
    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success")]

    class ExplodingRegistry:
        def record_targeted_job(self, *a, **k):
            raise RuntimeError("db down")

    req = AnalyserReconRequest(job="graphql-cop", requester_id="r", correlation_id="cid-x")
    # must still return a result (fail-open on the registry write too)
    result = _run(request_targeted_recon(req, "run-5", "proj-1", run_job=fake_run_job, registry=ExplodingRegistry()))
    assert result.status == "success"


def test_all_pods_failed_is_degraded():
    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="failed"), PodExport(input_asset={}, verdict="failed")]

    reg = _FakeRegistry()
    req = AnalyserReconRequest(job="graphql-cop", requester_id="r")
    result = _run(request_targeted_recon(req, "run-6", "proj-1", run_job=fake_run_job, registry=reg))
    assert result.status == "degraded"
    assert reg.calls[0]["status"] == "degraded"
