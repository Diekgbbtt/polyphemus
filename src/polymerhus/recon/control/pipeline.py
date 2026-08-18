# src/polymerhus/recon/control/pipeline.py
"""Pipeline orchestrator: drives the phase DAG (`polymerhus.recon.control.jobs`) across
runs, seeding phase 0 from the project's target domain and later phases from
Neo4j-produced assets, threading the auth channel to `use_auth` jobs, and
recording per-job/per-run status in the Postgres registry
(`polymerhus.app.clients.pg`).

Best-effort by design (design §10.6): one job's failure (all its pods
failing, or `run_job` itself raising) degrades that job but never aborts the
run - the pipeline always reaches a terminal `set_run_status(..., "complete")`.

Every phase is a hard barrier: a phase's jobs run sequentially, one job's
`run_job` call (its MAX_PODS pod fan-out included) completing before the next
job in the phase starts - this bounds peak concurrency to a single job's pods
rather than (jobs in phase) x MAX_PODS. The next phase does not start (its
jobs' `input_assets` are not even resolved) until every job in the current
phase has returned.

`run_job`, `load_settings`, `registry`, `read_assets`, and `decide_routing` are
all injected so tests can fully mock Neo4j/Postgres/pod-graph collaborators;
production defaults to the real `polymerhus.recon.control.job_agent.run_job`,
`polymerhus.app.clients.pg.load_settings`, the `pg` module itself as the
registry, the `read_assets` helper below, and - since feat/async-actor-agents -
a mailbox-actor recon-orchestrator (`ReconOrchestratorActor`, see
`orchestrator_agent.py`) as the steering seam between phases.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from datetime import datetime, timezone

from polymerhus.app.config import config
from polymerhus.app.clients.pg import touch_run_heartbeat as _touch_heartbeat
from polymerhus.recon.control.auth import select_auth_context
from polymerhus.recon.domain.curator import ALLOWED_LABELS, curate
from polymerhus.recon.control.jobs import JOBS, build_phase_plan, validate_job_subset
from polymerhus.recon.control.scope import (
    DISCOVERY_JOBS,
    HOST_MODE_ONLY_JOBS,
    HOST_MODE_SUPPRESSED,
    parse_scope,
    resolve_seed,
)
from polymerhus.recon.domain.types import AssetDelta

logger = logging.getLogger(__name__)

# Node properties that are bookkeeping, not part of an asset's identity -
# excluded when re-hydrating produced assets from Neo4j for the next phase.
_NON_IDENTITY_KEYS = {"project_id", "first_seen", "last_seen"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _phase_exclusions(decide, signals: list[dict], phase_jobs: list[str]) -> dict[str, list[str]]:
    """Resolve one phase's routing decision through the `run_pipeline` steering seam.

    Empty signals short-circuit to {} (the orchestrator is only invoked with a
    non-empty signal list). The seam is polymorphic: an injected SYNC callable
    (the historical one-shot `decide_routing` lambda) is offloaded via
    `to_thread`; an async callable (the actor client method,
    feat/async-actor-agents) is awaited. Either way the decision is
    {job_name: [urls to exclude]} and a steering blip degrades adaptivity, never
    the run (fail-open is the collaborator's own contract)."""
    if not signals or not phase_jobs:
        return {}
    if inspect.iscoroutinefunction(decide):
        return await decide(signals, phase_jobs)
    return await asyncio.to_thread(decide, signals, phase_jobs)


def _exec_window(t0: float, started_at: str) -> dict:
    """A job's real execution window, persisted into `recon_jobs.stats`.

    Recorded because the row's own `started_at` column cannot answer "when did this
    job actually run" (see `_run_one`), and the stall predicate needs the gap
    BETWEEN jobs - which is where the analyser's time was being spent. Duration
    from `time.monotonic` so a clock step cannot manufacture or hide a stall; the
    endpoints in wall-clock UTC so they join against a pass census and a trace."""
    return {
        "exec_started_at": started_at,
        "exec_finished_at": _utc_now_iso(),
        "exec_seconds": round(time.monotonic() - t0, 3),
    }


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
    scope = parse_scope(resolve_seed(settings))
    name = scope["seed_host"] if scope["mode"] == "exact" else scope["apex"]
    return [{"name": name}]


def _gate_plan_by_scope(plan: list[list[str]], scope: dict) -> list[list[str]]:
    """Apply the scope gate, dropping jobs a mode must not run and any phase left
    empty:

    - `exact` (D14): drop `DISCOVERY_JOBS` (subdomain enumeration is moot for a
      single host) and `HOST_MODE_ONLY_JOBS` (never run outside host mode).
    - `host` (D-HS S2): drop `DISCOVERY_JOBS` and `HOST_MODE_SUPPRESSED`
      (whois/paramspider are low-signal on a bare IP); KEEP `HOST_MODE_ONLY_JOBS`
      (the httpx_services bridge).
    - `wildcard`: keep everything except `HOST_MODE_ONLY_JOBS`.

    `subdomain_takeover` is in none of these sets, so it survives every mode
    (the D14 carve-out)."""
    mode = scope.get("mode")
    if mode == "host":
        drop = DISCOVERY_JOBS | HOST_MODE_SUPPRESSED
    elif mode == "exact":
        drop = DISCOVERY_JOBS | HOST_MODE_ONLY_JOBS
    else:  # wildcard (and any unknown mode): only fence off the host-only jobs
        drop = HOST_MODE_ONLY_JOBS
    gated = [[j for j in phase if j not in drop] for phase in plan]
    return [phase for phase in gated if phase]


def _services_to_probe_targets(input_assets: list[dict]) -> list[dict]:
    """Map naabu `Service` nodes to scheme-less httpx probe targets, one per
    non-default web port (D-HS S5a).

    Ports 80/443 are skipped: the phase-3 httpx probe already mints their
    (portless, canonical) BaseURLs, so re-probing them here would create a
    `:80`/`:443` alias (D-HS Trap 1). The target is scheme-less `<ip>:<port>` so
    httpx is the protocol detector - a service naabu labelled `unknown` (its
    naming is port-number-based) is still probed, and a non-web port simply
    yields no BaseURL. Deduped on the synthesized target."""
    targets: list[dict] = []
    seen: set[str] = set()
    for svc in input_assets or []:
        ip = svc.get("ip_address")
        port = svc.get("port_number")
        if not ip or port in (None, 80, 443):
            continue
        target = f"{ip}:{port}"
        if target in seen:
            continue
        seen.add(target)
        targets.append({"url": target, "target": target})
    return targets


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


def _seed_domain_host(scope: dict) -> list[dict]:
    """The single canonical host a later-phase Domain-consuming passive harvester
    (paramspider) runs against - EXACTLY ONE pod per zone, in both scope modes.

    D14/D19: paramspider (`consumes="Domain"`) harvests archived URLs for a whole
    zone from a single seed; it must run once, never fan out per-subdomain (the
    wildcard rate-ban risk) and never double up the apex plus an exact subdomain.
    The host mirrors `seed_assets`: the exact host in exact mode (confine the
    harvest to the in-scope host), the registrable apex in wildcard mode (harvest
    the zone once). This REPLACES whatever Domain nodes the graph read returned,
    so paramspider runs even when whois produced no Domain node - and stays a
    single pod even when whois produced several."""
    name = scope["seed_host"] if scope["mode"] == "exact" else scope["apex"]
    return [{"name": name}]


def read_assets(
    node_type: str, project_id: str, where=None, *, driver=None
) -> list[dict]:
    """Re-query Neo4j for all `node_type` nodes belonging to `project_id`,
    returning each as an identity dict (bookkeeping props stripped).

    `node_type` is validated against the Layer-0 label allowlist
    (`polymerhus.recon.domain.curator.ALLOWED_LABELS`) before being interpolated into
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
        from polymerhus.app.clients import neo4j_client

        driver = neo4j_client._driver

    query = f"MATCH (n:{node_type} {{project_id: $project_id}}) RETURN n"
    with driver.session() as session:
        result = session.run(query, project_id=project_id)
        records = [dict(record["n"]) for record in result]

    assets = [
        {k: v for k, v in record.items() if k not in _NON_IDENTITY_KEYS}
        for record in records
    ]

    from polymerhus.recon.domain.selectors import apply_selector

    return apply_selector(assets, where)


def read_steering_signals(project_id: str, *, driver=None) -> list[dict]:
    """Return the live WAF steering signals (fail-open to []).

    Each signal is {"url", "macro_kind", "evidence"} for a BaseURL carrying a
    WAF observation. A DELIBERATELY separate read from read_assets, which is
    label-allowlist-clean and must never read Observation nodes. Any error ->
    [], so a steering-read blip degrades adaptivity, never the run (mirrors the
    heartbeat/upsert_job best-effort ethos). WAF observations anchor to BaseURL
    with identity {"url": ...} (curator ANCHOR_ALLOWLIST)."""
    from polymerhus.recon.control.steering import WAF_MACRO_KINDS
    try:
        if driver is None:
            from polymerhus.app.clients import neo4j_client
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
    orchestrator_factory=None,
    feed_mode: str | None = None,
    pass_fn=None,
    with_analysis: bool = True,
) -> None:
    """Drive the full (or subset) phase plan for `project_id` under `run_id`.

    `with_analysis` (#75): when True (the combined dispatch) recon also STARTS the
    independent analysis consumer for this run; when False (the recon-only
    dispatch) recon only pushes chunks to the run's FIFO and a later analysis-only
    dispatch drains them. Either way recon NEVER waits on analysis.

    `decide_routing` is the steering seam between phases. It is INJECTABLE for
    tests and rollback: a sync callable (the historical one-shot `decide_routing`
    lambda) runs via `to_thread`, an async callable is awaited. When None (the
    production default, feat/async-actor-agents), the recon-orchestrator runs as a
    persistent MAILBOX ACTOR for the run (`ReconOrchestratorActor`, one
    `job_orchestrator` session thread) - each phase's steering is fed to its inbox
    and the parsed `RoutingDecision` awaited, with the actor's checkpointed memory
    carrying the reasoning across phases; the actor is stopped in the `finally`
    so no task leaks. `orchestrator_factory(run_id)` builds the actor (tests
    inject a fake or a real actor with a fake model).

    Best-effort: a job whose pods all fail, or whose `run_job` call raises,
    is marked "degraded" and the pipeline continues - it always reaches a
    terminal `set_run_status(run_id, "complete")`.
    """
    if run_job is None:
        from polymerhus.recon.control.job_agent import run_job as run_job  # noqa: PLC0414
    if load_settings is None:
        from polymerhus.app.clients.pg import load_settings as load_settings  # noqa: PLC0414
    if registry is None:
        from polymerhus.app.clients import pg as registry
    if read_assets is None:
        read_assets = globals()["read_assets"]
    if read_steering_signals is None:
        read_steering_signals = globals()["read_steering_signals"]

    orchestrator = None
    if decide_routing is None:
        if orchestrator_factory is None:
            from polymerhus.recon.control.orchestrator_agent import ReconOrchestratorActor

            def _default_factory(_run_id: str):
                return ReconOrchestratorActor(run_id=_run_id)

            orchestrator_factory = _default_factory
        orchestrator = orchestrator_factory(run_id)
        _decide = orchestrator.decide_routing  # async client method
    else:
        _decide = decide_routing  # injected sync or async seam

    # All DB helpers below (pg + neo4j) are synchronous/blocking. run_pipeline
    # runs on the API event loop, so every one is offloaded via asyncio.to_thread
    # - otherwise a single slow query stalls the whole API (health, polls,
    # /graph) and starves the heartbeat under concurrent runs (Defect C).
    settings = (await asyncio.to_thread(load_settings, project_id)) or {}

    # FR-STREAM (NM-7, operator-pulled 2026-07-17): when enabled, the analyser is
    # fed each recon job's freshly-curated surface AS RECON PROCEEDS, so L1 is
    # integrated progressively. Default OFF -> batch stays the default (L1D-23).
    streaming = bool(settings.get("streaming_analysis"))
    # #34: the analysis touchpoint is a FEED handle, not a direct call. `inline`
    # reproduces today's blocking behaviour verbatim (the rollback path); `queued`
    # hands the pass to a per-run consumer so recon never waits on an LLM. The mode
    # is a settings flag, so this call site does not branch and rollback is a flip.
    from polymerhus.analysis.feed import (
        InlineAnalysisFeed, L0Chunk, get_or_create_feed, resolve_feed_mode,
    )
    _mode = feed_mode or resolve_feed_mode(settings)
    # #75: recon is the PRODUCER. For the `queued` (decoupled) mode it pushes onto
    # the run's per-run FIFO in the process-level registry - a feed that OUTLIVES
    # this task, so analysis can drain it independently. Recon starts the analysis
    # consumer itself only on the COMBINED dispatch (`with_analysis`); the recon-only
    # dispatch leaves the chunks for a later analysis-only dispatch. `inline` is the
    # coupled rollback path (analysis runs on this task), unchanged.
    feed = None
    if streaming:
        if _mode == "inline":
            feed = InlineAnalysisFeed(project_id, run_id, pass_fn=pass_fn)
        else:
            feed = get_or_create_feed(project_id, run_id, pass_fn=pass_fn)
            if with_analysis:
                from polymerhus.analysis.lifecycle import start_analysis
                start_analysis(project_id, run_id, pass_fn=pass_fn)

    if job_subset is not None:
        validate_job_subset(job_subset)

    scope = parse_scope(resolve_seed(settings))
    # D14: suppress subdomain discovery when the target is an exact host (and
    # additionally the passive harvesters in host mode, D-HS S2). The gate is
    # applied to the resolved plan (not re-validated) - the seed-host injection
    # below is what satisfies the Subdomain-consuming jobs at runtime once their
    # discovery producers are gone.
    plan = _gate_plan_by_scope(build_phase_plan(job_subset), scope)

    # D14 Q1 / D-HS: an exact- or host-scope run is deliberately small (no
    # subdomain fan-out). Record why at run start so an otherwise near-empty run
    # is self-explaining rather than looking silently broken. recon_runs/
    # recon_jobs carry no run-level note column, so this is a structured log.
    if scope["mode"] in ("exact", "host"):
        suppressed = DISCOVERY_JOBS | (HOST_MODE_SUPPRESSED if scope["mode"] == "host" else frozenset())
        logger.info(
            "run %s scope=%s target=%s; discovery suppressed (%s)",
            run_id,
            scope["mode"],
            scope["seed_host"],
            "/".join(sorted(suppressed)),
        )

    await asyncio.to_thread(registry.create_run, run_id, project_id)

    # D28 / D-HS S3: in exact and host mode, deterministically materialize the
    # seed as the engagement root up front - it must be on the attack surface
    # even if httpx never probes it (host down, timeout). A domain seed is a
    # `Domain{name}`; a bare-IP seed is an `IP{address}`. curate is idempotent
    # (MERGE), so a later probe of the same seed just re-asserts it.
    if scope["mode"] in ("exact", "host") and resolve_seed(settings):
        if scope["mode"] == "host":
            root = AssetDelta(type="IP", identity={"address": scope["seed_host"]})
        else:
            root = AssetDelta(type="Domain", identity={"name": scope["seed_host"]})
        await asyncio.to_thread(curate, [root], [], project_id)

    hb = asyncio.create_task(_heartbeat_loop(run_id))
    signals: list[dict] = []
    try:
        for phase_idx, phase_jobs in enumerate(plan):
            job_configs: dict[str, tuple] = {}
            exclusions = await _phase_exclusions(_decide, signals, phase_jobs)
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
                        # A later-phase Domain-consuming passive harvester
                        # (paramspider) must run EXACTLY ONE pod against the
                        # scope's canonical host - never per-subdomain, never
                        # apex+subdomain doubled, and even when whois produced no
                        # Domain node. The only phase-0 Domain consumers take the
                        # `phase_idx == 0` branch above, so this fires solely for
                        # the later-phase harvesters (paramspider today).
                        elif job.consumes == "Domain":
                            input_assets = _seed_domain_host(scope)
                        # D-HS S5a: the httpx_services bridge consumes naabu's
                        # Service nodes; synthesize a scheme-less `<ip>:<port>`
                        # probe target per non-default web port (80/443 skipped -
                        # the phase-3 httpx probe owns those, portlessly). httpx
                        # then mints the BaseURL for whatever responds.
                        elif job.consumes == "Service":
                            input_assets = _services_to_probe_targets(input_assets)

                    excluded = set(exclusions.get(name, []))
                    if excluded:
                        input_assets = [a for a in input_assets if a.get("url") not in excluded]

                    extra = {"project_id": project_id}
                    if job.use_auth and settings.get("auth_context"):
                        # FR-AUTH: select the DEFAULT role's credential set (honours
                        # default_role, else the flat unroled creds) so a role/realm-
                        # tagged auth_context never leaks its `roles` map to the tool.
                        selected = select_auth_context(settings["auth_context"])
                        if selected:
                            extra["auth_context"] = selected
                    # Scope gate for URL-hosted assets (out-of-scope BaseURL
                    # drop in curate): the seed host/apex/IP, only when a target
                    # is actually configured (never the parse_scope placeholder).
                    seed = resolve_seed(settings)
                    if seed:
                        extra["scope_domain"] = scope["seed_host"]
                        # D28 / D-HS S3: in exact and host mode the seed is the
                        # engagement root, not a Subdomain. Tell curate to promote
                        # any Subdomain the tools mint for it (httpx's BaseURL
                        # back-link etc.) to the root type, so the
                        # deterministically-seeded root is not duplicated: a
                        # `Domain` for a domain seed, an `IP` for a bare-IP seed.
                        if scope["mode"] in ("exact", "host"):
                            extra["seed_domain"] = scope["seed_host"]
                            if scope["mode"] == "host":
                                extra["seed_root_type"] = "IP"
                        # C3: batching (reduce + pack bundles into <= MAX_PODS
                        # pods) is the recon-JOB agent's concern, not the
                        # orchestrator's - the pipeline only supplies the one
                        # datum the reduction needs (the target's registrable
                        # apex, for the first-party filter), and only to the
                        # batched job that consumes it. The job agent's preprocess
                        # reads extra["apex_registrable"] and batches. In host mode
                        # the IP itself is the first-party key (registrable_domain
                        # on an IP is garbage).
                        if job.batch:
                            from polymerhus.recon.domain.parsers._urls import registrable_domain
                            extra["apex_registrable"] = (
                                scope["seed_host"] if scope["mode"] == "host"
                                else registrable_domain(seed)
                            )
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
                # The job's REAL execution window (#34 AST-DEC-09). `recon_jobs.
                # started_at` cannot serve: `upsert_job` stamps it with now() on
                # INSERT and leaves it untouched ON CONFLICT, and the phase-setup
                # loop above already inserted the `in_progress` row for every job in
                # this phase - so that column measures phase setup, not job start,
                # and a gap computed from it is meaningless.
                exec_t0 = time.monotonic()
                exec_started_at = _utc_now_iso()
                try:
                    pod_exports = await run_job(
                        job, input_assets, run_id=run_id, phase=phase_idx, extra=extra
                    )
                except Exception as exc:  # best-effort: never abort the pipeline
                    await asyncio.to_thread(
                        registry.upsert_job, run_id, phase_idx, name, "degraded",
                        stats=_exec_window(exec_t0, exec_started_at), error=str(exc)
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
                    **_exec_window(exec_t0, exec_started_at),
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

# FR-STREAM (NM-7) + #34: signal the analyser that this job added
                # surface, so L1 grows progressively during recon. Only when the job
                # actually produced surface (else the push is redundant).
                # `push` is NON-BLOCKING under the queued feed - that is the whole
                # point, and the memory bound moved with it: a process-wide semaphore
                # of one pass now does what strict serialisation used to do, so the
                # OOM failure mode the NM-7 ledger named stays closed. Under the
                # inline feed this call blocks exactly as it always did. Guarded
                # regardless: analysis never fails a healthy recon run. The chunk
                # carries the job's EXACTLY-curated L0 payload (the merged asset
                # and observation lists), so the feed re-reads no graph - each chunk
                # is consumed once, in push order (#74).
                #
                # The endpoint-reprofile pass (`endpoint_profiling`, phase 6) is
                # EXCLUDED (#9): it re-emits Endpoints the crawl phase already streamed,
                # adding only each Endpoint's own `profile`. The current proposers
                # (assigner/typist/data_modeller) do not read that per-endpoint profile,
                # so re-streaming those endpoints is a redundant re-analysis of surface
                # already judged. Nothing is lost: the pushes are exact per-job payloads
                # and the terminal drain pass is cumulative, so any genuinely-new asset
                # the reprofile probe incidentally mints is still observed by the next
                # produced job's pass or the terminal drain pass.
                if feed is not None and (produced_assets or produced_observations) \
                        and not job.endpoint_profiling:
                    chunk = L0Chunk(
                        project_id=project_id,
                        run_id=run_id, job=name, phase=phase_idx,
                        assets=[a for e in pod_exports for a in e.assets],
                        observations=[o for e in pod_exports for o in e.observations],
                    )
                    try:
                        await feed.push(chunk)
                    except Exception:  # best-effort: analysis never aborts recon
                        logger.warning(
                            "analysis feed push raised for run %s job %s (recon continues)",
                            run_id, name, exc_info=True,
                        )

            await asyncio.to_thread(
                registry.set_run_status, run_id, "running", current_phase=phase_idx
            )
            # Sequential, not gathered: peak concurrency must be one job's
            # MAX_PODS pod fan-out, not (jobs in phase) x MAX_PODS - the latter
            # OOM-killed the agent container on heavy phases (e.g. phase 4's
            # katana/ffuf/kiterunner/graphql-cop/paramspider/steel_crawl).
            for name in job_configs:
                await _run_one(name)
            signals = await asyncio.to_thread(read_steering_signals, project_id)

        # #75: recon and analysis are DECOUPLED. For the INLINE rollback path only,
        # analysis ran on this task, so record its stats onto the recon run as
        # before. The queued (decoupled) path records nothing here - the analysis
        # run owns its own status row.
        if feed is not None and getattr(feed, "mode", None) == "inline":
            try:
                feed_stats = await feed.drain()
                write_stats = getattr(registry, "set_run_stats", None)
                if write_stats is not None:
                    await asyncio.to_thread(write_stats, run_id, feed_stats.model_dump())
            except Exception:  # a drain failure must never fail a healthy recon run
                logger.warning("inline analysis drain raised for run %s (recon continues)",
                               run_id, exc_info=True)
    finally:
        # #75 D4: on EVERY exit path (clean complete OR stop/kill) tell the analysis
        # consumer "no more chunks" by enqueuing the terminal marker - fire-and-forget,
        # never waiting for analysis. The consumer is owned by the analysis lifecycle
        # module (NOT this task), so recon never cancels it: it drains the FIFO
        # naturally and records its own status. For the inline feed this is a no-op.
        if feed is not None:
            try:
                await feed.signal_end()
            except Exception:
                logger.warning("analysis signal_end raised for run %s (recon continues)",
                               run_id, exc_info=True)
        # feat/async-actor-agents: reap the recon-orchestrator actor (if any) so no
        # orphan task outlives the run - on a clean stop AND on every error path.
        if orchestrator is not None:
            try:
                await orchestrator.stop()
            except Exception:  # teardown must never fail a healthy recon run
                logger.warning("recon-orchestrator stop raised for run %s (recon continues)",
                               run_id, exc_info=True)
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
    # Recon reaches complete the instant its jobs finish - it does NOT wait on
    # analysis (#75 D3). Analysis settles independently on its own run row.
    await asyncio.to_thread(registry.set_run_status, run_id, "complete")
