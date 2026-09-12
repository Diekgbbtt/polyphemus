"""The canonical http-artifact/v1 record preserves the wire truth."""
from __future__ import annotations

from kali.http_history.models import (
    SCHEMA_VERSION,
    CaptureContext,
    HttpArtifact,
    RequestRecord,
    ResponseRecord,
)


def _artifact(**overrides) -> HttpArtifact:
    base = dict(
        artifact_id="http_01J0000000000000000000000A",
        project_id="proj-1",
        capture_context=CaptureContext(
            session_id="s1", run_id="r1", spec_id="spec", variant_ref="v0", exec_id="e1"
        ),
        request=RequestRecord(
            method="POST",
            url="https://target.example/login",
            http_version="HTTP/2",
            headers=[["content-type", "application/json"], ["x-dup", "a"], ["x-dup", "b"]],
            cookies=[{"name": "sid", "value": "abc"}],
            query=[{"name": "q", "value": "1"}],
            form=[],
            body_ref="sha256:deadbeef",
            body_size=42,
            body_encoding="utf-8",
        ),
        response=ResponseRecord(
            status=200,
            reason="OK",
            http_version="HTTP/2",
            headers=[["set-cookie", "sid=abc; Path=/"]],
        ),
        created_at=1234.5,
        schema_version=SCHEMA_VERSION,
    )
    base.update(overrides)
    return HttpArtifact(**base)


def test_schema_version_is_pinned():
    assert SCHEMA_VERSION == "http-artifact/v1"
    assert _artifact().schema_version == "http-artifact/v1"


def test_duplicate_headers_and_order_are_preserved():
    artifact = _artifact()
    assert artifact.request.headers == [
        ("content-type", "application/json"),
        ("x-dup", "a"),
        ("x-dup", "b"),
    ]


def test_missing_response_is_allowed_without_error():
    artifact = _artifact(response=None)
    assert artifact.response is None
    assert artifact.error is None


def test_replay_lineage_fields_default_to_none():
    artifact = _artifact()
    assert artifact.derived_from is None
    assert artifact.replay_kind is None


def test_record_roundtrips_through_json():
    artifact = _artifact()
    blob = artifact.model_dump_json()
    assert HttpArtifact.model_validate_json(blob) == artifact
