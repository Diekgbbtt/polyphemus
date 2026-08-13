import pytest

from agent.ingestion.contracts import (
    IngestionError,
    SourceChange,
    SourceRecord,
    SourceStatus,
    classify_source,
)
from agent.ingestion.source_identity import (
    SourceValidationError,
    build_source_key,
    build_url_source_key,
    canonicalize_url,
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
    assert result.change == SourceChange.UNCHANGED


def test_classify_missing_source_as_new():
    result = classify_source(None, incoming_hash="abc123")

    assert result.status == SourceStatus.DISCOVERED
    assert result.should_ingest is True
    assert result.change == SourceChange.NEW


def test_classify_changed_processed_source_as_updated():
    existing = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
    )

    result = classify_source(existing, incoming_hash="new-hash")

    assert result.status == SourceStatus.DISCOVERED
    assert result.should_ingest is True
    assert result.change == SourceChange.UPDATED


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


def test_failed_audit_is_terminal():
    assert SourceStatus.FAILED_AUDIT.can_transition_to(SourceStatus.PROCESSED) is False
    assert SourceStatus.FAILED_AUDIT.can_transition_to(SourceStatus.PROCESSING) is False
    assert SourceStatus.FAILED_AUDIT.can_transition_to(SourceStatus.FAILED) is False
    assert SourceStatus.FAILED_AUDIT.can_transition_to(SourceStatus.SKIPPED_DUPLICATE) is False


def test_auditing_to_failed_audit_allowed():
    assert SourceStatus.AUDITING.can_transition_to(SourceStatus.FAILED_AUDIT)
    assert SourceStatus.AUDITING.can_transition_to(SourceStatus.PROCESSED)
    assert SourceStatus.AUDITING.can_transition_to(SourceStatus.FAILED)


def test_invalid_transitions_remain_rejected():
    assert not SourceStatus.PROCESSED.can_transition_to(SourceStatus.FAILED_AUDIT)
    assert not SourceStatus.DISCOVERED.can_transition_to(SourceStatus.PROCESSED)
    assert not SourceStatus.SKIPPED_DUPLICATE.can_transition_to(SourceStatus.PROCESSED)


# ---------------------------------------------------------------------------
# Milestone 4 URL identity
# ---------------------------------------------------------------------------

def test_canonicalize_url_lowercases_scheme_host_and_defaults_path():
    assert canonicalize_url("HTTP://Example.COM") == "http://example.com/"


def test_canonicalize_url_removes_default_port():
    assert canonicalize_url("https://example.com:443/a?b=1") == "https://example.com/a?b=1"


def test_canonicalize_url_preserves_query_order_and_separators():
    assert canonicalize_url("http://example.com/?a=1&b=2&a=3") == "http://example.com/?a=1&b=2&a=3"


def test_canonicalize_url_removes_fragment():
    assert canonicalize_url("http://example.com/path#section") == "http://example.com/path"


def test_canonicalize_url_normalizes_dot_segments():
    assert canonicalize_url("http://example.com/a/b/../c/./d") == "http://example.com/a/c/d"


def test_canonicalize_url_preserves_duplicate_slashes():
    assert canonicalize_url("http://example.com//a//b") == "http://example.com//a//b"


def test_canonicalize_url_percent_encoding_normalized_uppercase_and_decodes_unreserved():
    assert canonicalize_url("http://example.com/%7euser/%2f") == "http://example.com/~user/%2F"


def test_canonicalize_url_rejects_leading_trailing_whitespace():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("  http://example.com  ")
    assert exc.value.code == "URL_INVALID"


def test_canonicalize_url_rejects_unsupported_scheme():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("ftp://example.com")
    assert exc.value.code == "URL_UNSUPPORTED_SCHEME"


def test_canonicalize_url_rejects_credentials():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("http://user:pass@example.com")
    assert exc.value.code == "URL_CREDENTIALS_FORBIDDEN"


def test_canonicalize_url_rejects_nondefault_port():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("http://example.com:8080")
    assert exc.value.code == "URL_PORT_FORBIDDEN"


def test_canonicalize_url_rejects_invalid_host():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("http://-bad-.com")
    assert exc.value.code == "URL_HOST_INVALID"


def test_canonicalize_url_idna_success():
    assert canonicalize_url("http://münchen.de") == "http://xn--mnchen-3ya.de/"


def test_canonicalize_url_idna_failure():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("http://\ud800")
    assert exc.value.code == "URL_HOST_INVALID"


def test_canonicalize_url_ipv4_normalized():
    assert canonicalize_url("http://192.168.1.1:80/") == "http://192.168.1.1/"


def test_canonicalize_url_rejects_leading_zero_ipv4():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("http://192.168.001.001/")
    assert exc.value.code == "URL_HOST_INVALID"


def test_canonicalize_url_ipv6_normalized_and_bracketed():
    assert canonicalize_url("http://[2001:0DB8:0:0:0:0:0:1]/") == "http://[2001:db8::1]/"


def test_canonicalize_url_rejects_unbracketed_ipv6():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("http://2001:db8::1/")
    assert exc.value.code == "URL_INVALID"


def test_canonicalize_url_rejects_invalid_percent_encoding():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("http://example.com/%zz")
    assert exc.value.code == "URL_INVALID"


def test_canonicalize_url_idempotent():
    original = "HTTP://Example.COM:80/a/./b/../c?q=1&q=2#frag"
    once = canonicalize_url(original)
    twice = canonicalize_url(once)
    assert once == twice == "http://example.com/a/c?q=1&q=2"


def test_canonicalize_url_preserves_query_raw_escapes_and_order():
    assert canonicalize_url("http://example.com/path?x=%7e&x=%2f;z=1") == "http://example.com/path?x=%7e&x=%2f;z=1"


def test_canonicalize_url_retains_empty_query_marker():
    assert canonicalize_url("http://example.com/path?") == "http://example.com/path?"


def test_canonicalize_url_does_not_add_empty_query_marker_without_question():
    assert canonicalize_url("http://example.com/path") == "http://example.com/path"


@pytest.mark.parametrize("host", ["127.1", "2130706433", "0x7f000001"])
def test_canonicalize_url_rejects_alternative_ipv4_notations(host):
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url(f"http://{host}/")
    assert exc.value.code == "URL_HOST_INVALID"


@pytest.mark.parametrize("host", ["0177.0.0.1", "0x7f.0.0.1", "192.168.001.001"])
def test_canonicalize_url_rejects_legacy_ipv4_dotted_forms(host):
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url(f"http://{host}/")
    assert exc.value.code == "URL_HOST_INVALID"


def test_canonicalize_url_rejects_dotted_hex_ipv4_notation():
    with pytest.raises(SourceValidationError) as exc:
        canonicalize_url("http://0x7f.0.0.1/")
    assert exc.value.code == "URL_HOST_INVALID"


def test_canonicalize_url_accepts_regular_dns_name_with_digits():
    assert canonicalize_url("http://example123.com") == "http://example123.com/"


def test_canonicalize_url_accepts_dns_numeric_hosts_that_are_not_legacy_ipv4():
    assert canonicalize_url("http://1.2.3.999/") == "http://1.2.3.999/"
    assert canonicalize_url("http://1.2.3.4.5/") == "http://1.2.3.4.5/"


def test_build_url_source_key_stable_and_exactly_url_prefix():
    assert build_url_source_key("HTTP://Example.COM/a") == "url:http://example.com/a"
    assert build_url_source_key("http://example.com/a") == "url:http://example.com/a"
    assert build_url_source_key("http://example.com/a") != build_url_source_key("http://example.com/a/")
