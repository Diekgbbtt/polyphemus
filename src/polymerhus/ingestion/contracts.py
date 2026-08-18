from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SourceStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    STABILIZING = "STABILIZING"
    PROCESSING = "PROCESSING"
    NORMALIZED = "NORMALIZED"
    INGESTING = "INGESTING"
    AUDITING = "AUDITING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    FAILED_AUDIT = "FAILED_AUDIT"

    def can_transition_to(self, target: "SourceStatus") -> bool:
        return target in _ALLOWED_TRANSITIONS[self]


_ALLOWED_TRANSITIONS: dict[SourceStatus, set[SourceStatus]] = {
    SourceStatus.DISCOVERED: {SourceStatus.STABILIZING, SourceStatus.FAILED},
    SourceStatus.STABILIZING: {SourceStatus.PROCESSING, SourceStatus.FAILED},
    SourceStatus.PROCESSING: {SourceStatus.NORMALIZED, SourceStatus.FAILED},
    SourceStatus.NORMALIZED: {SourceStatus.INGESTING, SourceStatus.FAILED},
    SourceStatus.INGESTING: {SourceStatus.AUDITING, SourceStatus.FAILED},
    SourceStatus.AUDITING: {SourceStatus.PROCESSED, SourceStatus.FAILED, SourceStatus.FAILED_AUDIT},
    SourceStatus.PROCESSED: set(),
    SourceStatus.FAILED: {SourceStatus.PROCESSING},
    SourceStatus.SKIPPED_DUPLICATE: set(),
    SourceStatus.FAILED_AUDIT: set(),
}


class SourceChange(StrEnum):
    NEW = "NEW"
    UNCHANGED = "UNCHANGED"
    UPDATED = "UPDATED"


class SourceRecord(BaseModel):
    source_key: str
    source_kind: Literal["file", "url"]
    source_uri: str
    content_hash: str | None = None
    status: SourceStatus
    parser: str | None = None
    parser_version: str | None = None
    normalization_version: str | None = None
    lightrag_document_id: str | None = None
    normalized_markdown_path: str | None = None
    normalized_json_path: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    source_metadata: dict[str, object] = Field(default_factory=dict)


class SourceClassification(BaseModel):
    change: SourceChange
    status: SourceStatus
    should_ingest: bool


class IngestionError(BaseModel):
    code: str
    message: str
    stage: str


def classify_source(existing: SourceRecord | None, incoming_hash: str) -> SourceClassification:
    if existing is None:
        return SourceClassification(change=SourceChange.NEW, status=SourceStatus.DISCOVERED, should_ingest=True)
    if existing.status == SourceStatus.PROCESSED and existing.content_hash == incoming_hash:
        return SourceClassification(
            change=SourceChange.UNCHANGED,
            status=SourceStatus.SKIPPED_DUPLICATE,
            should_ingest=False,
        )
    if existing.status == SourceStatus.PROCESSED and existing.content_hash != incoming_hash:
        return SourceClassification(change=SourceChange.UPDATED, status=SourceStatus.DISCOVERED, should_ingest=True)
    return SourceClassification(change=SourceChange.NEW, status=SourceStatus.DISCOVERED, should_ingest=True)
