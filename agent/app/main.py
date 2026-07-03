from fastapi import FastAPI
from agent.app.clients import pg, neo4j_client, kali_mcp
from agent.app.llm import validate_llm_config

app = FastAPI(title="polymerhus-agent")

@app.on_event("startup")
async def _startup():
    await pg.ensure_checkpoint_tables()
    neo4j_client.ensure_schema()
    validate_llm_config()

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
