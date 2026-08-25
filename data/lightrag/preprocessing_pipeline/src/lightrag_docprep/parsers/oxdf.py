from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from ..models import RawParseResult
from .base import ParserAdapter
from .html_common import clean_title, remove_structural_noise, select_primary_content, to_markdown


class OxdfParser(ParserAdapter):
    name = "0xdf"
    supported_suffixes = frozenset({".html", ".htm"})

    def is_available(self) -> bool:
        return True

    @staticmethod
    def _manifest_metadata(path: Path) -> dict[str, Any]:
        manifest_path = path.parent / ".manifest.json"
        if not manifest_path.is_file():
            return {}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        for entry in manifest.get("writeups", []):
            source_path = Path(entry.get("source_path", ""))
            if source_path == path or source_path.name == path.name:
                return {
                    "canonical_url": entry.get("url"),
                    "source_title": entry.get("title"),
                    "publication_date": entry.get("date"),
                    "tags": entry.get("tags") or [],
                    "sha256": entry.get("sha256"),
                    "fetched_at": entry.get("fetched_at"),
                }
        return {}

    @classmethod
    def _convert(cls, path: Path) -> tuple[str, str, dict[str, Any]]:
        source = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(source, "html.parser")

        tags = [tag.get_text(" ", strip=True) for tag in soup.select("a.post-tag, .post-tag")]
        tags = list(dict.fromkeys(tag for tag in tags if tag))

        title_node = soup.select_one("h1.post-title") or soup.find("h1")
        title = clean_title(title_node.get_text(" ", strip=True) if title_node else None)
        if title is None and soup.title is not None:
            title = clean_title(soup.title.get_text(" ", strip=True))
        if title:
            title = re.sub(r"\s+\|\s+0xdf.*$", "", title, flags=re.I).strip()
        title = title or path.stem.replace("-", " ").replace("_", " ").title()

        canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
        canonical_url = canonical.get("href") if canonical else None
        published = soup.find("time", attrs={"datetime": True})
        publication_date = published.get("datetime") if published else None
        if publication_date is None:
            meta = soup.find("meta", attrs={"property": "article:published_time"})
            publication_date = meta.get("content") if meta else None

        root = select_primary_content(
            soup,
            selectors=("article", "main", ".post-content", ".entry-content", ".content"),
        )
        remove_structural_noise(root, remove_aside=True)
        for selector in (".post-tags", ".tags", ".toc", "#toc", ".table-of-contents"):
            for node in root.select(selector):
                node.decompose()

        markdown = to_markdown(root)
        metadata: dict[str, Any] = {
            "source_title": title,
            "canonical_url": canonical_url,
            "publication_date": publication_date,
            "tags": tags,
        }
        manifest_metadata = cls._manifest_metadata(path)
        for key, value in manifest_metadata.items():
            if value not in (None, [], ""):
                metadata[key] = value
        return markdown, title, metadata

    async def parse(self, path: Path) -> RawParseResult:
        markdown, title, metadata = await asyncio.to_thread(self._convert, path)
        return RawParseResult(
            parser_name=self.name,
            source_path=str(path),
            title_candidate=title,
            markdown=markdown,
            source_profile="0xdf",
            native_metadata=metadata,
        )
