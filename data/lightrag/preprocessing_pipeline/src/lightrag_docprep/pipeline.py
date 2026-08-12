from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .config import PreprocessorConfig
from .errors import ParserExecutionError, ParserUnavailableError, UnsupportedSourceError
from .exporters import export_document
from .normalizer import normalize_parse_result
from .postprocessors.docling import postprocess_docling_result
from .router import ParserRouter
from .url_fetcher import URLFetchError, URLFetcher


@dataclass(slots=True)
class PreprocessResult:
    source_path: str | Path
    success: bool
    output_dir: Path | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _source_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}:
        return "image"
    return suffix.lstrip(".") or "unknown"


class DocumentPreprocessor:
    def __init__(
        self,
        config: PreprocessorConfig,
        *,
        router: ParserRouter | None = None,
        url_fetcher: URLFetcher | None = None,
    ) -> None:
        self.config = config
        self.router = router or ParserRouter(config)
        self.url_fetcher = url_fetcher or URLFetcher()
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    async def _process_path(
        self,
        source: Path,
        *,
        source_identity: str | None = None,
        extra_native_metadata: dict[str, str | None] | None = None,
    ) -> PreprocessResult:
        display_source: str | Path = source_identity or source
        if not source.is_file():
            return PreprocessResult(source_path=display_source, success=False, error="Source file does not exist")

        try:
            candidates = self.router.candidates(source)
        except UnsupportedSourceError as exc:
            return PreprocessResult(source_path=display_source, success=False, error=str(exc))

        warnings: list[str] = []
        last_error: str | None = None
        for parser in candidates:
            if not parser.is_available():
                warning = f"{parser.name} unavailable; trying fallback"
                warnings.append(warning)
                last_error = warning
                continue
            try:
                raw = await asyncio.wait_for(
                    parser.parse(source),
                    timeout=self.config.parser_timeout_seconds,
                )
            except asyncio.TimeoutError:
                last_error = f"{parser.name} timed out after {self.config.parser_timeout_seconds:g}s"
                warnings.append(last_error)
                continue
            except (ParserUnavailableError, ParserExecutionError) as exc:
                last_error = f"{parser.name} failed: {exc}"
                warnings.append(last_error)
                continue
            except Exception as exc:
                last_error = f"{parser.name} failed: {type(exc).__name__}: {exc}"
                warnings.append(last_error)
                continue

            raw.warnings = [*warnings, *raw.warnings]
            if raw.parser_name == "docling":
                raw = postprocess_docling_result(raw)
            if source_identity is not None:
                raw.source_path = source_identity
            if extra_native_metadata:
                raw.native_metadata = {
                    **raw.native_metadata,
                    **{key: value for key, value in extra_native_metadata.items() if value is not None},
                }
            document = normalize_parse_result(raw, source_type=_source_type(source))
            output_dir = export_document(document, self.config.output_dir)
            return PreprocessResult(
                source_path=display_source,
                success=True,
                output_dir=output_dir,
                warnings=list(document.warnings),
            )

        return PreprocessResult(
            source_path=display_source,
            success=False,
            warnings=warnings,
            error=last_error or "No parser could process the source",
        )

    async def process(self, path: Path) -> PreprocessResult:
        source = Path(path)
        async with self._semaphore:
            return await self._process_path(source)

    async def process_url(self, url: str) -> PreprocessResult:
        async with self._semaphore:
            try:
                async with self.url_fetcher.fetch(url) as fetched:
                    return await self._process_path(
                        fetched.local_path,
                        source_identity=fetched.source_url,
                        extra_native_metadata={
                            "source_url": fetched.source_url,
                            "resolved_url": fetched.resolved_url,
                            "http_content_type": fetched.content_type,
                        },
                    )
            except URLFetchError as exc:
                return PreprocessResult(source_path=url, success=False, error=str(exc))

    async def process_many(self, paths: Sequence[Path]) -> list[PreprocessResult]:
        return list(await asyncio.gather(*(self.process(Path(path)) for path in paths)))
