"""Model-facing views: no bodies, redacted secrets, and the one summary exception."""
from __future__ import annotations

import json

from kali.http_history.models import (
    CaptureContext,
    HttpArtifact,
    HttpError,
    NameValue,
    RequestRecord,
    ResponseRecord,
)
from kali.http_history.sanitize import (
    SUMMARY_HEADER_VALUE_MAX,
    sanitize_artifact,
    sanitize_summary,
)

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


def test_sanitized_summary_is_the_lean_candidate_projection():
    summary = sanitize_summary(_artifact())
    assert set(summary) == {
        "artifact_id", "method", "url", "status", "request_size", "response_size",
        "request_headers", "response_headers",
    }
    assert summary["artifact_id"] == "http_01J0000000000000000000000A"
    assert summary["method"] == "POST"
    assert summary["status"] == 200
    assert "target.example" in summary["url"]
    assert summary["request_size"] == 10
    assert summary["response_size"] == 5
    assert "capture_state" not in summary
    assert "project_id" not in summary


def test_the_summary_headers_are_lowercased_and_side_bound():
    summary = sanitize_summary(_artifact())

    assert summary["request_headers"] == {
        "authorization": [f"Bearer {_SECRET}"],
    }
    assert summary["response_headers"] == {
        "set-cookie": [f"sid={_SECRET}; Path=/"],
    }
    assert "accept" not in summary["request_headers"]


def test_the_summary_headers_keep_duplicates_in_recorded_order():
    artifact = _artifact().model_copy(update={
        "response": ResponseRecord(status=200, headers=[
            ["Set-Cookie", "a=1; Path=/"],
            ["set-cookie", "b=2; Path=/"],
            ["Content-Type", "text/html"],
        ]),
    })

    headers = sanitize_summary(artifact)["response_headers"]

    assert headers["set-cookie"] == ["a=1; Path=/", "b=2; Path=/"]
    assert headers["content-type"] == ["text/html"]


def test_the_summary_omits_headers_that_are_not_triage_keys():
    artifact = _artifact().model_copy(update={
        "request": RequestRecord(method="GET", url="https://target.example/", headers=[
            ["Vary", "Accept-Encoding"],
            ["Content-Length", "12"],
            ["Date", "Wed, 21 Oct 2026 23:57:19 GMT"],
            ["User-Agent", "polymerhus-recon/jsluice"],
        ]),
        "response": ResponseRecord(status=204, headers=[["Vary", "Origin"]]),
    })

    summary = sanitize_summary(artifact)

    assert "request_headers" not in summary
    assert "response_headers" not in summary


def test_the_summary_keeps_location_and_the_cors_family():
    artifact = _artifact().model_copy(update={
        "response": ResponseRecord(status=302, headers=[
            ["Location", "https://target.example/after"],
            ["Access-Control-Allow-Origin", "https://app.example"],
            ["Content-Security-Policy", "default-src 'self'; script-src 'self'"],
        ]),
    })

    headers = sanitize_summary(artifact)["response_headers"]

    assert headers["location"] == ["https://target.example/after"]
    assert headers["access-control-allow-origin"] == ["https://app.example"]
    assert headers["content-security-policy"] == [
        "default-src 'self'; script-src 'self'"]


def test_the_summary_truncates_a_long_header_value_to_the_cap():
    value = "x" * (SUMMARY_HEADER_VALUE_MAX + 40)
    artifact = _artifact().model_copy(update={
        "response": ResponseRecord(status=200, headers=[["Server", value]]),
    })

    rendered = sanitize_summary(artifact)["response_headers"]["server"][0]

    assert len(rendered) == SUMMARY_HEADER_VALUE_MAX
    assert rendered.endswith("...")


def test_the_summary_renders_secret_headers_verbatim():
    """The operator decision: the summary row is not a redacting boundary.
    The full view still redacts, which the earlier test pins."""
    summary = sanitize_summary(_artifact())
    assert _SECRET in summary["request_headers"]["authorization"][0]
    assert _SECRET in summary["response_headers"]["set-cookie"][0]
    assert "[redacted]" not in json.dumps(
        summary["request_headers"]) + json.dumps(summary["response_headers"])


def test_sanitized_summary_carries_only_sparse_lineage_and_error():
    artifact = _artifact().model_copy(update={
        "derived_from": "http_01J0000000000000000000000P",
        "replay_kind": "mutated",
        "error": HttpError(type="timeout", message="probe timed out"),
    })
    summary = sanitize_summary(artifact)
    assert summary["derived_from"] == "http_01J0000000000000000000000P"
    assert summary["replay_kind"] == "mutated"
    assert summary["error"] == "timeout"

    clean = sanitize_summary(_artifact())
    assert "derived_from" not in clean
    assert "replay_kind" not in clean
    assert "error" not in clean


def test_sanitized_summary_omits_empty_sizes():
    artifact = _artifact().model_copy(update={
        "request": RequestRecord(method="GET", url="https://target.example/"),
        "response": ResponseRecord(status=204),
    })
    summary = sanitize_summary(artifact)
    assert "request_size" not in summary
    assert "response_size" not in summary


def test_sanitize_never_exposes_body_identity_or_content():
    view = sanitize_artifact(_artifact())
    assert "body_ref" not in json.dumps(view)


from kali.http_history.models import CaptureContext, HttpArtifact
from kali.http_history.sanitize import sanitize_artifact


def test_capture_context_is_projected_explicitly():
    artifact = HttpArtifact(
        artifact_id="http_01J0000000000000000000000A",
        project_id="proj-1",
        capture_context=CaptureContext(
            exec_id="e1", session_id="s1", source_ip="172.30.0.2"
        ),
    )
    view = sanitize_artifact(artifact)
    assert set(view["capture_context"]) == {
        "session_id", "run_id", "spec_id", "variant_ref", "exec_id",
        "derived_from", "replay_kind",
    }
    assert "172.30.0.2" not in str(view)
