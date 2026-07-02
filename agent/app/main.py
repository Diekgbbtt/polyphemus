from fastapi import FastAPI
from agent.app.clients import pg, neo4j_client, kali_mcp

app = FastAPI(title="polymerhus-agent")

@app.on_event("startup")
async def _startup():
    await pg.ensure_checkpoint_tables()
    neo4j_client.ensure_schema()

@app.get("/health")
async def health():
    checks = {"postgres": False, "neo4j": False, "kali_mcp": False}
    try:
        checks["postgres"] = pg.check()
    except Exception:  # noqa: BLE001
        pass
    try:
        checks["neo4j"] = neo4j_client.check()
    except Exception:  # noqa: BLE001
        pass
    try:
        checks["kali_mcp"] = await kali_mcp.check()
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks}
