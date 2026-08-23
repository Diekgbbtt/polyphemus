from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from .config import PreprocessorConfig
from .pipeline import DocumentPreprocessor
from .router import SUPPORTED_SOURCE_SUFFIXES


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lightrag-docprep",
        description="Normalize local files or web URLs for later LightRAG ingestion.",
    )
    parser.add_argument("sources", nargs="+")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("normalized"),
        help="Output root directory (default: ./normalized).",
    )
    parser.add_argument(
        "--profile",
        choices=["auto", "wstg", "0xdf", "generic"],
        default="auto",
        help="Source-aware preprocessing profile. Auto detects WSTG and 0xdf conservatively.",
    )
    parser.add_argument(
        "--preferred-pdf-parser",
        choices=["mineru", "docling", "pymupdf4llm"],
        default="mineru",
    )
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _expand_sources(sources: Sequence[str]) -> list[str | Path]:
    expanded: list[str | Path] = []
    for source in sources:
        if _is_url(source):
            expanded.append(source)
            continue
        path = Path(source)
        if path.is_dir():
            expanded.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file()
                and not child.name.startswith(".")
                and child.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
            )
        else:
            expanded.append(path)
    return list(dict.fromkeys(expanded))


async def _run(args: argparse.Namespace) -> int:
    config = PreprocessorConfig(
        output_dir=args.output,
        preferred_pdf_parser=args.preferred_pdf_parser,
        parser_timeout_seconds=args.timeout,
        max_concurrency=args.max_concurrency,
        source_profile=args.profile,
    )
    sources = _expand_sources(args.sources)
    if not sources:
        print("ERROR no supported source files or URLs found")
        return 1

    processor = DocumentPreprocessor(config)
    tasks = [
        processor.process_url(source) if isinstance(source, str) and _is_url(source) else processor.process(Path(source))
        for source in sources
    ]
    results = list(await asyncio.gather(*tasks))

    all_success = True
    for result in results:
        if result.success:
            print(f"OK    {result.source_path} -> {result.output_dir}")
        else:
            all_success = False
            print(f"ERROR {result.source_path} -> {result.error}")
            for warning in result.warnings:
                print(f"WARN  {warning}")
    return 0 if all_success else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
