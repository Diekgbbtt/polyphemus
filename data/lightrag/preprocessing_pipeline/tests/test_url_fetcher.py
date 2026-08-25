from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from lightrag_docprep.url_fetcher import URLFetchError, URLFetcher


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.mark.asyncio
async def test_fetch_rejects_non_http_scheme():
    fetcher = URLFetcher()
    with pytest.raises(URLFetchError, match="http or https"):
        async with fetcher.fetch("file:///tmp/report.pdf"):
            pass


@pytest.mark.asyncio
async def test_fetch_detects_html_from_content_type_and_cleans_temp_file():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, text="<html><body>Hello</body></html>")

    async with _client(handler) as client:
        fetcher = URLFetcher(client=client)
        async with fetcher.fetch("https://example.test/article?id=3") as fetched:
            assert fetched.local_path.suffix == ".html"
            assert fetched.local_path.read_text() == "<html><body>Hello</body></html>"
            assert fetched.source_url == "https://example.test/article?id=3"
            assert fetched.resolved_url == "https://example.test/article?id=3"
            assert fetched.content_type == "text/html"
            temp_path = fetched.local_path
        assert not temp_path.exists()


@pytest.mark.asyncio
async def test_fetch_uses_content_disposition_filename_when_content_type_is_generic():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment; filename="guide.pdf"',
            },
            content=b"%PDF-1.7\nbody",
        )

    async with _client(handler) as client:
        async with URLFetcher(client=client).fetch("https://example.test/download?id=4") as fetched:
            assert fetched.local_path.suffix == ".pdf"


@pytest.mark.asyncio
async def test_fetch_sniffs_extensionless_pdf_when_headers_are_generic():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "application/octet-stream"}, content=b"%PDF-1.7\nbody")

    async with _client(handler) as client:
        async with URLFetcher(client=client).fetch("https://example.test/resource") as fetched:
            assert fetched.local_path.suffix == ".pdf"


@pytest.mark.asyncio
async def test_fetch_identifies_docx_from_zip_package_signature():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types><Override PartName="/word/document.xml"/></Types>')
        archive.writestr("word/document.xml", "<document/>")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "application/octet-stream"}, content=buffer.getvalue())

    async with _client(handler) as client:
        async with URLFetcher(client=client).fetch("https://example.test/resource") as fetched:
            assert fetched.local_path.suffix == ".docx"


@pytest.mark.asyncio
async def test_fetch_rejects_download_over_size_limit():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"0123456789")

    async with _client(handler) as client:
        fetcher = URLFetcher(client=client, max_download_bytes=5)
        with pytest.raises(URLFetchError, match="maximum download size"):
            async with fetcher.fetch("https://example.test/large"):
                pass
