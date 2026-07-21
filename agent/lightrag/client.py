from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import httpx

from agent.app.config import config


class LightRAGHttpClient:
    """Small sync client for the LightRAG API server."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = (base_url or config.LIGHTRAG_API_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else config.LIGHTRAG_API_KEY
        self.timeout = timeout if timeout is not None else config.LIGHTRAG_TIMEOUT_SECONDS

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


def _iter_ingestable_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            yield path
