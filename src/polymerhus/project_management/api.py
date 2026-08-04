"""REST API for the operator-intent surface (design §10.5): project/settings
CRUD, non-blocking recon-run launch, and run-status polling.

This module is a thin HTTP adapter: every handler delegates to the
`repository` use-case layer and maps its domain errors onto status codes
(ProjectNotFound/RunNotFound -> 404, ValueError -> 400). The one piece of
orchestration that stays here is `_launch_pipeline` - the fire-and-forget
`asyncio.create_task` seam that schedules `run_pipeline` and returns
immediately. It is a module-level seam so tests can monkeypatch it with a
recorder instead of exercising the real pipeline/DB/Kali/Neo4j stack.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from polymerhus.project_management import repository
from polymerhus.project_management.repository import (
    BootstrapBlocked,
    ProjectNotFound,
    RunNotFound,
)
from polymerhus.recon.control.pipeline import run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str


class SettingsUpdate(BaseModel):
    recon: dict = {}


class ReconLaunch(BaseModel):
    jobs: list[str] | None = None
    settings: dict | None = None
    # #75: the recon endpoint is the COMBINED dispatch by default (recon + an
    # independent analysis consumer for the same run). Set false for the recon-ONLY
    # dispatch: recon pushes chunks to the run's FIFO and a later `POST /analysis`
    # drains them.
    with_analysis: bool = True


class AnalysisLaunch(BaseModel):
    """#75: start the analysis-only dispatch - a consumer that drains an existing
    run's FIFO. `run_id` is the recon run whose queue to drain."""

    run_id: str


class BootstrapLaunch(BaseModel):
    """Ingest the operator's knowledge base and bootstrap. `operator_kb` is optional:
    supply it to ingest-and-bootstrap in one call (the frontend's flow), or omit it to
    bootstrap from the KB already stored in the project's settings."""

    operator_kb: str | None = None


@router.post("/projects")
def create_project(body: ProjectCreate) -> dict:
    return {"project_id": repository.create_project(body.name)}


@router.get("/projects")
def list_projects() -> dict:
    return {"projects": repository.list_projects()}


