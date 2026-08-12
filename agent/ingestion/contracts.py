from enum import StrEnum

from pydantic import BaseModel


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

    def can_transition_to(self, target: "SourceStatus") -> bool:
        return target in _ALLOWED_TRANSITIONS[self]


_ALLOWED_TRANSITIONS: dict[SourceStatus, set[SourceStatus]] = {
    SourceStatus.DISCOVERED: {SourceStatus.STABILIZING, SourceStatus.FAILED},
    SourceStatus.STABILIZING: {SourceStatus.PROCESSING, SourceStatus.FAILED},
    SourceStatus.PROCESSING: {SourceStatus.NORMALIZED, SourceStatus.FAILED},
    SourceStatus.NORMALIZED: {SourceStatus.INGESTING, SourceStatus.FAILED},
    SourceStatus.INGESTING: {SourceStatus.AUDITING, SourceStatus.FAILED},
    SourceStatus.AUDITING: {SourceStatus.PROCESSED, SourceStatus.FAILED},
    SourceStatus.PROCESSED: set(),
    SourceStatus.FAILED: {SourceStatus.PROCESSING},
    SourceStatus.SKIPPED_DUPLICATE: set(),
}


class SourceRecord(BaseModel):
    source_key: str
    source_kind: str
    source_uri: str
    content_hash: str
    status: SourceStatus


class SourceClassification(BaseModel):
    status: SourceStatus
    should_ingest: bool


class IngestionError(BaseModel):
    code: str
    message: str
    stage: str


def classify_source(existing: SourceRecord | None, incoming_hash: str) -> SourceClassification:
    if existing is None:
        return SourceClassification(status=SourceStatus.DISCOVERED, should_ingest=True)
    if existing.status == SourceStatus.PROCESSED and existing.content_hash == incoming_hash:
        return SourceClassification(status=SourceStatus.SKIPPED_DUPLICATE, should_ingest=False)
    return SourceClassification(status=SourceStatus.DISCOVERED, should_ingest=True)
