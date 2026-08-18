from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import httpx


class LightRAGHttpClient:
    """Small sync client for the LightRAG API server."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        defaults = _lightrag_defaults()
        self.base_url = (base_url or defaults["base_url"]).rstrip("/")
        self.api_key = api_key if api_key is not None else str(defaults["api_key"])
        self.timeout = (
            timeout if timeout is not None else float(defaults["timeout_seconds"])
        )

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"X-API-Key": self.api_key}

    def _raise_for_status(self, response: httpx.Response) -> dict:
        response.raise_for_status()
        return response.json()

    def health(self) -> dict:
        response = httpx.get(
            f"{self.base_url}/health",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def insert_text(self, text: str, *, file_source: str = "manual.txt") -> dict:
        response = httpx.post(
            f"{self.base_url}/documents/text",
            headers=self._headers(),
            json={"text": text, "file_source": file_source},
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def upload_file(self, source_path: str | Path) -> dict:
        path = Path(source_path)
        with path.open("rb") as handle:
            response = httpx.post(
                f"{self.base_url}/documents/upload",
                headers=self._headers(),
                files={"file": (path.name, handle)},
                timeout=self.timeout,
            )
        return self._raise_for_status(response)

    def delete_all_documents(self) -> dict:
        response = httpx.delete(
            f"{self.base_url}/documents",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def clear_cache(self) -> dict:
        response = httpx.post(
            f"{self.base_url}/documents/clear_cache",
            headers=self._headers(),
            json={},
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def status_counts(self) -> dict:
        response = httpx.get(
            f"{self.base_url}/documents/status_counts",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def paginated_documents(
        self,
        *,
        page: int = 1,
        page_size: int = 200,
        sort_field: str = "file_path",
        sort_direction: str = "asc",
        status_filters: list[str] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "sort_field": sort_field,
            "sort_direction": sort_direction,
        }
        if status_filters is not None:
            payload["status_filters"] = status_filters
        response = httpx.post(
            f"{self.base_url}/documents/paginated",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def pipeline_status(self) -> dict:
        response = httpx.get(
            f"{self.base_url}/documents/pipeline_status",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def cancel_pipeline(self) -> dict:
        response = httpx.post(
            f"{self.base_url}/documents/cancel_pipeline",
            headers=self._headers(),
            json={},
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def reprocess_failed(self) -> dict:
        response = httpx.post(
            f"{self.base_url}/documents/reprocess_failed",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def delete_entity(self, entity_name: str) -> dict:
        response = httpx.request(
            "DELETE",
            f"{self.base_url}/documents/delete_entity",
            headers=self._headers(),
            json={"entity_name": entity_name},
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def delete_document(
        self,
        doc_id: str,
        *,
        delete_file: bool = False,
        delete_llm_cache: bool = False,
    ) -> dict:
        response = httpx.request(
            "DELETE",
            f"{self.base_url}/documents/delete_document",
            headers=self._headers(),
            json={
                "doc_ids": [doc_id],
                "delete_file": delete_file,
                "delete_llm_cache": delete_llm_cache,
            },
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def ingest_source(self, source_path: str | Path) -> dict:
        path = Path(source_path)
        if path.is_dir():
            return {
                "uploaded": [
                    {"source_path": str(child), "response": self.upload_file(child)}
                    for child in _iter_ingestable_files(path)
                ]
            }
        return {"uploaded": [{"source_path": str(path), "response": self.upload_file(path)}]}

    def scan_documents(self) -> dict:
        response = httpx.post(
            f"{self.base_url}/documents/scan",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def track_status(self, track_id: str) -> dict:
        response = httpx.get(
            f"{self.base_url}/documents/track_status/{track_id}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def query(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        include_references: bool = True,
        include_chunk_content: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        payload = {
            "query": query,
            "mode": mode,
            "include_references": include_references,
            "include_chunk_content": include_chunk_content,
        }
        if extra:
            payload.update(extra)
        response = httpx.post(
            f"{self.base_url}/query",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        return self._raise_for_status(response)

    def query_data(self, payload: dict) -> dict:
        """Context-only retrieval. No generation, inspectable evidence only."""
        response = httpx.post(
            f"{self.base_url}/query/data",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        return self._raise_for_status(response)


def _iter_ingestable_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            yield path


def _lightrag_defaults() -> dict[str, str | float]:
    try:
        from polymerhus.app.config import config
    except KeyError:
        return {
            "base_url": "http://lightrag:9621",
            "writeup_url": "http://lightrag-writeups:9621",
            "api_key": "",
            "timeout_seconds": 30.0,
        }
    return {
        "base_url": config.LIGHTRAG_BASE_API_URL,
        "writeup_url": config.LIGHTRAG_WRITEUP_API_URL,
        "api_key": config.LIGHTRAG_API_KEY,
        "timeout_seconds": config.LIGHTRAG_TIMEOUT_SECONDS,
    }


def build_lightrag_clients() -> dict[str, LightRAGHttpClient]:
    defaults = _lightrag_defaults()
    return {
        "base": LightRAGHttpClient(str(defaults["base_url"])),
        "writeups": LightRAGHttpClient(str(defaults["writeup_url"])),
    }
