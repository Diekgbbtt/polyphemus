"""HTTP boundary that receives a QuerySpec and returns a validated answer.

The final Polyphemus receiver endpoint does not exist yet; this route is the
simulation-side seam. It accepts the provisional QuerySpecV1 and returns the
full pipeline record so the caller can inspect retrieval, provenance and
generation metadata alongside the validated bundle.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from polymerhus.lightrag.pipeline import (
    MockMode,
    QueryPipelineResultV1,
    run_query_pipeline,
)
from polymerhus.lightrag.query_spec import QuerySpecV1, R_A, R_B

router = APIRouter(prefix="/lightrag", tags=["lightrag"])


@router.post("/query", response_model=QueryPipelineResultV1)
def query_lightrag(spec: QuerySpecV1, config: str = "R-A") -> QueryPipelineResultV1:
    """Receive a bounded concern, retrieve, generate and validate the answer."""
    if config not in {"R-A", "R-B"}:
        raise HTTPException(status_code=422, detail="config must be R-A or R-B")
    retrieval_config = R_A if config == "R-A" else R_B
    try:
        from polymerhus.app.config import config as app_config

        if app_config.QUERY_PIPELINE_MOCK:
            return run_query_pipeline(
                spec, retrieval_config=retrieval_config, mock=MockMode()
            )
        return run_query_pipeline(spec, retrieval_config=retrieval_config)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"query pipeline failed: {error}"
        ) from error
