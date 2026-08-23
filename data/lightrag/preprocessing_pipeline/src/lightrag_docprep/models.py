from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator



_SEMANTIC_METADATA_KEYS = frozenset({
    "preconditionenvironment",
    "technologystack",
    "defensivecontrol",
    "vulnerabilityclass",
    "attackgoal",
    "attackercapability",
    "attacktechnique",
    "payloadpattern",
    "artifact",
    "observablesignal",
    "entities",
    "relationships",
    "relations",
    "embeddings",
    "chunks",
})


def _validate_native_metadata(value: dict[str, Any]) -> dict[str, Any]:
    for key in value:
        if str(key).replace("_", "").replace("-", "").casefold() in _SEMANTIC_METADATA_KEYS:
            raise ValueError(f"semantic metadata key is not allowed in preprocessing: {key}")
    return value


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    FORMULA = "formula"
    CODE = "code"
    IMAGE_TEXT = "image_text"


class RawParseResult(BaseModel):
    parser_name: str
    parser_version: str | None = None
    source_path: str
    title_candidate: str | None = None
    markdown: str
    warnings: list[str] = Field(default_factory=list)
    page_markdown: list[str] | None = None
    source_profile: str | None = None
    native_metadata: dict[str, Any] = Field(default_factory=dict)
    parser_context: dict[str, Any] = Field(default_factory=dict, exclude=True)

    _native_metadata_boundary = field_validator("native_metadata")(_validate_native_metadata)


class ContentBlock(BaseModel):
    kind: BlockKind
    content: str
    page_number: int | None = None


class SectionNode(BaseModel):
    section_id: str
    heading: str
    level: int
    heading_path: list[str]
    blocks: list[ContentBlock] = Field(default_factory=list)


class DocumentModel(BaseModel):
    doc_id: str
    title: str
    source_path: str
    source_type: str
    parser_engine: str
    parser_version: str | None = None
    processed_at: datetime
    warnings: list[str] = Field(default_factory=list)
    source_profile: str | None = None
    native_metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[SectionNode] = Field(default_factory=list)

    _native_metadata_boundary = field_validator("native_metadata")(_validate_native_metadata)
