from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from ..errors import ParserExecutionError, ParserUnavailableError
from ..models import RawParseResult
from .base import ParserAdapter


def _label_value(item: Any) -> str:
    label = getattr(item, "label", "")
    value = getattr(label, "value", label)
    return str(value).casefold()


def _first_page_number(item: Any) -> int | None:
    for prov in getattr(item, "prov", []) or []:
        page_no = getattr(prov, "page_no", None)
        if isinstance(page_no, int) and page_no > 0:
            return page_no
    return None


def _num_pages(document: Any) -> int:
    value = getattr(document, "num_pages", 0)
    if callable(value):
        value = value()
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _collect_native_structure(document: Any) -> tuple[list[str] | None, dict[str, Any]]:
    footnotes: list[dict[str, Any]] = []
    iterate_items = getattr(document, "iterate_items", None)
    if callable(iterate_items):
        for item, _level in iterate_items():
            if _label_value(item) != "footnote":
                continue
            text = str(getattr(item, "text", "") or "").strip()
            if not text:
                continue
            footnotes.append({"text": text, "page_number": _first_page_number(item)})

    pages = _num_pages(document)
    page_markdown: list[str] | None = None
    if pages:
        page_markdown = [
            document.export_to_markdown(page_no=page_no)
            for page_no in range(1, pages + 1)
        ]

    return page_markdown, {"footnotes": footnotes}


class DoclingParser(ParserAdapter):
    name = "docling"
    supported_suffixes = frozenset({
        ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm",
        ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp",
    })

    def is_available(self) -> bool:
        return find_spec("docling") is not None

    @staticmethod
    def _convert(path: Path) -> tuple[str, list[str] | None, dict[str, Any]]:
        from docling.document_converter import DocumentConverter

        result = DocumentConverter().convert(str(path))
        document = result.document
        markdown = document.export_to_markdown()
        page_markdown, parser_context = _collect_native_structure(document)
        return markdown, page_markdown, parser_context

    @staticmethod
    def _version() -> str | None:
        try:
            return version("docling")
        except PackageNotFoundError:
            return None

    async def parse(self, path: Path) -> RawParseResult:
        if not self.is_available():
            raise ParserUnavailableError("Docling is not installed")
        try:
            markdown, page_markdown, parser_context = await asyncio.to_thread(self._convert, path)
        except Exception as exc:  # adapter boundary: normalize third-party failures
            raise ParserExecutionError(f"Docling failed: {exc}") from exc
        return RawParseResult(
            parser_name=self.name,
            parser_version=self._version(),
            source_path=str(path),
            markdown=markdown,
            page_markdown=page_markdown,
            source_profile="generic",
            parser_context=parser_context,
        )
