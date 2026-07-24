"""Operator-intent use-cases - the project_management application layer.

Every project / settings / run operation the operator surface offers lives here
as a plain function over the Postgres gateway (`app.clients.pg`). These
functions raise DOMAIN errors (`ProjectNotFound`, `RunNotFound`) or `ValueError`
for contract violations; they never speak HTTP. `api.py` is the thin adapter
that maps those onto status codes.

This is a deep module over a thin gateway (CODING_STANDARD §0): the raw SQL
stays generic in `pg`, the operator's use-cases (launch guards, liveness
annotation, settings validation) are modelled here. The context LAUNCHES recon
via the `_launch_pipeline` seam owned by `api` - it never imports the pipeline
eagerly, keeping the dependency `project_management -> recon` lazy.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from polymerhus.app.clients import pg
from polymerhus.app.config import config
from polymerhus.project_management.auth_context import validate_auth_context
from polymerhus.recon.control.jobs import JOBS, validate_job_subset
from polymerhus.recon.control.scope import resolve_seed, seed_kind
from polymerhus.recon.domain.graph_read import fetch_project_graph


class ProjectNotFound(Exception):
    """No project with the given id exists."""


class RunNotFound(Exception):
    """No run with the given id exists."""


def create_project(name: str) -> str:
    """Create a project and return its freshly-minted id."""
    project_id = str(uuid.uuid4())
    pg.create_project(project_id, name)
    return project_id


def list_projects() -> list:
    return pg.list_projects()


def project_graph(project_id: str) -> dict:
    """The project's attack-surface graph. Raises ProjectNotFound if unknown."""
    if not pg.project_exists(project_id):
        raise ProjectNotFound(project_id)
    g = fetch_project_graph(project_id)
    return {"project_id": project_id, "nodes": g["nodes"], "links": g["links"]}


def running_runs(now: datetime | None = None) -> dict:
    """Currently-running runs, each annotated live/stalled against the liveness
    TTL by comparing its last heartbeat to `now` (injectable for tests)."""
    ttl = config.LIVENESS_TTL_SECONDS
    now = now or datetime.now(timezone.utc)
    runs = []
    for r in pg.list_running_runs():
        hb = r["last_heartbeat_at"]
        live = hb is not None and (now - hb).total_seconds() <= ttl
        runs.append({**r, "liveness": "live" if live else "stalled"})
    return {"runs": runs, "liveness_ttl_seconds": ttl}


def save_project_settings(project_id: str, recon: dict) -> None:
    """Validate (the AuthContext contract) and persist a partial settings PUT.
    Raises ProjectNotFound if unknown, ValueError on a malformed auth_context."""
    if not pg.project_exists(project_id):
        raise ProjectNotFound(project_id)
    auth_context = recon.get("auth_context")
    if auth_context is not None:
        validate_auth_context(auth_context)  # ValueError on any shape violation
    pg.save_settings(project_id, recon)


def validate_launch(project_id: str, jobs: list[str] | None) -> None:
    """Guard a recon launch. Raises ProjectNotFound if unknown, ValueError for
    unknown/invalid job subsets, a missing target seed, or an IPv6 seed (D-HS3).

    Refusing a targetless run is deliberate: without a target seed the pipeline
    silently falls back to the example.com placeholder and scans an unrelated
    third party, so a wiped/omitted target is caught here rather than in prod.
    The seed is read via `resolve_seed` (canonical `target_seed`, legacy
    `target_domain` alias), so already-persisted projects still launch."""
    if not pg.project_exists(project_id):
        raise ProjectNotFound(project_id)
    if jobs is not None:
        unknown = [j for j in jobs if j not in JOBS]
        if unknown:
            raise ValueError(f"unknown job(s): {unknown}")
        validate_job_subset(jobs)  # ValueError on an incoherent subset
    seed = resolve_seed(pg.load_settings(project_id) or {})
    if not seed:
        raise ValueError(
            "no target_seed configured; PUT /projects/{id}/settings "
            "with recon.target_seed before launching recon"
        )
    # D-HS3: IPv6 seeding is designed-not-built. Reject it here rather than let
    # parse_scope's host-mode safety net reach an unbracketed URL-synthesis path.
    if seed_kind(seed) == "ipv6":
        raise ValueError(
            "IPv6 seeding is not supported yet; provide an IPv4 address or a domain"
        )


def open_run(project_id: str) -> str:
    """Create the run row synchronously and return its id, so a status poll
    immediately after launch never 404s. `run_pipeline` also calls create_run,
    but it is idempotent (ON CONFLICT DO NOTHING), so that call is a no-op."""
    run_id = str(uuid.uuid4())
    pg.create_run(run_id, project_id)
    return run_id


def recon_status(run_id: str) -> dict:
    """Run status + per-job breakdown. Raises RunNotFound if unknown."""
    run = pg.get_run(run_id)
    if run is None:
        raise RunNotFound(run_id)
    return {
        "status": run["status"],
        "current_phase": run["current_phase"],
        "per_job": pg.get_run_jobs(run_id),
    }
