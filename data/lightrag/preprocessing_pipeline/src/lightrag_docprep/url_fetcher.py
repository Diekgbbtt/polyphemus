from __future__ import annotations

import tempfile
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import unquote, urlparse

import httpx

from .router import SUPPORTED_SOURCE_SUFFIXES


DEFAULT_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_FETCH_TIMEOUT_SECONDS = 30.0


class URLFetchError(Exception):
    """Raised when a URL cannot be materialized as a supported source document."""


@dataclass(frozen=True, slots=True)
class FetchedURLSource:
    local_path: Path
    source_url: str
    resolved_url: str
    content_type: str | None


_MIME_SUFFIXES = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}
_GENERIC_CONTENT_TYPES = {"", "application/octet-stream", "binary/octet-stream", "application/binary"}


def _normalize_content_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.split(";", 1)[0].strip().lower()
    return normalized or None


def _supported_suffix_from_name(name: str | None) -> str | None:
    if not name:
        return None
    suffix = Path(unquote(name)).suffix.lower()
    return suffix if suffix in SUPPORTED_SOURCE_SUFFIXES else None


def _filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    message = Message()
    message["Content-Disposition"] = value
    return message.get_filename()


def _sniff_zip_office(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    if "word/document.xml" in names or any(name.startswith("word/") for name in names):
        return ".docx"
    if "ppt/presentation.xml" in names or any(name.startswith("ppt/") for name in names):
        return ".pptx"
    if "xl/workbook.xml" in names or any(name.startswith("xl/") for name in names):
        return ".xlsx"
    return None


def _sniff_suffix(path: Path) -> str | None:
    try:
        head = path.read_bytes()[:8192]
    except OSError:
        return None
    if head.startswith(b"%PDF-"):
        return ".pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if head.startswith(b"BM"):
        return ".bmp"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head.startswith(b"PK\x03\x04"):
        office = _sniff_zip_office(path)
        if office:
            return office
    text_probe = head.lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    if text_probe.startswith(b"<!doctype html") or text_probe.startswith(b"<html"):
        return ".html"
    return None


def _detect_suffix(
    *,
    path: Path,
    content_type: str | None,
    content_disposition: str | None,
    resolved_url: str,
    source_url: str,
) -> str | None:
    if content_type and content_type not in _GENERIC_CONTENT_TYPES:
        mapped = _MIME_SUFFIXES.get(content_type)
        if mapped:
            return mapped

    disposition_suffix = _supported_suffix_from_name(_filename_from_content_disposition(content_disposition))
    if disposition_suffix:
        return disposition_suffix

    for url in (resolved_url, source_url):
        suffix = _supported_suffix_from_name(Path(urlparse(url).path).name)
        if suffix:
            return suffix

    return _sniff_suffix(path)


class URLFetcher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
    ) -> None:
        if max_download_bytes <= 0:
            raise ValueError("max_download_bytes must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._client = client
        self.max_download_bytes = max_download_bytes
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise URLFetchError("URL scheme must be http or https")
        if not parsed.netloc:
            raise URLFetchError("URL must include a host")

    @asynccontextmanager
    async def fetch(self, url: str) -> AsyncIterator[FetchedURLSource]:
        self._validate_url(url)
        with tempfile.TemporaryDirectory(prefix="lightrag-docprep-url-") as temp_dir:
            raw_path = Path(temp_dir) / "source.download"
            owns_client = self._client is None
            client = self._client or httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "lightrag-docprep/0.3.4"},
            )
            try:
                try:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        content_length = response.headers.get("Content-Length")
                        if content_length and content_length.isdigit() and int(content_length) > self.max_download_bytes:
                            raise URLFetchError(
                                f"Download exceeds maximum download size of {self.max_download_bytes} bytes"
                            )
                        total = 0
                        with raw_path.open("wb") as handle:
                            async for chunk in response.aiter_bytes():
                                total += len(chunk)
                                if total > self.max_download_bytes:
                                    raise URLFetchError(
                                        f"Download exceeds maximum download size of {self.max_download_bytes} bytes"
                                    )
                                handle.write(chunk)

                        content_type = _normalize_content_type(response.headers.get("Content-Type"))
                        resolved_url = str(response.url)
                        suffix = _detect_suffix(
                            path=raw_path,
                            content_type=content_type,
                            content_disposition=response.headers.get("Content-Disposition"),
                            resolved_url=resolved_url,
                            source_url=url,
                        )
                except URLFetchError:
                    raise
                except httpx.HTTPError as exc:
                    raise URLFetchError(f"HTTP fetch failed: {exc}") from exc

                if suffix is None:
                    raise URLFetchError(
                        f"Could not detect a supported document type for {url}"
                    )
                local_path = raw_path.with_suffix(suffix)
                raw_path.replace(local_path)
                yield FetchedURLSource(
                    local_path=local_path,
                    source_url=url,
                    resolved_url=resolved_url,
                    content_type=content_type,
                )
            finally:
                if owns_client:
                    await client.aclose()
