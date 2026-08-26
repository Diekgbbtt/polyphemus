from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path

from ..errors import ParserExecutionError, ParserUnavailableError
from ..models import RawParseResult
from .base import ParserAdapter


class PyMuPDF4LLMParser(ParserAdapter):
    name = "pymupdf4llm"
    supported_suffixes = frozenset({".pdf"})

    def is_available(self) -> bool:
        return find_spec("pymupdf4llm") is not None

    @staticmethod
    def _convert(path: Path) -> str:
        import lightrag.data.lightrag.preprocessing_pipeline.src.lightrag_docprep.parsers.pymupdf4llm as pymupdf4llm

        return pymupdf4llm.to_markdown(
            str(path),
            header=False,
            footer=False,
            write_images=False,
            embed_images=False,
            page_chunks=False,
        )

    @staticmethod
    def _version() -> str | None:
        try:
            return version("pymupdf4llm")
        except PackageNotFoundError:
            return None

    async def parse(self, path: Path) -> RawParseResult:
        if not self.is_available():
            raise ParserUnavailableError("PyMuPDF4LLM is not installed")
        try:
            markdown = await asyncio.to_thread(self._convert, path)
        except Exception as exc:
            raise ParserExecutionError(f"PyMuPDF4LLM failed: {exc}") from exc
        return RawParseResult(
            parser_name=self.name,
            parser_version=self._version(),
            source_path=str(path),
            markdown=markdown,
            source_profile="generic",
        )
