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
import logging

from agent.app.config import config
from agent.app.clients.pg import touch_run_heartbeat as _touch_heartbeat
from agent.recon.curator import ALLOWED_LABELS
from agent.recon.jobs import JOBS, build_phase_plan, validate_job_subset
from agent.recon.scope import DISCOVERY_JOBS, parse_scope

logger = logging.getLogger(__name__)

# Node properties that are bookkeeping, not part of an asset's identity -
# excluded when re-hydrating produced assets from Neo4j for the next phase.
_NON_IDENTITY_KEYS = {"project_id", "first_seen", "last_seen"}


def seed_assets(settings: dict) -> list[dict]:
    """Phase-0 root input: the project's target apex domain (or a deterministic
    placeholder if none is configured).

    The raw `target_domain` may carry a `*.` wildcard placeholder (D14); the
    Domain-consuming phase-0 jobs (subfinder/whois/gau/...) must run against the
    bare apex, never the literal `*.example.com`, so the scope descriptor's
    parsed `apex` is used rather than the raw setting."""
    scope = parse_scope(settings.get("target_domain"))
    return [{"name": scope["apex"]}]


def _gate_plan_by_scope(plan: list[list[str]], scope: dict) -> list[list[str]]:
    """Apply the D14 scope gate: in `exact` mode, drop the subdomain-discovery
    jobs (`DISCOVERY_JOBS`) from every phase and drop any phase left empty. In
    `wildcard` mode the plan is returned unchanged (discovery runs as today).

    `subdomain_takeover` is not in `DISCOVERY_JOBS`, so it survives the gate."""
    if scope["mode"] != "exact":
        return plan
    gated = [[j for j in phase if j not in DISCOVERY_JOBS] for phase in plan]
    return [phase for phase in gated if phase]


def _inject_seed_host(input_assets: list[dict], scope: dict) -> list[dict]:
    """Ensure the scope's seed host is in a Subdomain-consuming job's input set.

    D11/D14: the primary host (the apex in wildcard mode, the exact host in
    exact mode) must be HTTP-probed / port-scanned even when subdomain discovery
    did not produce it - the apex is a `Domain` node, never a `Subdomain`, and
    in exact mode discovery is suppressed entirely. Prepending (not appending)
    guarantees the seed host survives the MAX_PODS cap the per-job orchestrator
    applies to a large discovered-subdomain population."""
    seed_host = scope.get("seed_host")
    if not seed_host:
        return input_assets
    if any(asset.get("name") == seed_host for asset in input_assets):
        return input_assets
    return [{"name": seed_host}, *input_assets]


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


async def _heartbeat_loop(run_id: str) -> None:
    """Refresh the run heartbeat every HEARTBEAT_TICK_SECONDS until cancelled."""
    try:
        while True:
            await asyncio.sleep(config.HEARTBEAT_TICK_SECONDS)
            try:
                # Offload the blocking pg write so the heartbeat tick never
                # depends on (or blocks) the API event loop - a stalled tick is
                # exactly what makes the reaper spuriously fail a live run.
                await asyncio.to_thread(_touch_heartbeat, run_id)
            except Exception:  # best-effort; a heartbeat blip must not crash the run
                logger.warning("heartbeat tick failed for run %s", run_id, exc_info=True)
    except asyncio.CancelledError:
        return


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

    # All DB helpers below (pg + neo4j) are synchronous/blocking. run_pipeline
    # runs on the API event loop, so every one is offloaded via asyncio.to_thread
    # - otherwise a single slow query stalls the whole API (health, polls,
    # /graph) and starves the heartbeat under concurrent runs (Defect C).
    settings = (await asyncio.to_thread(load_settings, project_id)) or {}

    if job_subset is not None:
        validate_job_subset(job_subset)

    scope = parse_scope(settings.get("target_domain"))
    # D14: suppress subdomain discovery when the target is an exact host. The
    # gate is applied to the resolved plan (not re-validated) - the seed-host
    # injection below is what satisfies the Subdomain-consuming jobs at runtime
    # once their discovery producers are gone.
    plan = _gate_plan_by_scope(build_phase_plan(job_subset), scope)

    await asyncio.to_thread(registry.create_run, run_id, project_id)
    hb = asyncio.create_task(_heartbeat_loop(run_id))
    try:
        for phase_idx, phase_jobs in enumerate(plan):
            job_configs: dict[str, tuple] = {}
            for name in phase_jobs:
                job = JOBS[name]
                try:
                    if phase_idx == 0:
                        input_assets = seed_assets(settings)
                    else:
                        input_assets = await asyncio.to_thread(
                            read_assets, job.consumes, project_id
                        )
                        # D11/D14: the primary host is a Domain node, never a
                        # Subdomain, so it is never in a Subdomain-consuming
                        # job's input set on its own. Seed it in so httpx/naabu/
                        # takeover reach the apex (wildcard) or the single exact
                        # host (exact, where discovery produced nothing).
                        if job.consumes == "Subdomain":
                            input_assets = _inject_seed_host(input_assets, scope)

                    extra = {"project_id": project_id}
                    if job.use_auth and settings.get("auth_context"):
                        extra["auth_context"] = settings["auth_context"]

                    await asyncio.to_thread(
                        registry.upsert_job, run_id, phase_idx, name, "in_progress"
                    )
                except Exception as exc:  # best-effort: a setup blip degrades
                    # only this job, it must never leave the run stuck non-terminal.
                    await asyncio.to_thread(
                        registry.upsert_job, run_id, phase_idx, name, "degraded", error=str(exc)
                    )
                    continue
                job_configs[name] = (job, input_assets, extra)

            async def _run_one(name: str) -> None:
                job, input_assets, extra = job_configs[name]
                try:
                    pod_exports = await run_job(
                        job, input_assets, run_id=run_id, phase=phase_idx, extra=extra
                    )
                except Exception as exc:  # best-effort: never abort the pipeline
                    await asyncio.to_thread(
                        registry.upsert_job, run_id, phase_idx, name, "degraded", error=str(exc)
                    )
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

                # Per-job data lineage (D12): consumed = number of input
                # assets this job was asked to process; produced_* = assets /
                # observations merged into the graph (new+updated) summed
                # across this job's pods. Persisted inside the existing stats
                # JSONB so "phases executed with the data they consumed/
                # produced" is verifiable from state, not reconstructed.
                produced_assets = sum(e.assets_merged for e in pod_exports)
                produced_observations = sum(e.observations_merged for e in pod_exports)
                job_stats = {
                    "pods": total,
                    "success": succeeded,
                    "failed": failed,
                    "consumed": len(input_assets),
                    "produced_assets": produced_assets,
                    "produced_observations": produced_observations,
                }
                # Surface a crawl job's Steel viewer URL (interactive
                # steel_await_auth MVP path, see crawl_pod.py) so
                # GET /recon/{run_id} lets the operator complete manual login -
                # pass through the first pod export that carries one.
                viewer_url = next(
                    (
                        e.stats.get("viewer_url")
                        for e in pod_exports
                        if e.stats and e.stats.get("viewer_url")
                    ),
                    None,
                )
                if viewer_url:
                    job_stats["viewer_url"] = viewer_url

                await asyncio.to_thread(
                    registry.upsert_job,
                    run_id,
                    phase_idx,
                    name,
                    status,
                    stats=job_stats,
                )

            await asyncio.to_thread(
                registry.set_run_status, run_id, "running", current_phase=phase_idx
            )
            await asyncio.gather(*[_run_one(name) for name in job_configs])
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
    await asyncio.to_thread(registry.set_run_status, run_id, "complete")
