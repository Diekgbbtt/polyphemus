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
    """Phase-0 root input: the Domain node the phase-0 Domain-consuming jobs run
    against (or a deterministic placeholder if none is configured).

    - `wildcard` mode: the parsed `apex` (never the literal `*.example.com`) -
      subfinder/amass need the registrable parent to enumerate the zone.
    - `exact` mode: the `seed_host` itself, NOT the registrable apex (D14 Q2).
      subfinder/amass are already suppressed in exact mode, so the only
      remaining Domain-consumers are the ungated passive harvesters
      (gau/paramspider); seeding the exact host keeps them confined to the
      in-scope host instead of harvesting the whole zone. (whois also consumes
      the exact host in exact-subdomain mode - accepted as low-signal, D14b.)"""
    scope = parse_scope(settings.get("target_domain"))
    name = scope["seed_host"] if scope["mode"] == "exact" else scope["apex"]
    return [{"name": name}]


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
    guarantees the seed host survives the per-job MAX_JOB_ASSETS budget cap the
    orchestrator applies to a large discovered-subdomain population (MAX_PODS is
    now the concurrency ceiling, not an asset cap - see job_agent)."""
    seed_host = scope.get("seed_host")
    if not seed_host:
        return input_assets
    if any(asset.get("name") == seed_host for asset in input_assets):
        return input_assets
    return [{"name": seed_host}, *input_assets]


def read_assets(
    node_type: str, project_id: str, where=None, *, driver=None
) -> list[dict]:
    """Re-query Neo4j for all `node_type` nodes belonging to `project_id`,
    returning each as an identity dict (bookkeeping props stripped).

    `node_type` is validated against the Layer-0 label allowlist
    (`agent.recon.curator.ALLOWED_LABELS`) before being interpolated into
    the Cypher label position - the only place a label can legally appear
    unparameterised. Values stay fully parameterised.

    `where` (an optional `AssetSelector`) narrows the read-back set beyond the
    bare label - e.g. jsluice consumes `Endpoint` but only the `.js`/`.mjs`
    bundles (D17/Q5). The predicate is applied purely in Python via
    `apply_selector`, so this stays a reusable label-plus-predicate read, not a
    per-tool special case. (The label population read here is one query per job
    per run; pushing the suffix into Cypher is a possible future optimization.)
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

    assets = [
        {k: v for k, v in record.items() if k not in _NON_IDENTITY_KEYS}
        for record in records
    ]

    from agent.recon.selectors import apply_selector

    return apply_selector(assets, where)


