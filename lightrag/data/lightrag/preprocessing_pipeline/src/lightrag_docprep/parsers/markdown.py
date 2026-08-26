from __future__ import annotations

from pathlib import Path

from ..models import RawParseResult
from .base import ParserAdapter


class MarkdownParser(ParserAdapter):
    name = "markdown"
    supported_suffixes = frozenset({".md", ".markdown", ".txt"})

    def is_available(self) -> bool:
        return True

    @staticmethod
    def _strip_front_matter(text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.splitlines()
        if lines and lines[0].strip() == "---":
            for index in range(1, len(lines)):
                if lines[index].strip() == "---":
                    return "\n".join(lines[index + 1 :]).lstrip("\n")
        return normalized

    async def parse(self, path: Path) -> RawParseResult:
        text = path.read_text(encoding="utf-8", errors="replace")
        return RawParseResult(
            parser_name=self.name,
            source_path=str(path),
            markdown=self._strip_front_matter(text).rstrip(),
            source_profile="generic",
        )
