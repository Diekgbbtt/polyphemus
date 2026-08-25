from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from polymerhus.ingestion.service import IngestionService


router = APIRouter(prefix="/v1/ingestions", tags=["ingestions"])


class IngestionRequest(BaseModel):
    source_kind: str
    source_uri: str


class IngestionCreated(BaseModel):
    job_id: str
    source_key: str
    status: str


def get_ingestion_service() -> IngestionService:
    return IngestionService.from_config()


@router.post("", response_model=IngestionCreated)
async def create_ingestion(request: IngestionRequest, background_tasks: BackgroundTasks):
    service = get_ingestion_service()
    try:
        result = service.submit(source_kind=request.source_kind, source_uri=request.source_uri)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("run_in_background", True):
        if request.source_kind == "url":
            background_tasks.add_task(
                service.process_job,
                job_id=result["job_id"],
                requested_url=request.source_uri,
            )
        else:
            background_tasks.add_task(service.process_job, result["job_id"])
    return {
        "job_id": result["job_id"],
        "source_key": result["source_key"],
        "status": str(result["status"]),
    }


@router.get("/{job_id}")
async def get_ingestion(job_id: str):
    job = get_ingestion_service().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ingestion job not found")
    return job
