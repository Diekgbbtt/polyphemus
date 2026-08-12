from pathlib import Path
from time import sleep
from typing import Any

import httpx
from pydantic import BaseModel


class LightRAGAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class LightRAGIngestionResult(BaseModel):
    track_id: str
    document_id: str | None
    status: str


class LightRAGIngestionAdapter:
    def __init__(
        self,
        *,
        client,
        poll_interval_seconds: float = 2.0,
        max_upload_attempts: int = 3,
        max_poll_attempts: int = 60,
    ):
        self.client = client
        self.poll_interval_seconds = poll_interval_seconds
        self.max_upload_attempts = max_upload_attempts
        self.max_poll_attempts = max_poll_attempts

    def ingest_markdown(self, markdown_path: Path, *, source_key: str) -> LightRAGIngestionResult:
        del source_key
        upload_response = self._upload_with_retry(Path(markdown_path))
        track_id = _extract_track_id(upload_response)
        for _ in range(self.max_poll_attempts):
            status_response = self.client.track_status(track_id)
            status = _normalize_status(status_response)
            if status == "processed":
                return LightRAGIngestionResult(
                    track_id=track_id,
                    document_id=_extract_document_id(status_response),
                    status=status,
                )
            if status == "failed":
                raise LightRAGAdapterError(
                    "LIGHTRAG_INGESTION_FAILED",
                    str(status_response.get("error") or "LightRAG ingestion failed"),
                    retryable=False,
                )
            if self.poll_interval_seconds > 0:
                sleep(self.poll_interval_seconds)
        raise LightRAGAdapterError(
            "LIGHTRAG_TIMEOUT",
            "LightRAG did not reach a terminal status before timeout",
            retryable=True,
        )

    def _upload_with_retry(self, markdown_path: Path) -> dict[str, Any]:
        last_error: LightRAGAdapterError | None = None
        for _ in range(self.max_upload_attempts):
            try:
                return self.client.upload_file(markdown_path)
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code >= 500
                last_error = LightRAGAdapterError(
                    "LIGHTRAG_INGESTION_FAILED",
                    f"LightRAG upload failed with HTTP {exc.response.status_code}",
                    retryable=retryable,
                )
                if not retryable:
                    raise last_error from exc
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = LightRAGAdapterError(
                    "LIGHTRAG_UNAVAILABLE",
                    "LightRAG is unavailable",
                    retryable=True,
                )
            if self.poll_interval_seconds > 0:
                sleep(self.poll_interval_seconds)
        if last_error is not None:
            raise last_error
        raise LightRAGAdapterError("LIGHTRAG_UNAVAILABLE", "LightRAG upload did not run", retryable=True)


def _extract_track_id(payload: dict[str, Any]) -> str:
    track_id = payload.get("track_id") or payload.get("id")
    if not track_id:
        raise LightRAGAdapterError(
            "LIGHTRAG_INGESTION_FAILED",
            "LightRAG upload response did not include track_id",
            retryable=False,
        )
    return str(track_id)


def _extract_document_id(payload: dict[str, Any]) -> str | None:
    document_id = payload.get("document_id") or payload.get("doc_id") or payload.get("id")
    return str(document_id) if document_id else None


def _normalize_status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").lower()
    if status in {"processed", "completed", "complete", "done"}:
        return "processed"
    if status in {"failed", "error"}:
        return "failed"
    return status or "processing"
