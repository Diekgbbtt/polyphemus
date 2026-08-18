"""Interface agreement B (L1D-26): the backward-recon seam.

Lets the analyser (and, later, system-anatomy skills) request one targeted recon
job outside the linear phase plan and receive the result routed back **in the
same process** (synchronous MVP), rather than through the generic
recon->analyser stream. Unifies with forward-decision D2's
`request_targeted_recon` shape: it builds a synthetic single JobSpec around the
request, reuses the existing pod machinery via `run_job` (no new subgraph), and
persists the targeted job into `recon_jobs` carrying `correlation_id` (the result
is routed back by it), `requester_id` (...to this agent instance), and `origin`.

MVP scope (per the bridge): the typed contract + synchronous execution. Async
dispatch and block-and-reuse are `NM-2`, deliberately NOT built here. Fail-open
throughout (mirrors the pipeline's per-job degrade, pipeline.py:341-359): a
targeted job that cannot run degrades to an empty result with an error status and
never raises into the caller.
"""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain.types import JobSpec, PodExport

logger = logging.getLogger(__name__)

# Out-of-band phase index for a targeted job (mirrors pg.TARGETED_PHASE), so it
# runs and is registered outside the linear phase barrier.
from polymerhus.app.clients.pg import TARGETED_PHASE


class ReconScope(BaseModel):
    """What a targeted request points at. `targets` are concrete L0 handles the
    probe runs against (URLs/hosts, or already-shaped asset dicts); `unit_id`
    names the L1 **testable unit** the need arose from - a kind-qualified
    identity string `"<kind>:<key>"` (`"Service:orders"`, or a System's
    `"System:<kind>/<discriminator>"`); an unprefixed value is read as a Service
    slug for back-compat. It carries the testable-unit identity only, never a
    fault-class (hunt back-edges join the fault in the hunt store via
    `correlation_id`, keeping this seam fault-agnostic). `auth_context` (optional)
    carries the per-role credentials a skill probe needs (interface-B
    `auth_context?`); `note` (optional) records WHY the probe was raised (e.g. an
    anatomy skill's fingerprint-only rationale + the spine slot(s) it must settle,
    or a hunt's yellow `insufficient-evidence` gap) so the routed result knows
    what to refine."""

    unit_id: str | None = None
    targets: list[str | dict] = Field(default_factory=list)
    auth_context: dict | None = None
    note: str | None = None


class AnalyserReconRequest(BaseModel):
    """The typed backward-recon contract (spec §7.5). `job` is the tool to run
    (a registered `JOBS` key for the MVP); `origin` says who raised the need and
    `skill_id` is set when an anatomy skill did; `correlation_id` routes the
    result back and `requester_id` names the awaiting agent instance."""

    job: str
    scope: ReconScope = Field(default_factory=ReconScope)
    origin: Literal["analyser", "anatomy_skill", "hunting"] = "analyser"
    skill_id: str | None = None
    correlation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    requester_id: str


class TargetedReconResult(BaseModel):
    """The result routed back to the requester in-process (sync MVP). Carries the
    correlation/requester ids (so an async promotion, NM-2, can route by them),
    the run status, the pod exports, and the merged-asset/observation counts the
    caller reasons about."""

    correlation_id: str
    requester_id: str
    origin: str
    status: Literal["success", "degraded", "skipped", "error"]
    pod_exports: list[PodExport] = Field(default_factory=list)
    assets_merged: int = 0
    observations_merged: int = 0
    error: str | None = None


def _build_input_assets(scope: ReconScope) -> list[dict]:
    """One input asset per target. A plain string target is the common
    request-tool shape (`{target}`/url); an already-shaped dict passes through so
    the caller can supply a concrete L0 asset slice."""
    assets: list[dict] = []
    for t in scope.targets:
        assets.append(dict(t) if isinstance(t, dict) else {"url": t, "target": t})
    return assets


