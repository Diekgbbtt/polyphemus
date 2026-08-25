from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bs4 import BeautifulSoup

from ..models import RawParseResult
from .base import ParserAdapter
from .html_common import clean_title, remove_structural_noise, select_primary_content, to_markdown


class HtmlParser(ParserAdapter):
    name = "html"
    supported_suffixes = frozenset({".html", ".htm"})

    def is_available(self) -> bool:
        return True

    @staticmethod
    def _convert(path: Path) -> tuple[str, str | None, dict[str, str]]:
        html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        root = select_primary_content(soup)
        remove_structural_noise(root, remove_aside=True)
        markdown = to_markdown(root)

        heading = root.find("h1")
        title = clean_title(heading.get_text(" ", strip=True) if heading else None)
        if title is None and soup.title is not None:
            title = clean_title(soup.title.get_text(" ", strip=True))
        metadata = {"source_title": title} if title else {}
        return markdown, title, metadata

    async def parse(self, path: Path) -> RawParseResult:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            markdown, title, metadata = await loop.run_in_executor(
                executor, self._convert, path
            )
        finally:
            try:
                executor.shutdown(wait=True, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=True)

        return RawParseResult(
            parser_name=self.name,
            source_path=str(path),
            title_candidate=title,
            markdown=markdown,
            source_profile="generic",
            native_metadata=metadata,
        )
