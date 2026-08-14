from pathlib import Path
from time import sleep
from typing import Any
import hashlib
import shutil

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
        upload_path = _upload_named_copy(Path(markdown_path), source_key)
        try:
            upload_response = self._upload_with_retry(upload_path)
        finally:
            upload_path.unlink(missing_ok=True)
        track_id = _extract_track_id(upload_response)
        for _ in range(self.max_poll_attempts):
            status_response = self.client.track_status(track_id)
            status = _normalize_status(status_response)
            if status == "processed":
                document_id = _extract_document_id(status_response)
                if isinstance(document_id, str):
                    document_id = document_id.strip()
                if not document_id:
                    raise LightRAGAdapterError(
                        "LIGHTRAG_DOCUMENT_ID_MISSING",
                        "LightRAG did not return a valid document ID",
                        retryable=False,
                    )
                return LightRAGIngestionResult(
                    track_id=track_id,
                    document_id=document_id,
                    status=status,
                )
            if status == "failed":
                raise LightRAGAdapterError(
                    "LIGHTRAG_INGESTION_FAILED",
                    _extract_error_message(status_response),
                    retryable=False,
                )
            if self.poll_interval_seconds > 0:
                sleep(self.poll_interval_seconds)
        raise LightRAGAdapterError(
            "LIGHTRAG_TIMEOUT",
            "LightRAG did not reach a terminal status before timeout",
            retryable=True,
        )

    def delete_document(self, document_id: str, *, delete_llm_cache: bool = True) -> dict[str, Any]:
        try:
            return self.client.delete_document(document_id, delete_llm_cache=delete_llm_cache)
        except httpx.HTTPStatusError as exc:
            raise LightRAGAdapterError(
                "LIGHTRAG_DELETE_FAILED",
                f"LightRAG document delete failed with HTTP {exc.response.status_code}",
                retryable=exc.response.status_code >= 500,
            ) from exc
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise LightRAGAdapterError(
                "LIGHTRAG_UNAVAILABLE",
                "LightRAG is unavailable",
                retryable=True,
            ) from exc

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


def _upload_named_copy(markdown_path: Path, source_key: str) -> Path:
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:16]
    upload_path = markdown_path.with_name(f"source-{digest}.md")
    shutil.copyfile(markdown_path, upload_path)
    return upload_path


def _extract_document_id(payload: dict[str, Any]) -> str | None:
    document_id = payload.get("document_id") or payload.get("doc_id") or payload.get("id")
    if not document_id:
        documents = payload.get("documents")
        if isinstance(documents, list) and documents:
            first_document = documents[0]
            if isinstance(first_document, dict):
                document_id = first_document.get("id") or first_document.get("document_id") or first_document.get("doc_id")
    return document_id if isinstance(document_id, str) else None


def _normalize_status(payload: dict[str, Any]) -> str:
    document_status = _documents_status(payload)
    if document_status:
        return document_status
    status = str(payload.get("status") or "").lower()
    if status in {"processed", "completed", "complete", "done"}:
        return "processed"
    if status in {"failed", "error"}:
        return "failed"
    return status or "processing"


def _documents_status(payload: dict[str, Any]) -> str | None:
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        return None

    statuses = [
        str(document.get("status") or "").lower()
        for document in documents
        if isinstance(document, dict)
    ]
    if any(status in {"failed", "error"} for status in statuses):
        return "failed"
    if statuses and all(status in {"processed", "completed", "complete", "done"} for status in statuses):
        return "processed"
    return "processing"


def _extract_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error") or payload.get("error_msg")
    if error:
        return str(error)
    documents = payload.get("documents")
    if isinstance(documents, list):
        for document in documents:
            if not isinstance(document, dict):
                continue
            document_error = document.get("error") or document.get("error_msg")
            if document_error:
                return str(document_error)
    return "LightRAG ingestion failed"
