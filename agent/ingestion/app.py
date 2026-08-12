from fastapi import FastAPI

from agent.ingestion.routes import router as ingestion_router


app = FastAPI(title="polyphemus-ingestion")
app.include_router(ingestion_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
