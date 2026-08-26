from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .markdown_structure import parse_markdown_structure
from .models import DocumentModel, RawParseResult
from .page_provenance import assign_block_page_numbers


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _source_identity_and_fallback_title(source_path: str) -> tuple[str, str]:
    parsed = urlparse(source_path)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        basename = Path(unquote(parsed.path)).name
        fallback = Path(basename).stem if basename else parsed.netloc
        return source_path, fallback or parsed.netloc
    source = Path(source_path)
    return str(source.resolve(strict=False)), source.stem


def normalize_parse_result(raw: RawParseResult, *, source_type: str) -> DocumentModel:
    markdown = _normalize_text(raw.markdown)
    sections = parse_markdown_structure(markdown)
    if raw.page_markdown:
        assign_block_page_numbers(sections, raw.page_markdown)
    identity, fallback_title = _source_identity_and_fallback_title(raw.source_path)
    digest = hashlib.sha256(f"{identity}\n{markdown}".encode("utf-8")).hexdigest()[:20]
    first_heading = next((s.heading for s in sections if s.heading), None)
    title = (raw.title_candidate or first_heading or fallback_title).strip()

    return DocumentModel(
        doc_id=digest,
        title=title,
        source_path=raw.source_path,
        source_type=source_type,
        parser_engine=raw.parser_name,
        parser_version=raw.parser_version,
        processed_at=datetime.now(timezone.utc),
        warnings=list(raw.warnings),
        source_profile=raw.source_profile,
        native_metadata=dict(raw.native_metadata),
        sections=sections,
    )
