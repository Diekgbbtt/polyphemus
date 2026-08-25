from pathlib import Path
import json
from typing import Any

from pydantic import BaseModel


class DocprepError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class NormalizedDocument(BaseModel):
    output_dir: Path
    markdown_path: Path
    json_path: Path
    parser: str
    warnings: list[str]


def _build_preprocessor(output_root: Path):
    try:
        from lightrag_docprep.config import PreprocessorConfig
        from lightrag_docprep.pipeline import DocumentPreprocessor
    except ModuleNotFoundError as exc:
        raise DocprepError("NORMALIZATION_FAILED", f"lightrag_docprep dependency unavailable: {exc.name}") from exc

    return DocumentPreprocessor(
        PreprocessorConfig(
            output_dir=output_root,
            preferred_pdf_parser="mineru",
            parser_timeout_seconds=120,
            max_concurrency=1,
        )
    )


def _to_normalized_document(result) -> NormalizedDocument:
    if not result.success or result.output_dir is None:
        raise DocprepError("PARSE_FAILED", result.error or "Document preprocessing failed")

    markdown_path = result.output_dir / "document.md"
    json_path = result.output_dir / "document.json"
    if not markdown_path.is_file() or not json_path.is_file():
        raise DocprepError("NORMALIZATION_FAILED", "Docprep did not produce canonical artifacts")

    document_payload = json.loads(json_path.read_text(encoding="utf-8"))
    return NormalizedDocument(
        output_dir=result.output_dir,
        markdown_path=markdown_path,
        json_path=json_path,
        parser=document_payload.get("parser_engine") or "unknown",
        warnings=result.warnings,
    )


async def normalize_document(source_path: Path, *, output_root: Path) -> NormalizedDocument:
    preprocessor = _build_preprocessor(output_root)
    result = await preprocessor.process(Path(source_path))
    return _to_normalized_document(result)


async def normalize_downloaded_artifact(
    source_path: Path,
    *,
    output_root: Path,
    source_identity: str,
    source_type: str,
    native_metadata: dict[str, Any],
) -> NormalizedDocument:
    """Normalize an already-downloaded local artifact through docprep.

    The artifact is handed off to the existing parser router with its explicit
    source identity and download metadata. This adapter performs no network
    access of its own: all bytes are already on the local filesystem.
    """
    preprocessor = _build_preprocessor(output_root)
    result = await preprocessor.process_local(
        Path(source_path),
        source_identity=source_identity,
        source_type=source_type,
        extra_native_metadata=native_metadata,
    )
    return _to_normalized_document(result)
