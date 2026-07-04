# agent/recon/pipeline.py
"""Pipeline orchestrator: drives the phase DAG (`agent.recon.jobs`) across
runs, seeding phase 0 from the project's target domain and later phases from
Neo4j-produced assets, threading the auth channel to `use_auth` jobs, and
recording per-job/per-run status in the Postgres registry
(`agent.app.clients.pg`).

Best-effort by design (design §10.6): one job's failure (all its pods
failing, or `run_job` itself raising) degrades that job but never aborts the
run - the pipeline always reaches a terminal `set_run_status(..., "complete")`.

Every phase is a hard barrier: all of a phase's jobs run concurrently via
`asyncio.gather`, and the next phase does not start (its jobs' `input_assets`
are not even resolved) until every job in the current phase has returned.

`run_job`, `load_settings`, `registry`, and `read_assets` are all injected so
tests can fully mock Neo4j/Postgres/pod-graph collaborators; production
defaults to the real `agent.recon.job_agent.run_job`,
`agent.app.clients.pg.load_settings`, the `pg` module itself as the
registry, and the `read_assets` helper below.
"""
from __future__ import annotations

import asyncio

from agent.recon.curator import ALLOWED_LABELS
from agent.recon.jobs import JOBS, build_phase_plan, validate_job_subset

# Node properties that are bookkeeping, not part of an asset's identity -
# excluded when re-hydrating produced assets from Neo4j for the next phase.
_NON_IDENTITY_KEYS = {"project_id", "first_seen", "last_seen"}


def seed_assets(settings: dict) -> list[dict]:
    """Phase-0 root input: the project's target domain (or a deterministic
    placeholder if none is configured)."""
    return [{"name": settings.get("target_domain") or "example.com"}]


def read_assets(node_type: str, project_id: str, *, driver=None) -> list[dict]:
    """Re-query Neo4j for all `node_type` nodes belonging to `project_id`,
    returning each as an identity dict (bookkeeping props stripped).

    `node_type` is validated against the Layer-0 label allowlist
    (`agent.recon.curator.ALLOWED_LABELS`) before being interpolated into
    the Cypher label position - the only place a label can legally appear
    unparameterised. Values stay fully parameterised.
    """
    if node_type not in ALLOWED_LABELS:
        raise ValueError(f"Unknown asset label: {node_type!r}")

    if driver is None:
        from agent.app.clients import neo4j_client

        driver = neo4j_client._driver

    query = f"MATCH (n:{node_type} {{project_id: $project_id}}) RETURN n"
    with driver.session() as session:
        result = session.run(query, project_id=project_id)
        records = [dict(record["n"]) for record in result]

    return [
        {k: v for k, v in record.items() if k not in _NON_IDENTITY_KEYS}
        for record in records
    ]


async def run_pipeline(
    project_id: str,
    *,
    run_id: str,
    job_subset: list[str] | None = None,
    run_job=None,
    load_settings=None,
    registry=None,
    read_assets=None,
) -> None:
    """Drive the full (or subset) phase plan for `project_id` under `run_id`.

    Best-effort: a job whose pods all fail, or whose `run_job` call raises,
    is marked "degraded" and the pipeline continues - it always reaches a
    terminal `set_run_status(run_id, "complete")`.
    """
    if run_job is None:
        from agent.recon.job_agent import run_job as run_job  # noqa: PLC0414
    if load_settings is None:
        from agent.app.clients.pg import load_settings as load_settings  # noqa: PLC0414
    if registry is None:
        from agent.app.clients import pg as registry
    if read_assets is None:
        read_assets = globals()["read_assets"]

    settings = load_settings(project_id) or {}

    if job_subset is not None:
        validate_job_subset(job_subset)

    plan = build_phase_plan(job_subset)

    registry.create_run(run_id, project_id)

    for phase_idx, phase_jobs in enumerate(plan):
        job_configs: dict[str, tuple] = {}
        for name in phase_jobs:
            job = JOBS[name]
            try:
                if phase_idx == 0:
                    input_assets = seed_assets(settings)
                else:
                    input_assets = read_assets(job.consumes, project_id)

                extra = {"project_id": project_id}
                if job.use_auth and settings.get("auth_context"):
                    extra["auth_context"] = settings["auth_context"]

                registry.upsert_job(run_id, phase_idx, name, "in_progress")
            except Exception as exc:  # best-effort: a setup blip degrades
                # only this job, it must never leave the run stuck non-terminal.
                registry.upsert_job(run_id, phase_idx, name, "degraded", error=str(exc))
                continue
            job_configs[name] = (job, input_assets, extra)

        async def _run_one(name: str) -> None:
            job, input_assets, extra = job_configs[name]
            try:
                pod_exports = await run_job(
                    job, input_assets, run_id=run_id, phase=phase_idx, extra=extra
                )
            except Exception as exc:  # best-effort: never abort the pipeline
                registry.upsert_job(run_id, phase_idx, name, "degraded", error=str(exc))
                return

            total = len(pod_exports)
            succeeded = sum(1 for e in pod_exports if e.verdict == "success")
            failed = sum(1 for e in pod_exports if e.verdict == "failed")

            if total == 0:
                status = "skipped"
            elif failed == total:
                status = "degraded"
            else:
                status = "success"

            registry.upsert_job(
                run_id,
                phase_idx,
                name,
                status,
                stats={"pods": total, "success": succeeded, "failed": failed},
            )

        registry.set_run_status(run_id, "running", current_phase=phase_idx)
        await asyncio.gather(*[_run_one(name) for name in job_configs])

    registry.set_run_status(run_id, "complete")
