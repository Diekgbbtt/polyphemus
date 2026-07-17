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
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.app.clients import pg
from agent.app.config import config
from agent.recon.graph_read import fetch_project_graph
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


# auth_context keys that are structural, NOT HTTP headers. Every other key is
# treated as an arbitrary request header (name -> string value). `roles` /
# `default_role` tag multiple credential sets (FR-AUTH); `realm` tags a set's
# origin (credential vs IdP). This mirrors the header serialiser's reserved set
# (pod._RESERVED_AUTH_KEYS); the selector's auth._STRUCTURAL_KEYS is deliberately
# narrower (it keeps `realm` in a selected role's set - see that module's note).
_RESERVED_AUTH_CONTEXT_KEYS = {"cookies", "scope", "credentials", "roles", "default_role", "realm"}
# RFC 7230 header field-names are tokens; we accept the realistic subset
# (letters, digits, hyphen) that covers every auth header (Authorization,
# X-Api-Key, ...) and excludes shell/CRLF-dangerous characters.
_HTTP_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")


def _validate_auth_context(auth_context: object) -> None:
    """Raise ValueError on any shape violation of the AuthContext contract:
    a dict with an OPTIONAL `cookies` list (each `{name, value}`), an optional
    string `scope`, and optional `credentials`.

    `cookies` (request-based crawling) and `credentials` (agentic login, D23-2)
    are INDEPENDENT items. A partial PUT may set either without the other, so
    an absent `cookies` key is valid; only a present-but-malformed one is an
    error. The registry merges partial PUTs recursively (see pg.save_settings)
    so setting one item never wipes the other."""
    if not isinstance(auth_context, dict):
        raise ValueError("auth_context must be an object")

    cookies = auth_context.get("cookies")
    if cookies is not None:
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

    # D23: optional autonomous-login credentials (username/password/login_url
    # required; domain + form selectors optional). Absent is valid.
    credentials = auth_context.get("credentials")
    if credentials is not None:
        if not isinstance(credentials, dict):
            raise ValueError("auth_context.credentials must be an object")
        for field in ("username", "password", "login_url"):
            if not isinstance(credentials.get(field), str) or not credentials[field]:
                raise ValueError(f"auth_context.credentials.{field} must be a non-empty string")
        for field in ("domain", "username_selector", "password_selector", "submit_selector"):
            if field in credentials and not isinstance(credentials[field], str):
                raise ValueError(f"auth_context.credentials.{field} must be a string")

    # Arbitrary HTTP headers: auth_context is header-agnostic, so every key that
    # is not a reserved structural key is an HTTP header name -> string value,
    # emitted verbatim on the request-based tools (Authorization, X-Api-Key,
    # ...). `cookies` stays the one source of the `Cookie` header, so a literal
    # `Cookie` header is refused to avoid two sources of truth.
    for name, value in auth_context.items():
        if name in _RESERVED_AUTH_CONTEXT_KEYS:
            continue
        if name.lower() == "cookie":
            raise ValueError(
                "auth_context: set cookies via the `cookies` list, not a `Cookie` header"
            )
        if not _HTTP_HEADER_NAME_RE.match(name):
            raise ValueError(
                f"auth_context header name {name!r} is not a valid HTTP header token"
            )
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"auth_context header {name!r} value must be a non-empty string"
            )
        if "\r" in value or "\n" in value:
            raise ValueError(
                f"auth_context header {name!r} value must not contain CR or LF"
            )

    # FR-AUTH: optional role/realm-tagged credential sets. Each role's set is
    # itself a flat credential set, so it is validated by the SAME rules (recurse);
    # `roles`/`default_role`/`realm` are reserved, so the header loop above already
    # skipped them. A partial PUT setting one role deep-merges (pg.save_settings),
    # never wiping a sibling role.
    roles = auth_context.get("roles")
    if roles is not None:
        if not isinstance(roles, dict):
            raise ValueError("auth_context.roles must be an object mapping role -> credential set")
        for role_name, role_set in roles.items():
            if not isinstance(role_set, dict):
                raise ValueError(f"auth_context.roles.{role_name} must be an object")
            _validate_auth_context(role_set)  # a role's set is a flat auth_context
    default_role = auth_context.get("default_role")
    if default_role is not None:
        if not isinstance(default_role, str):
            raise ValueError("auth_context.default_role must be a string")
        if default_role not in (roles or {}):
            raise ValueError(
                f"auth_context.default_role {default_role!r} has no matching entry in roles"
            )
    realm = auth_context.get("realm")
    if realm is not None and not isinstance(realm, str):
        raise ValueError("auth_context.realm must be a string")


@router.post("/projects")
def create_project(body: ProjectCreate) -> dict:
    project_id = str(uuid.uuid4())
    pg.create_project(project_id, body.name)
    return {"project_id": project_id}


@router.get("/projects")
def list_projects() -> dict:
    return {"projects": pg.list_projects()}


@router.get("/projects/{project_id}/graph")
def project_graph(project_id: str) -> dict:
    if not pg.project_exists(project_id):
        raise HTTPException(status_code=404, detail="unknown project")
    g = fetch_project_graph(project_id)
    return {"project_id": project_id, "nodes": g["nodes"], "links": g["links"]}


@router.get("/runs")
def list_runs(status: str | None = None) -> dict:
    if status != "running":
        raise HTTPException(status_code=400, detail="only status=running is supported")
    ttl = config.LIVENESS_TTL_SECONDS
    now = datetime.now(timezone.utc)
    runs = []
    for r in pg.list_running_runs():
        hb = r["last_heartbeat_at"]
        live = hb is not None and (now - hb).total_seconds() <= ttl
        runs.append({**r, "liveness": "live" if live else "stalled"})
    return {"runs": runs, "liveness_ttl_seconds": ttl}


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

    # Refuse to launch a targetless run: without target_domain the pipeline
    # silently falls back to the example.com placeholder and scans an unrelated
    # third party. Fail loudly instead so a wiped/omitted target is caught here.
    if not (pg.load_settings(project_id) or {}).get("target_domain"):
        raise HTTPException(
            status_code=400,
            detail="no target_domain configured; PUT /projects/{id}/settings "
                   "with recon.target_domain before launching recon",
        )

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
