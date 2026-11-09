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
    BODY_TEXT_MAX,
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


_RAW_URL = ("https://user:pass@target.example/login?token=" + _SECRET
            + "&q=a%20b&flag#frag")


def _artifact_with_raw_url() -> HttpArtifact:
    artifact = _artifact()
    return artifact.model_copy(update={
        "request": artifact.request.model_copy(update={"url": _RAW_URL}),
    })


def test_the_summary_url_is_the_recorded_url_verbatim():
    """The row is the string the filter matched on. `sanitize_url` redacts,
    so it must not run on the summary: a model that filters on a query value
    would otherwise get rows that do not display it."""
    summary = sanitize_summary(_artifact_with_raw_url())

    assert summary["url"] == _RAW_URL
    assert _SECRET in summary["url"]
    assert "user:pass@" in summary["url"]


def test_the_full_view_still_strips_userinfo_and_redacts_the_query():
    url = sanitize_artifact(_artifact_with_raw_url())["request"]["url"]

    assert "user:pass@" not in url
    assert "token=[redacted]" in url
    assert _SECRET not in url


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


def _captured_artifact() -> HttpArtifact:
    return HttpArtifact(
        artifact_id="http_01J0000000000000000000000B",
        project_id="proj-1",
        capture_context=CaptureContext(exec_id="e1"),
        request=RequestRecord(
            method="POST",
            url="https://target.example/login",
            headers=[["content-type", "application/x-www-form-urlencoded"]],
            body_ref="sha256:req",
            body_size=42,
            body_encoding="utf-8",
            capture_state="captured",
        ),
        response=ResponseRecord(
            status=200,
            headers=[["content-type", "text/html; charset=utf-8"]],
            body_ref="sha256:res",
            body_size=50,
            body_encoding="utf-8",
            capture_state="captured",
        ),
    )


def test_a_captured_text_body_is_rendered_and_redacted():
    bodies = {
        "sha256:req": b"username=admin&password=" + _SECRET.encode(),
        "sha256:res": (
            b"<html><title>Welcome</title>"
            b"<script>var token=\"" + _SECRET.encode() + b"\";</script></html>"
        ),
    }
    view = sanitize_artifact(_captured_artifact(), body_loader=bodies.get)

    assert "username=admin" in view["request"]["body"]["text"]
    assert "password=[redacted]" in view["request"]["body"]["text"]
    assert "Welcome" in view["response"]["body"]["text"]
    assert "token=\"[redacted]\"" in view["response"]["body"]["text"]
    assert _SECRET not in json.dumps(view)
    assert view["response"]["body"]["truncated"] is False


def test_a_gzip_response_body_is_decompressed_before_rendering():
    import gzip

    raw = gzip.compress(b"<html><body>compressed welcome</body></html>")
    artifact = _captured_artifact().model_copy(update={
        "response": _captured_artifact().response.model_copy(update={
            "headers": [
                ["content-type", "text/html; charset=utf-8"],
                ["content-encoding", "gzip"],
            ],
            "body_ref": "sha256:gz",
            "body_size": len(raw),
            "body_encoding": "binary",
        }),
    })
    view = sanitize_artifact(artifact, body_loader={"sha256:gz": raw}.get)
    assert "compressed welcome" in view["response"]["body"]["text"]


def test_a_large_body_is_capped_and_marked_truncated():
    raw = b"a" * (BODY_TEXT_MAX + 100)
    artifact = _captured_artifact().model_copy(update={
        "response": _captured_artifact().response.model_copy(update={
            "headers": [["content-type", "text/plain; charset=utf-8"]],
            "body_ref": "sha256:big",
            "body_size": len(raw),
        }),
    })
    view = sanitize_artifact(artifact, body_loader={"sha256:big": raw}.get)
    assert len(view["response"]["body"]["text"]) == BODY_TEXT_MAX
    assert view["response"]["body"]["truncated"] is True


def test_a_binary_body_is_not_rendered():
    artifact = _captured_artifact().model_copy(update={
        "response": _captured_artifact().response.model_copy(update={
            "body_ref": "sha256:bin",
            "body_size": 3,
            "body_encoding": "binary",
        }),
    })
    view = sanitize_artifact(
        artifact, body_loader={"sha256:bin": b"\x00\x01\x02"}.get)
    assert view["response"]["body"]["text"] is None
    assert "binary" in (view["response"]["body"].get("note") or "").lower()


def test_an_omitted_body_is_not_rendered():
    artifact = _captured_artifact().model_copy(update={
        "response": _captured_artifact().response.model_copy(update={
            "capture_state": "omitted",
            "capture_reason": "body exceeds capture limit",
            "body_ref": None,
        }),
    })
    view = sanitize_artifact(artifact, body_loader=lambda ref: b"never")
    assert view["response"]["body"]["text"] is None
    assert "omitted" in (view["response"]["body"].get("note") or "").lower()


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
