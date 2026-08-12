import pytest

from agent.ingestion.contracts import (
    IngestionError,
    SourceRecord,
    SourceStatus,
    classify_source,
)
from agent.ingestion.source_identity import (
    SourceValidationError,
    build_source_key,
    content_sha256,
    validate_source_path,
)


def test_content_sha256_is_stable_for_same_bytes(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_bytes(b"# Title\n\nsame content\n")
    second.write_bytes(b"# Title\n\nsame content\n")

    assert content_sha256(first) == content_sha256(second)


def test_source_key_is_deterministic_and_relative_to_allowed_root(tmp_path):
    root = tmp_path / "ingestion"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    source = inbox / "Example File.md"
    source.write_text("# Example\n", encoding="utf-8")

    first = build_source_key(source, allowed_root=root)
    second = build_source_key(source, allowed_root=root)

    assert first == second
    assert first == "file:inbox/Example File.md"


def test_validate_source_path_rejects_paths_outside_allowed_root(tmp_path):
    root = tmp_path / "ingestion"
    outside = tmp_path / "outside.md"
    root.mkdir()
    outside.write_text("# Outside\n", encoding="utf-8")

    with pytest.raises(SourceValidationError) as exc:
        validate_source_path(outside, allowed_root=root)

    assert exc.value.code == "SOURCE_OUTSIDE_ALLOWED_ROOT"


def test_source_status_allows_only_defined_transitions():
    assert SourceStatus.DISCOVERED.can_transition_to(SourceStatus.STABILIZING)
    assert SourceStatus.STABILIZING.can_transition_to(SourceStatus.PROCESSING)
    assert SourceStatus.PROCESSING.can_transition_to(SourceStatus.NORMALIZED)
    assert SourceStatus.NORMALIZED.can_transition_to(SourceStatus.INGESTING)
    assert SourceStatus.INGESTING.can_transition_to(SourceStatus.AUDITING)
    assert SourceStatus.AUDITING.can_transition_to(SourceStatus.PROCESSED)
    assert SourceStatus.PROCESSING.can_transition_to(SourceStatus.FAILED)
    assert SourceStatus.FAILED.can_transition_to(SourceStatus.PROCESSING)

    assert not SourceStatus.DISCOVERED.can_transition_to(SourceStatus.PROCESSED)
    assert not SourceStatus.PROCESSED.can_transition_to(SourceStatus.PROCESSING)


def test_classify_identical_processed_source_as_skipped_duplicate():
    existing = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="abc123",
        status=SourceStatus.PROCESSED,
    )

    result = classify_source(existing, incoming_hash="abc123")

    assert result.status == SourceStatus.SKIPPED_DUPLICATE
    assert result.should_ingest is False


def test_ingestion_error_serializes_stable_code_and_safe_message():
    error = IngestionError(
        code="LIGHTRAG_TIMEOUT",
        message="LightRAG did not finish before timeout",
        stage="INGESTING",
    )

    assert error.model_dump() == {
        "code": "LIGHTRAG_TIMEOUT",
        "message": "LightRAG did not finish before timeout",
        "stage": "INGESTING",
    }
