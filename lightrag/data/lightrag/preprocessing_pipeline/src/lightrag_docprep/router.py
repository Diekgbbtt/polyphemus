from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path
from typing import Iterable

from .config import PreprocessorConfig
from .errors import UnsupportedSourceError
from .parsers.base import ParserAdapter

_HINT_RE = re.compile(r"\.\[(mineru|docling|pymupdf4llm)\](?=\.[^.]+$)", re.IGNORECASE)
_WSTG_MARKER_RE = re.compile(r"\bWSTG-[A-Z]{4}-\d{2}", re.IGNORECASE)

SUPPORTED_SOURCE_SUFFIXES = frozenset({
    ".md", ".markdown", ".html", ".htm", ".pdf", ".docx", ".pptx", ".xlsx",
    ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp", ".txt",
})

_PARSER_SPECS: tuple[tuple[str, str], ...] = (
    ("wstg", "WstgParser"),
    ("oxdf", "OxdfParser"),
    ("markdown", "MarkdownParser"),
    ("html", "HtmlParser"),
    ("mineru", "MinerUParser"),
    ("docling", "DoclingParser"),
    ("pymupdf4llm", "PyMuPDF4LLMParser"),
)


def _default_parsers() -> list[ParserAdapter]:
    parsers: list[ParserAdapter] = []
    for module_name, class_name in _PARSER_SPECS:
        try:
            module = import_module(f".parsers.{module_name}", __package__)
        except ModuleNotFoundError:
            continue
        parsers.append(getattr(module, class_name)())
    return parsers


class ParserRouter:
    def __init__(
        self,
        config: PreprocessorConfig,
        parsers: Iterable[ParserAdapter] | None = None,
    ) -> None:
        self.config = config
        default = _default_parsers()
        self._parsers = {parser.name: parser for parser in (list(parsers) if parsers is not None else default)}

    def _get(self, names: list[str]) -> list[ParserAdapter]:
        return [self._parsers[name] for name in names if name in self._parsers]

    @staticmethod
    def _read_probe(path: Path, limit: int = 65536) -> str:
        if not path.is_file():
            return ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                return handle.read(limit)
        except OSError:
            return ""

    def _resolved_profile(self, path: Path) -> str:
        configured = self.config.source_profile
        if configured != "auto":
            return configured

        suffix = path.suffix.lower()
        lower_parts = [part.lower() for part in path.parts]
        if suffix in {".md", ".markdown"}:
            if any("wstg" in part for part in lower_parts):
                return "wstg"
            if any(re.match(r"\d{2}-(?:information|configuration|identity|authentication|authorization|session|input_|testing_for|business_|client-side|api_)", part, re.I) for part in path.parts):
                return "wstg"
            if _WSTG_MARKER_RE.search(self._read_probe(path)):
                return "wstg"
        if suffix in {".html", ".htm"}:
            if any(part == "0xdf" or part.startswith("0xdf") for part in lower_parts):
                return "0xdf"
            probe = self._read_probe(path).lower()
            if "0xdf hacks stuff" in probe or "0xdf.gitlab.io" in probe:
                return "0xdf"
        return "generic"

    def candidates(self, path: Path) -> list[ParserAdapter]:
        suffix = path.suffix.lower()
        profile = self._resolved_profile(path)

        if profile == "wstg" and suffix not in {".md", ".markdown"}:
            raise UnsupportedSourceError("WSTG profile supports Markdown sources only")
        if profile == "0xdf" and suffix not in {".html", ".htm"}:
            raise UnsupportedSourceError("0xdf profile supports HTML sources only")

        if suffix in {".md", ".markdown"}:
            names = ["wstg", "markdown"] if profile == "wstg" else ["markdown"]
        elif suffix == ".txt":
            names = ["markdown"]
        elif suffix in {".html", ".htm"}:
            names = ["0xdf", "html", "docling"] if profile == "0xdf" else ["html", "docling"]
        elif suffix == ".pdf":
            names = [self.config.preferred_pdf_parser, "mineru", "docling", "pymupdf4llm"]
        elif suffix in {".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}:
            names = ["docling", "mineru"]
        elif suffix == ".webp":
            names = ["docling"]
        else:
            raise UnsupportedSourceError(f"Unsupported source type: {suffix or '<none>'}")

        deduped = list(dict.fromkeys(names))
        hint_match = _HINT_RE.search(path.name)
        if hint_match:
            hinted = hint_match.group(1).lower()
            parser = self._parsers.get(hinted)
            if parser is not None and parser.supports(path):
                deduped = [hinted] + [name for name in deduped if name != hinted]

        candidates = self._get(deduped)
        if not candidates:
            raise UnsupportedSourceError(f"No configured parser supports {path}")
        return candidates
