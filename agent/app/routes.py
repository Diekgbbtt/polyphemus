# agent/app/routes.py
"""REST API for the recon pipeline (design §10.5): project/settings CRUD,
recon-run launch (non-blocking), and run status polling from the Postgres
registry.

The `POST /projects/{id}/recon` handler never awaits `run_pipeline` directly
- it schedules `_launch_pipeline` (an `asyncio.create_task` wrapper) and
returns `{run_id}` immediately. `_launch_pipeline` is a module-level seam so
tests can monkeypatch it with a recorder instead of exercising the real
pipeline/DB/Kali/Neo4j stack.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.app.clients import pg
from agent.recon.jobs import JOBS, validate_job_subset
from agent.recon.pipeline import run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str


class SettingsUpdate(BaseModel):
    recon: dict = {}


class ReconLaunch(BaseModel):
    jobs: list[str] | None = None
    settings: dict | None = None


def _validate_auth_context(auth_context: object) -> None:
    """Raise ValueError on any shape violation of the AuthContext contract:
    a dict with a `cookies` list (each `{name, value}`) and an optional
    string `scope`."""
    if not isinstance(auth_context, dict):
        raise ValueError("auth_context must be an object")

    cookies = auth_context.get("cookies")
    if not isinstance(cookies, list):
        raise ValueError("auth_context.cookies must be a list")
    for cookie in cookies:
        if not isinstance(cookie, dict) or "name" not in cookie or "value" not in cookie:
            raise ValueError("each auth_context.cookies entry must be {name, value}")
        if not isinstance(cookie["name"], str) or not isinstance(cookie["value"], str):
            raise ValueError("auth_context.cookies entries must have string name/value")

    scope = auth_context.get("scope")
    if scope is not None and not isinstance(scope, str):
        raise ValueError("auth_context.scope must be a string")


@router.post("/projects")
def create_project(body: ProjectCreate) -> dict:
    project_id = str(uuid.uuid4())
    pg.create_project(project_id, body.name)
    return {"project_id": project_id}


@router.put("/projects/{project_id}/settings")
def update_settings(project_id: str, body: SettingsUpdate) -> dict:
    if not pg.project_exists(project_id):
        raise HTTPException(status_code=404, detail="unknown project")

    auth_context = body.recon.get("auth_context")
    if auth_context is not None:
        try:
            _validate_auth_context(auth_context)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    pg.save_settings(project_id, body.recon)
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
    if not pg.project_exists(project_id):
        raise HTTPException(status_code=404, detail="unknown project")

    jobs = body.jobs
    if jobs is not None:
        unknown = [j for j in jobs if j not in JOBS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown job(s): {unknown}")
        try:
            validate_job_subset(jobs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = str(uuid.uuid4())
    # Create the run row synchronously so a poll right after this returns
    # sees it (no 404 race). `run_pipeline` also calls create_run, but it is
    # idempotent (ON CONFLICT DO NOTHING), so the pipeline's call is a no-op.
    pg.create_run(run_id, project_id)
    _launch_pipeline(project_id, run_id, jobs)
    return {"run_id": run_id}


@router.get("/projects/{project_id}/recon/{run_id}")
def get_recon_status(project_id: str, run_id: str) -> dict:
    run = pg.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run")

    jobs = pg.get_run_jobs(run_id)
    return {
        "status": run["status"],
        "current_phase": run["current_phase"],
        "per_job": jobs,
    }
