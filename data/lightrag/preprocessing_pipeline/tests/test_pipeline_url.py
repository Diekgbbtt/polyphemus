from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lightrag_docprep.config import PreprocessorConfig
from lightrag_docprep.models import RawParseResult
from lightrag_docprep.parsers.base import ParserAdapter
from lightrag_docprep.pipeline import DocumentPreprocessor


@contextmanager
def _server(routes: dict[str, tuple[str, bytes]]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            content_type, body = routes[self.path]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.asyncio
async def test_process_url_reuses_html_parser_and_preserves_web_provenance(tmp_path: Path):
    body = b"<html><head><title>Web Guide</title></head><body><main><h1>Web Guide</h1><p>Useful body.</p></main></body></html>"
    config = PreprocessorConfig(output_dir=tmp_path / "out", source_profile="generic")
    processor = DocumentPreprocessor(config)

    with _server({"/article": ("text/html; charset=utf-8", body)}) as base:
        url = f"{base}/article"
        result = await processor.process_url(url)

    assert result.success is True
    data = json.loads((result.output_dir / "document.json").read_text())
    markdown = (result.output_dir / "document.md").read_text()
    assert "Useful body." in markdown
    assert data["source_path"] == url
    assert data["source_type"] == "html"
    assert data["parser_engine"] == "html"
    assert data["native_metadata"]["source_url"] == url
    assert data["native_metadata"]["resolved_url"] == url
    assert data["native_metadata"]["http_content_type"] == "text/html"


class _PdfStub(ParserAdapter):
    name = "pdfstub"
    supported_suffixes = frozenset({".pdf"})

    def is_available(self) -> bool:
        return True

    async def parse(self, path: Path) -> RawParseResult:
        assert path.suffix == ".pdf"
        return RawParseResult(
            parser_name=self.name,
            source_path=str(path),
            title_candidate="PDF Stub",
            markdown="# PDF Stub\n\nParsed PDF body.",
        )


class _StubRouter:
    def __init__(self):
        self.parser = _PdfStub()

    def candidates(self, path: Path):
        return [self.parser]


@pytest.mark.asyncio
async def test_process_url_sniffs_extensionless_pdf_before_existing_router(tmp_path: Path):
    config = PreprocessorConfig(output_dir=tmp_path / "out", source_profile="generic")
    processor = DocumentPreprocessor(config, router=_StubRouter())

    with _server({"/download?id=1": ("application/octet-stream", b"%PDF-1.7\nbody")}) as base:
        url = f"{base}/download?id=1"
        result = await processor.process_url(url)

    assert result.success is True
    data = json.loads((result.output_dir / "document.json").read_text())
    assert data["source_path"] == url
    assert data["source_type"] == "pdf"
    assert data["parser_engine"] == "pdfstub"
