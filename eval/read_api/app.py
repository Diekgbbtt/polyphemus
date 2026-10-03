"""The eval read API: a standalone GET-only FastAPI over an injected source (#278).

Three routes, no mutation, no core Polyphemus coupling:

- `GET /snapshot` -> the eval snapshot, straight from the source;
- `GET /health`   -> the source's own health;
- `GET /trials/{target_id}/{target_run_id}/{trial_id}/project-graph` -> the
  immutable historical graph of one materialized Trial.

The app is deliberately ignorant of the storage mechanism: it holds no paths,
no YAML, no store layout, and no projection. It only knows the `SnapshotSource`
contract and asks a factory for one on each request (so configuration is read at
request time, never at import). The global app uses the default filesystem
factory; a test or a future deployment injects its own. Run it with
`uvicorn read_api.app:app` (from the directory that holds `read_api/`).
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .source import (
    HistoricalProjectGraphError,
    SourceFactory,
    SnapshotSourceUnavailable,
    filesystem_source,
)


def create_app(source_factory: SourceFactory = filesystem_source) -> FastAPI:
    """Build the app over `source_factory`.

    Docs are disabled so the surface is exactly the two GETs. The factory runs
    per request, so a fresh, correctly-configured source backs every call.
    """
    app = FastAPI(
        title="Polyphemus eval read API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    def health() -> dict:
        return source_factory().health().as_dict()

    @app.get("/snapshot")
    def snapshot() -> dict:
        try:
            return source_factory().snapshot()
        except SnapshotSourceUnavailable as exc:
            raise HTTPException(
                status_code=503, detail=str(exc) or "snapshot source unavailable"
            ) from exc

    @app.get("/trials/{target_id}/{target_run_id}/{trial_id}/project-graph")
    def project_graph(target_id: str, target_run_id: str, trial_id: str) -> dict:
        try:
            return source_factory().get_project_graph(target_id, target_run_id, trial_id)
        except HistoricalProjectGraphError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
        except SnapshotSourceUnavailable as exc:
            raise HTTPException(
                status_code=503, detail=str(exc) or "project graph source unavailable"
            ) from exc

    return app


app = create_app()
