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


def _launch_pipeline(project_id: str, run_id: str, jobs: list[str] | None) -> None:
    """Schedule `run_pipeline` as a fire-and-forget background task.

    The pipeline itself is best-effort for job/pod failures (design §10.6),
    but a launch/setup error (e.g. the task raising before it even reaches
    the first `await`) must still be logged rather than vanish silently.
    """

    async def _run() -> None:
        try:
            await run_pipeline(project_id, run_id=run_id, job_subset=jobs)
        except Exception:  # noqa: BLE001 - best-effort launch, must not crash the loop
            logger.exception("recon pipeline run %s (project %s) failed", run_id, project_id)

    asyncio.create_task(_run())


@router.post("/projects/{project_id}/recon")
async def launch_recon(project_id: str, body: ReconLaunch) -> dict:
    try:
        repository.validate_launch(project_id, body.jobs)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = repository.open_run(project_id)
    _launch_pipeline(project_id, run_id, body.jobs)
    return {"run_id": run_id}


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
