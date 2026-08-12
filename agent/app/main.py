import asyncio
import logging

from fastapi import FastAPI
from agent.app.clients import pg, neo4j_client, kali_mcp
from agent.app.config import config
from agent.app.llm import validate_llm_config
from agent.app.observability import disabled_reason, get_langfuse_callbacks
from agent.app.routes import router as recon_router
from agent.ingestion.routes import router as ingestion_router

logger = logging.getLogger(__name__)

app = FastAPI(title="polymerhus-agent")
app.include_router(recon_router)
app.include_router(ingestion_router)


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
    neo4j_client.ensure_schema()
    validate_llm_config()
    log_tracing_status()
    pg.reap_stale_runs(config.REAP_TTL_SECONDS)  # sweep zombies left by a prior crash
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
