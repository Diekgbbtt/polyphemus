import asyncio
import logging

from fastapi import FastAPI
from polymerhus.app.logging_config import configure_logging
from polymerhus.app.clients import pg, neo4j_client, kali_mcp
from polymerhus.app.config import config
from polymerhus.app.llm import validate_llm_config
from polymerhus.app.observability import disabled_reason, get_langfuse_callbacks
from polymerhus.project_management.api import router as recon_router
from polymerhus.ingestion.routes import router as ingestion_router
from polymerhus.lightrag.api import router as lightrag_router

# Before anything else: uvicorn configures only its own loggers, so without this
# every application log line in this process is discarded. See logging_config.
configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="polymerhus-agent")
app.include_router(recon_router)
app.include_router(ingestion_router)
app.include_router(lightrag_router)


def log_tracing_status() -> None:
    """Emit a one-time, loud line about whether LLM reasoning is being traced.

    A silent no-op (LANGFUSE_* unset) is exactly what hid the missing reasoning
    trace in the run e55e8626 post-mortem; surface it at boot so operators know
    up front that decision traces will (not) be captured. Best-effort."""
    if get_langfuse_callbacks():
        logger.info("Langfuse tracing enabled - LLM configurator/triager reasoning is traced.")
    else:
        logger.warning(
            "Langfuse tracing disabled (%s) - no LLM reasoning traces will be captured "
            "for this process.", disabled_reason() or "unknown reason"
        )


@app.on_event("startup")
async def _startup():
    # Size up the default thread pool that asyncio.to_thread uses: the recon
    # pipeline offloads every blocking pod graph.invoke AND all sync pg/neo4j
    # calls onto it. The stdlib default (~cpu+4) is far too small for phase
    # fan-out and lets long-held pod threads starve the heartbeat/DB calls,
    # which in turn wedged the API and tripped the reaper (Defect C).
    import concurrent.futures
    asyncio.get_running_loop().set_default_executor(
        concurrent.futures.ThreadPoolExecutor(
            max_workers=config.WORKER_THREADS, thread_name_prefix="recon-worker"
        )
    )
    await pg.ensure_checkpoint_tables()
    pg.ensure_recon_schema()  # additive interface-B columns; idempotent, self-healing
    pg.ensure_hunting_schema()  # #110: hunting-run lifecycle status table
    neo4j_client.ensure_schema()
    neo4j_client.ensure_l1_schema()  # L1 substrate constraints (FR-LCUR)
    validate_llm_config()
    # Open the process-wide pooled checkpointer that backs every stateful agent (#94):
    # the analysis proposers, the concurrent recon pods, and the hunts share it, each on
    # its own SessionAddress thread. Fail-open (in-process fallback when Postgres is absent).
    from polymerhus.app.llm import setup_session_checkpointer
    setup_session_checkpointer()
    # Construct the module control plane (#118/#121): ONE shared worker loop
    # (the asyncio.Runner thread) owns every module task; the manager itself is
    # a plain coordinator on the API thread. Modules register RUNNING and the
    # API routes schedule/cancel through the runtime from here on (§5.1).
    from polymerhus.app.runtime import RuntimeManager
    runtime = RuntimeManager()
    runtime.start()
    runtime.register_module("recon")
    runtime.register_module("analysis")
    # #123: the hunting module registers with a flush hook on the shutdown
    # fan-out (flush the hunting in-memory checkpointer index into the still-open
    # pooled saver, fail-open).
    from polymerhus.attack.hunting.runtime import flush_hunting_checkpointer
    runtime.register_module("hunting", hooks={"flush": flush_hunting_checkpointer})
    app.state.runtime = runtime
    log_tracing_status()
    pg.reap_stale_runs(config.REAP_TTL_SECONDS)  # sweep zombies left by a prior crash
    # #75 D10: the in-memory chunk queue dies with the process, so any analysis run
    # left `draining` by a prior crash/redeploy has no live queue - flip it to
    # `interrupted` (an honest terminal state) rather than leave a zombie row.
    n_interrupted = pg.reconcile_orphaned_analysis_runs()
    if n_interrupted:
        logger.warning("startup: reconciled %d orphaned draining analysis run(s) -> interrupted",
                       n_interrupted)
    # #123: the per-run orchestration actor is in-memory and dies with the
    # process, so any hunting run left `running` at boot has no live engine
    # behind it - flip it to `interrupted` alongside the analysis reconcile.
    n_hunting_interrupted = pg.reconcile_orphaned_hunting_runs()
    if n_hunting_interrupted:
        logger.warning(
            "startup: reconciled %d orphaned running hunting run(s) -> interrupted",
            n_hunting_interrupted,
        )
    app.state.reaper_task = asyncio.create_task(_reaper_loop())


async def _reaper_loop():
    while True:
        await asyncio.sleep(config.REAPER_SWEEP_SECONDS)
        try:
            pg.reap_stale_runs(config.REAP_TTL_SECONDS)
        except Exception:
            logging.getLogger(__name__).warning("reaper sweep failed", exc_info=True)


@app.on_event("shutdown")
async def _shutdown():
    task = getattr(app.state, "reaper_task", None)
    if task:
        task.cancel()
    # The ratified shutdown walk (§5.12, G7c): stop accepting, hard-cancel
    # in-flight runs, flush each module's checkpointer index into the STILL-OPEN
    # #94 pool, close the shared executor, stop the worker loop. THEN close the
    # pool - so the fan-out's flush target is alive for the tail.
    runtime = getattr(app.state, "runtime", None)
    if runtime is not None:
        runtime.shutdown()
    from polymerhus.app.llm import close_session_checkpointer
    close_session_checkpointer()  # close the pooled stateful-session checkpointer

@app.get("/health")
async def health():
    # Observability: capture WHY a backend is down (not just a bare boolean),
    # so a degraded stack is diagnosable from the endpoint alone.
    checks = {"postgres": False, "neo4j": False, "kali_mcp": False}
    errors: dict[str, str] = {}
    try:
        checks["postgres"] = pg.check()
    except Exception as e:  # noqa: BLE001
        errors["postgres"] = f"{type(e).__name__}: {e}"
    try:
        checks["neo4j"] = neo4j_client.check()
    except Exception as e:  # noqa: BLE001
        errors["neo4j"] = f"{type(e).__name__}: {e}"
    try:
        checks["kali_mcp"] = await kali_mcp.check()
    except Exception as e:  # noqa: BLE001
        errors["kali_mcp"] = f"{type(e).__name__}: {e}"
    return {"status": "ok" if all(checks.values()) else "degraded",
            "checks": checks, "errors": errors}
