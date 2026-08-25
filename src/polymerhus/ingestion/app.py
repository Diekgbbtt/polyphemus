import logging

from fastapi import FastAPI

from polymerhus.app.clients import pg
from polymerhus.ingestion.routes import router as ingestion_router


logger = logging.getLogger(__name__)

app = FastAPI(title="polyphemus-ingestion")
app.include_router(ingestion_router)


@app.on_event("startup")
async def _startup():
    """Migrate existing PostgreSQL volumes before accepting URL traffic.

    The migration is idempotent and non-destructive. A failure propagates out
    of the startup hook, so the application never becomes ready and the
    Compose healthcheck keeps the service unhealthy.
    """
    logger.info("Applying URL ingestion schema migration at startup")
    pg.apply_url_ingestion_migrations()


@app.get("/health")
async def health():
    return {"status": "ok"}
