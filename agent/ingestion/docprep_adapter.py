from pathlib import Path
import json

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


async def normalize_document(source_path: Path, *, output_root: Path) -> NormalizedDocument:
    try:
        from lightrag_docprep.config import PreprocessorConfig
        from lightrag_docprep.pipeline import DocumentPreprocessor
    except ModuleNotFoundError as exc:
        raise DocprepError("NORMALIZATION_FAILED", f"lightrag_docprep dependency unavailable: {exc.name}") from exc

    preprocessor = DocumentPreprocessor(
        PreprocessorConfig(
            output_dir=output_root,
            preferred_pdf_parser="mineru",
            parser_timeout_seconds=120,
            max_concurrency=1,
        )
    )
    result = await preprocessor.process(Path(source_path))
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
