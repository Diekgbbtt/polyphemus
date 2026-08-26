from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PreprocessorConfig:
    output_dir: Path
    preferred_pdf_parser: str = "mineru"
    parser_timeout_seconds: float = 120.0
    max_concurrency: int = 2
    source_profile: str = "auto"

    def __post_init__(self) -> None:
        if self.preferred_pdf_parser not in {"mineru", "docling", "pymupdf4llm"}:
            raise ValueError("preferred_pdf_parser must be mineru, docling, or pymupdf4llm")
        if self.source_profile not in {"auto", "wstg", "0xdf", "generic"}:
            raise ValueError("source_profile must be auto, wstg, 0xdf, or generic")
        if self.parser_timeout_seconds <= 0:
            raise ValueError("parser_timeout_seconds must be positive")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
