"""Source-aware document preprocessing for later LightRAG ingestion."""

__version__ = "0.3.4"

from .config import PreprocessorConfig
from .models import BlockKind, ContentBlock, DocumentModel, RawParseResult, SectionNode
from .normalizer import normalize_parse_result
from .pipeline import DocumentPreprocessor, PreprocessResult

__all__ = [
    "BlockKind",
    "ContentBlock",
    "DocumentModel",
    "DocumentPreprocessor",
    "PreprocessResult",
    "PreprocessorConfig",
    "RawParseResult",
    "SectionNode",
    "normalize_parse_result",
]