@router.get("/projects/{project_id}/graph")
def project_graph(project_id: str) -> dict:
    try:
        return repository.project_graph(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")


@router.get("/runs")
def list_runs(status: str | None = None) -> dict:
    if status != "running":
        raise HTTPException(status_code=400, detail="only status=running is supported")
    return repository.running_runs()


@router.put("/projects/{project_id}/settings")
def update_settings(project_id: str, body: SettingsUpdate) -> dict:
    try:
        repository.save_project_settings(project_id, body.recon)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


# Strong references to in-flight pipeline tasks.
#
# The event loop keeps only a WEAK reference to a task, so the Python docs are
# explicit that a caller must retain one for the task's lifetime or it may be
# garbage-collected mid-flight. Every other `create_task` in this codebase already
# does (`app.state.reaper_task`, `QueuedAnalysisFeed._task`, the pipeline's local
# `hb`); this was the one that did not, and it is the OUTERMOST task, so losing it
# would take a whole run with it.
#
# HONEST SCOPE. This is defensive correctness, NOT the diagnosis of any observed
# failure. It was written while investigating run 6b9358a0, and it does not explain
# that run: the assertion that reproduced the theory passed without this fix,
# because a task suspended on an await is still referenced by the handle that will
# resume it, so the collectable window is far narrower than it first appears. That
# run died because its container was recreated underneath it. The reference is kept
# anyway because "narrow" is not "closed" and the cost is one set.
_IN_FLIGHT: set[asyncio.Task] = set()
# #75: recon tasks keyed by run_id so a recon-stop dispatch can cancel exactly one.
_RECON_TASKS: dict[str, asyncio.Task] = {}


def _launch_pipeline(project_id: str, run_id: str, jobs: list[str] | None,
                     *, with_analysis: bool = True) -> None:
    """Schedule `run_pipeline` as a fire-and-forget background task.

    The pipeline itself is best-effort for job/pod failures (design §10.6),
    but a launch/setup error (e.g. the task raising before it even reaches
    the first `await`) must still be logged rather than vanish silently.
    """

    async def _run() -> None:
        try:
            await run_pipeline(project_id, run_id=run_id, job_subset=jobs,
                               with_analysis=with_analysis)
        except Exception:  # noqa: BLE001 - best-effort launch, must not crash the loop
            logger.exception("recon pipeline run %s (project %s) failed", run_id, project_id)

    task = asyncio.create_task(_run(), name=f"recon-pipeline-{run_id}")
    # Hold the reference until the task finishes, then drop it so the set cannot
    # grow without bound. `discard` (not `remove`) because the callback may fire
    # after a shutdown that already cleared the set.
    _IN_FLIGHT.add(task)
    _RECON_TASKS[run_id] = task
    task.add_done_callback(_IN_FLIGHT.discard)
    task.add_done_callback(
        lambda t: _RECON_TASKS.pop(run_id, None) if _RECON_TASKS.get(run_id) is t else None)


@router.post("/projects/{project_id}/recon")
async def launch_recon(project_id: str, body: ReconLaunch) -> dict:
    """The dispatcher's recon entrypoint (#75). COMBINED by default
    (`with_analysis=True`): starts recon AND the independent analysis consumer for
    the run. `with_analysis=false` is the recon-ONLY dispatch."""
    try:
        repository.validate_launch(project_id, body.jobs)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = repository.open_run(project_id)
    _launch_pipeline(project_id, run_id, body.jobs, with_analysis=body.with_analysis)
    return {"run_id": run_id}


@router.post("/projects/{project_id}/recon/{run_id}/stop")
async def stop_recon(project_id: str, run_id: str) -> dict:
    """Stop recon ONLY (#75 D6): cancel the recon task. Its `finally` enqueues the
    terminal marker so the independent analysis consumer can still drain what was
    already pushed; analysis is never touched here. (The instant per-job kill +
    output suppression is #76.)"""
    task = _RECON_TASKS.get(run_id)
    if task is None or task.done():
        raise HTTPException(status_code=404, detail="no running recon for that run_id")
    task.cancel()
    return {"run_id": run_id, "stopping": True}


@router.post("/projects/{project_id}/analysis")
async def launch_analysis(project_id: str, body: AnalysisLaunch) -> dict:
    """The dispatcher's analysis-ONLY entrypoint (#75): start a consumer that drains
    an existing run's FIFO. Also the RESUME path after a graceful stop (D7)."""
    from polymerhus.analysis.lifecycle import start_analysis

    analysis_run_id = start_analysis(project_id, body.run_id)
    if analysis_run_id is None:
        raise HTTPException(status_code=409, detail="analysis already running for that run_id")
    return {"run_id": body.run_id, "analysis_run_id": analysis_run_id}


@router.post("/projects/{project_id}/analysis/{run_id}/stop")
async def stop_analysis_run(project_id: str, run_id: str) -> dict:
    """Graceful stop of the analysis consumer (#75 D7): finish the in-flight chunk,
    consume no further, preserve the queue for a resume."""
    from polymerhus.analysis.lifecycle import stop_analysis

    await stop_analysis(run_id)
    return {"run_id": run_id, "stopped": True}


@router.get("/projects/{project_id}/analysis/{run_id}")
async def get_analysis_status(project_id: str, run_id: str) -> dict:
    """The analysis run's own status row (#75), independent of the recon run."""
    from polymerhus.app.clients import pg

    row = await asyncio.to_thread(pg.get_analysis_run, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no analysis run for that run_id")
    return row


@router.post("/projects/{project_id}/bootstrap")
async def bootstrap_project(project_id: str, body: BootstrapLaunch) -> dict:
    """Ingest the operator KB and project it into the L1 Service skeleton.

    SYNCHRONOUS, unlike the recon launch: a bootstrap is two LLM calls whose RESULT
    (the skeleton counts, or the fail-closed block) is what the caller needs, and it
    has no per-job progress worth polling - so there is nothing a run row and a
    status endpoint would add over simply returning the outcome. The blocking work is
    offloaded to a worker thread so it never stalls the event loop.

    A fail-closed block is a 503, NOT a 200 with zero counts: the whole point of the
    signal is that the caller must not proceed to the analysis, and a success status
    would invite exactly that."""
    try:
        return await asyncio.to_thread(
            repository.bootstrap_project, project_id, body.operator_kb
        )
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BootstrapBlocked as exc:
        logger.warning("bootstrap blocked for project %s: %s", project_id, exc.reason)
        raise HTTPException(
            status_code=503,
            detail=f"bootstrap blocked, analysis must not proceed: {exc.reason}",
        ) from exc


@router.get("/projects/{project_id}/recon/{run_id}")
def get_recon_status(project_id: str, run_id: str) -> dict:
    try:
        return repository.recon_status(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail="unknown run")