def read_steering_signals(project_id: str, *, driver=None) -> list[dict]:
    """Return the live WAF steering signals (fail-open to []).

    Each signal is {"url", "macro_kind", "evidence"} for a BaseURL carrying a
    WAF observation. A DELIBERATELY separate read from read_assets, which is
    label-allowlist-clean and must never read Observation nodes. Any error ->
    [], so a steering-read blip degrades adaptivity, never the run (mirrors the
    heartbeat/upsert_job best-effort ethos). WAF observations anchor to BaseURL
    with identity {"url": ...} (curator ANCHOR_ALLOWLIST)."""
    from agent.recon.steering import WAF_MACRO_KINDS
    try:
        if driver is None:
            from agent.app.clients import neo4j_client
            driver = neo4j_client._driver
        query = (
            "MATCH (a:BaseURL {project_id: $project_id})-[:HAS_OBSERVATION]->"
            "(o:Observation {project_id: $project_id}) "
            "WHERE o.macro_kind IN $kinds "
            "RETURN DISTINCT a.url AS url, o.macro_kind AS macro_kind, o.evidence AS evidence"
        )
        with driver.session() as session:
            result = session.run(query, project_id=project_id, kinds=sorted(WAF_MACRO_KINDS))
            return [
                {"url": r["url"], "macro_kind": r["macro_kind"], "evidence": r["evidence"]}
                for r in result if r["url"]
            ]
    except Exception:
        logger.warning("read_steering_signals failed for %s; no adaptation", project_id, exc_info=True)
        return []


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
    read_steering_signals=None,
    decide_routing=None,
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
    if read_steering_signals is None:
        read_steering_signals = globals()["read_steering_signals"]
    if decide_routing is None:
        from agent.recon.orchestrator_agent import decide_routing as decide_routing  # noqa: PLC0414

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

    # D14 Q1: an exact-scope run is deliberately small (no subdomain fan-out).
    # Record why at run start so an otherwise near-empty run is self-explaining
    # rather than looking silently broken. recon_runs/recon_jobs carry no
    # run-level note column, so this is a structured log (no schema change).
    if scope["mode"] == "exact":
        logger.info(
            "run %s scope=exact target=%s; subdomain discovery suppressed (%s)",
            run_id,
            scope["seed_host"],
            "/".join(sorted(DISCOVERY_JOBS)),
        )

    await asyncio.to_thread(registry.create_run, run_id, project_id)
    hb = asyncio.create_task(_heartbeat_loop(run_id))
    signals: list[dict] = []
    try:
        for phase_idx, phase_jobs in enumerate(plan):
            job_configs: dict[str, tuple] = {}
            exclusions = (
                await asyncio.to_thread(decide_routing, signals, phase_jobs) if signals else {}
            )
            for name in phase_jobs:
                job = JOBS[name]
                try:
                    if phase_idx == 0:
                        input_assets = seed_assets(settings)
                    elif job.consumes_where is not None:
                        input_assets = await asyncio.to_thread(
                            read_assets, job.consumes, project_id, job.consumes_where
                        )
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

                    # Batched jobs (jsluice, D17/Q6): the raw per-bundle assets
                    # are reduced (first-party filter + url/basename dedup) and
                    # distributed across <= MAX_PODS pods, each carrying a
                    # `batch` list. Here MAX_PODS is deliberately a pod-COUNT
                    # target (pack all bundles into <= MAX_PODS looping pods) -
                    # intentionally different from the job-level semantics where
                    # MAX_PODS is only the concurrency ceiling; the resulting
                    # <= MAX_PODS batch-pods then run within that same ceiling.
                    if job.batch:
                        from agent.recon.batching import build_batch_assets
                        from agent.recon.config import MAX_PODS
                        from agent.recon.parsers._urls import registrable_domain

                        target = settings.get("target_domain")
                        apex = registrable_domain(target) if target else None
                        input_assets = build_batch_assets(
                            input_assets, apex_registrable=apex, max_pods=MAX_PODS
                        )

                    excluded = set(exclusions.get(name, []))
                    if excluded:
                        input_assets = [a for a in input_assets if a.get("url") not in excluded]

                    extra = {"project_id": project_id}
                    if job.use_auth and settings.get("auth_context"):
                        extra["auth_context"] = settings["auth_context"]
                    # Scope gate for URL-hosted assets (out-of-scope BaseURL
                    # drop in curate): the seed host/apex, only when a target is
                    # actually configured (never the parse_scope placeholder).
                    if settings.get("target_domain"):
                        extra["scope_domain"] = scope["seed_host"]
                    if signals:
                        extra["steering"] = signals

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
                commands = [
                    e.stats.get("command")
                    for e in pod_exports
                    if e.stats and e.stats.get("command")
                ]
                if commands:
                    job_stats["commands"] = commands
                # Surface a crawl job's Steel viewer URL (interactive
                # steel_await_auth MVP path, see crawl_pod.py) so
                # GET /recon/{run_id} lets the operator complete manual login -
                # pass through the first pod export that carries one.
                # C2 (operator-accepted 2026-07-13): the viewer_url is the POD's
                # to own; the pod already surfaced it mid-flight (crawl_pod.
                # default_status_sink) because this pipeline is blocked on
                # `await run_job` above and cannot surface it in time itself.
                # This terminal pass-through only RE-ASSERTS it so the final
                # full-stats write does not clobber the pod's mid-flight write.
                # Left as-is (not critical). ENHANCEMENT (D24): per-component
                # logs (orchestrator / job / pod) let the viewer_url surface from
                # the pod's own log, retiring this two-writer coordination.
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
            signals = await asyncio.to_thread(read_steering_signals, project_id)
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
    await asyncio.to_thread(registry.set_run_status, run_id, "complete")