def _build_extra(scope: ReconScope) -> dict:
    """The per-job `extra` the pod configurator reads (mirrors the pipeline's
    per-job extra). Carries auth_context when the request supplied one."""
    extra: dict = {}
    if scope.auth_context:
        extra["auth_context"] = scope.auth_context
    return extra


def _derive_status(pod_exports: list[PodExport]) -> Literal["success", "degraded", "skipped"]:
    """Mirror the pipeline's per-job status derivation (pipeline.py:361-370)."""
    total = len(pod_exports)
    if total == 0:
        return "skipped"
    if all(e.verdict == "failed" for e in pod_exports):
        return "degraded"
    return "success"


async def request_targeted_recon(
    request: AnalyserReconRequest,
    run_id: str,
    project_id: str,
    *,
    run_job=None,
    registry=None,
) -> TargetedReconResult:
    """Execute one targeted recon job for `request` outside the phase barrier and
    route its result back in-process. Reuses `run_job` (the existing pod
    machinery) and persists the job into `recon_jobs` with correlation/requester/
    origin. Fail-open: any failure degrades to an empty errored result, recorded
    and returned, never raised.

    `run_job` and `registry` are injected (defaulting to the real
    `job_agent.run_job` and the `pg` client) so this seam is unit/integration
    testable without a live kali/LLM, exactly like `run_pipeline`.
    """
    if run_job is None:
        from polymerhus.recon.control.job_agent import run_job as run_job  # noqa: PLC0414
    if registry is None:
        from polymerhus.app.clients import pg as registry

    cid, rid, origin = request.correlation_id, request.requester_id, request.origin

    def _record(status: str, *, stats: dict | None = None, error: str | None = None) -> None:
        try:
            registry.record_targeted_job(
                run_id, request.job, status,
                correlation_id=cid, requester_id=rid, origin=origin,
                stats=stats, error=error,
            )
        except Exception:  # registry write must never crash the caller either
            logger.warning("request_targeted_recon: registry write failed for cid=%s", cid, exc_info=True)

    job: JobSpec | None = JOBS.get(request.job)
    if job is None:
        # Unknown tool: no registered pod machinery to reuse -> degrade, never raise.
        msg = f"unknown targeted job {request.job!r}; known: {sorted(JOBS)}"
        logger.warning("request_targeted_recon: %s", msg)
        _record("skipped", error=msg)
        return TargetedReconResult(correlation_id=cid, requester_id=rid, origin=origin, status="error", error=msg)

    input_assets = _build_input_assets(request.scope)
    extra = _build_extra(request.scope)
    # The pod derives its write scope from extra["project_id"] (job_agent.py:213
    # `extra.get("project_id", run_id)`), exactly as the pipeline injects it
    # (pipeline.py:310). Without this the targeted job would curate L0 nodes under
    # the run_id instead of the project, orphaning them from the project graph.
    extra["project_id"] = project_id

    try:
        pod_exports: list[PodExport] = await run_job(
            job, input_assets, run_id=run_id, phase=TARGETED_PHASE, extra=extra
        )
    except Exception as exc:  # fail-open: mirror pipeline._run_one's degrade
        logger.warning("request_targeted_recon: run_job raised for cid=%s", cid, exc_info=True)
        _record("failed", error=str(exc))
        return TargetedReconResult(correlation_id=cid, requester_id=rid, origin=origin, status="error", error=str(exc))

    status = _derive_status(pod_exports)
    assets_merged = sum(e.assets_merged for e in pod_exports)
    observations_merged = sum(e.observations_merged for e in pod_exports)
    stats = {
        "pods": len(pod_exports),
        "assets_merged": assets_merged,
        "observations_merged": observations_merged,
        "skill_id": request.skill_id,
    }
    _record(status, stats=stats)
    return TargetedReconResult(
        correlation_id=cid, requester_id=rid, origin=origin, status=status,
        pod_exports=pod_exports, assets_merged=assets_merged,
        observations_merged=observations_merged,
    )
