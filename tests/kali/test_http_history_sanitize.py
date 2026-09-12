"""Model-facing views must never carry raw secrets or bodies."""
from __future__ import annotations

import json

from kali.http_history.models import (
    CaptureContext,
    HttpArtifact,
    NameValue,
    RequestRecord,
    ResponseRecord,
)
from kali.http_history.sanitize import sanitize_artifact, sanitize_summary

_SECRET = "sup3r-s3cr3t-value"


def _artifact() -> HttpArtifact:
    return HttpArtifact(
        artifact_id="http_01J0000000000000000000000A",
        project_id="proj-1",
        capture_context=CaptureContext(exec_id="e1"),
        request=RequestRecord(
            method="POST",
            url="https://target.example/login?token=" + _SECRET,
            headers=[["authorization", f"Bearer {_SECRET}"], ["accept", "application/json"]],
            cookies=[NameValue(name="sid", value=_SECRET)],
            query=[NameValue(name="token", value=_SECRET)],
            body_ref="sha256:abc",
            body_size=10,
        ),
        response=ResponseRecord(
            status=200,
            headers=[["set-cookie", f"sid={_SECRET}; Path=/"]],
            body_ref="sha256:def",
            body_size=5,
        ),
    )


def test_sanitized_artifact_has_no_secret():
    blob = json.dumps(sanitize_artifact(_artifact()))
    assert _SECRET not in blob


def test_sanitized_artifact_keeps_non_secret_headers_and_status():
    view = sanitize_artifact(_artifact())
    assert view["request"]["method"] == "POST"
    assert view["response"]["status"] == 200
    assert ["accept", "application/json"] in view["request"]["headers"]


def test_sanitized_summary_is_a_compact_safe_projection():
    summary = sanitize_summary(_artifact())
    assert summary["artifact_id"] == "http_01J0000000000000000000000A"
    assert summary["method"] == "POST"
    assert summary["status"] == 200
    assert summary["host"] == "target.example"
    assert summary["response_size"] == 5
    assert _SECRET not in json.dumps(summary)


def test_sanitize_never_exposes_body_identity_or_content():
    view = sanitize_artifact(_artifact())
    assert "body_ref" not in json.dumps(view)
