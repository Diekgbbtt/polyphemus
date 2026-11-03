"""Seam under test: CDP flow normalization and the HTTP-history batch client.

Spec: `docs/design/steel-crawl-spec.md` sections 10.1, 10.2, 10.3, and 12;
seam 9 of `docs/design/steel-crawl-implementation-plan.md` section 3.

The normalizer is the one place a captured flow becomes an
``http-artifact/v1`` record. The content id is deterministic over the request
and response truth; the client batches at most 100 artifacts or 8 MiB and
retries from its persisted cursor. No test needs a running edge: the HTTP seam
is injected.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import pytest

from polymerhus.recon.crawl.steel.capture.flow import Flow
from polymerhus.recon.crawl.steel.capture.history import (
    CaptureContext,
    HistoryClient,
    HistoryIngestError,
    RequestRecord,
    content_id,
    normalize_cdp_flow,
)

BODY = b'{"items":["alpha","beta"],"page":2}'
BODY_SHA = hashlib.sha256(BODY).hexdigest()


def flow(**overrides: Any) -> Flow:
    payload: dict[str, Any] = {
        "request_id": "1000.1",
        "page_id": "page_1",
        "action_id": "act_1",
        "attribution": "action",
        "method": "GET",
        "url": "https://example.test/api/items?page=2",
        "request_headers": {"Accept": "application/json"},
        "resource_type": "XHR",
        "initiator": {"type": "script", "scriptId": "10"},
        "frame_id": "FRAME-1",
        "status": 200,
        "response_headers": {
            "Content-Type": "application/json",
            "Date": "Mon, 02 Nov 2026 10:00:00 GMT",
        },
        "mime_type": "application/json",
        "connection": "keep-alive",
        "encoded_data_length": len(BODY),
        "response_body": BODY,
        "response_body_sha256": BODY_SHA,
        "body_original_size": len(BODY),
        "http_version": "http/1.1",
        "received_at": 1762000000.5,
        "finished": True,
    }
    payload.update(overrides)
    return Flow(**payload)


def context() -> CaptureContext:
    return CaptureContext(
        session_id="session-1",
        run_id="run-1",
        spec_id="spec-1",
        variant_ref="v0",
        exec_id="exec-1",
    )


def test_the_normalizer_maps_a_cdp_flow_to_the_http_artifact_contract():
    artifact, bodies = normalize_cdp_flow(
        flow(), project_id="proj-1", capture_context=context(), now=1762000001.0
    )

    assert artifact.schema_version == "http-artifact/v1"
    assert artifact.project_id == "proj-1"
    assert artifact.capture_context.run_id == "run-1"
    assert artifact.request.method == "GET"
    assert artifact.request.url == "https://example.test/api/items?page=2"
    assert artifact.request.headers == [("Accept", "application/json")]
    assert [(q.name, q.value) for q in artifact.request.query] == [("page", "2")]
    assert artifact.response is not None
    assert artifact.response.status == 200
    assert artifact.response.headers[0] == (
        "Content-Type",
        "application/json",
    )
    assert artifact.response.body_ref == f"sha256:{BODY_SHA}"
    assert artifact.response.body_hash == BODY_SHA
    assert artifact.response.body_size == len(BODY)
    assert artifact.response.capture_state == "captured"
    assert bodies[f"sha256:{BODY_SHA}"] == BODY
    assert artifact.request.http_version == "http/1.1"
    assert artifact.connection.protocol == "http"
    assert artifact.connection.websocket is False
    assert artifact.error is None
    assert artifact.created_at == 1762000001.0

    # The local record is the canonical contract: the Kali edge model validates
    # the same JSON without a translation layer.
    from kali.http_history.models import HttpArtifact as KaliArtifact

    KaliArtifact.model_validate(artifact.model_dump(mode="json"))


def test_the_normalizer_keeps_the_url_cap_fact():
    """The URL cap is a capture fact. A capped flow must carry the flag and the
    original length into the artifact; a silent field drop would make the edge
    store a clipped URL as if it were the real one."""
    long_url = "https://example.test/" + "a" * 3000
    artifact, _ = normalize_cdp_flow(
        flow(url=long_url, url_truncated=True, url_original_length=len(long_url)),
        project_id="proj-1",
        capture_context=context(),
    )

    assert artifact.request.url_truncated is True
    assert artifact.request.url_original_length == len(long_url)


def test_the_local_and_kali_request_records_agree_on_every_field():
    """The normalizer builds the local record; the edge validates the Kali
    record. A field added on one side only is silently dropped by pydantic's
    default extra=ignore, so the two field sets must be identical."""
    from kali.http_history.models import RequestRecord as KaliRequestRecord

    local = set(RequestRecord.model_fields)
    kali = set(KaliRequestRecord.model_fields)
    assert local == kali, {
        "local_only": sorted(local - kali),
        "kali_only": sorted(kali - local),
    }


def test_the_content_id_is_deterministic_and_ignores_volatile_headers():
    base = dict(
        project="proj-1",
        method="GET",
        url="https://Example.test/api/items?page=2",
        request_headers=[("accept", "application/json")],
        request_body_sha256=None,
        status=200,
        response_headers=[("content-type", "application/json")],
        response_body_sha256=BODY_SHA,
    )
    first = content_id(**base)
    second = content_id(**base)
    assert first == second
    assert first.startswith("http_")
    assert len(first) == len("http_") + 26

    volatile = dict(
        base,
        response_headers=[
            ("content-type", "application/json"),
            ("date", "Mon, 02 Nov 2026 10:00:00 GMT"),
        ],
    )
    assert content_id(**volatile) == first

    changed_header = dict(
        base, response_headers=[("content-type", "text/plain")]
    )
    assert content_id(**changed_header) != first

    changed_body = dict(base, response_body_sha256="0" * 64)
    assert content_id(**changed_body) != first


def test_a_replay_keeps_the_caller_provided_id_and_lineage():
    artifact, _ = normalize_cdp_flow(
        flow(),
        project_id="proj-1",
        capture_context=context(),
        artifact_id="http_BASELINE",
        derived_from="http_ORIGINAL",
        replay_kind="mutated",
    )

    assert artifact.artifact_id == "http_BASELINE"
    assert artifact.derived_from == "http_ORIGINAL"
    assert artifact.replay_kind == "mutated"


class FakeEdge:
    """A fake edge: records each payload and returns the aggregate response."""

    def __init__(self, fail_first: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_first = fail_first

    def __call__(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        if self._fail_first:
            self._fail_first = False
            raise ConnectionError("edge is down")
        count = len(payload["artifacts"])
        return {
            "created": count,
            "duplicates": 0,
            "rejected": 0,
            "errors": [],
        }


def test_the_history_client_batches_by_count_and_payload_size():
    edge = FakeEdge()
    client = HistoryClient(
        "http://edge.example.test:8001", "token-1", http_fn=edge, max_artifacts=2
    )
    artifacts = [
        normalize_cdp_flow(
            flow(request_id=f"r{index}"), project_id="proj-1", capture_context=context()
        )
        for index in range(3)
    ]

    result = client.ingest("proj-1", "run-1", artifacts)

    assert len(edge.calls) == 2
    assert [len(call["payload"]["artifacts"]) for call in edge.calls] == [2, 1]
    assert edge.calls[0]["url"] == "http://edge.example.test:8001/v1/ingest"
    assert edge.calls[0]["headers"]["Authorization"] == "Bearer token-1"
    assert edge.calls[0]["payload"]["project_id"] == "proj-1"
    assert edge.calls[0]["payload"]["run_id"] == "run-1"
    assert result.created == 3
    assert result.duplicates == 0
    assert result.rejected == 0


def test_the_history_client_retries_from_the_failed_batch():
    edge = FakeEdge(fail_first=True)
    client = HistoryClient(
        "http://edge.example.test:8001", "token-1", http_fn=edge, max_artifacts=2
    )
    artifacts = [
        normalize_cdp_flow(
            flow(request_id=f"r{index}"), project_id="proj-1", capture_context=context()
        )
        for index in range(2)
    ]

    result = client.ingest("proj-1", "run-1", artifacts)

    assert len(edge.calls) == 2
    assert len(edge.calls[0]["payload"]["artifacts"]) == 2
    assert len(edge.calls[1]["payload"]["artifacts"]) == 2
    assert result.created == 2
    assert result.retries == 1


def test_the_bodies_are_base64_in_the_payload():
    edge = FakeEdge()
    client = HistoryClient(
        "http://edge.example.test:8001", "token-1", http_fn=edge, max_artifacts=10
    )
    artifacts = [
        normalize_cdp_flow(
            flow(), project_id="proj-1", capture_context=context()
        )
    ]

    client.ingest("proj-1", "run-1", artifacts)

    body = edge.calls[0]["payload"]["bodies"][0]
    assert body["sha256"] == BODY_SHA
    assert body["encoding"] == "base64"
    assert base64.b64decode(body["data"]) == BODY


def test_a_failed_flush_raises_the_typed_failure():
    def edge(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        raise ConnectionError("edge is down")

    client = HistoryClient("http://edge.example.test:8001", "token-1", http_fn=edge)
    artifacts = [
        normalize_cdp_flow(
            flow(), project_id="proj-1", capture_context=context()
        )
    ]

    with pytest.raises(HistoryIngestError) as excinfo:
        client.ingest("proj-1", "run-1", artifacts)

    assert excinfo.value.code == "http_history_flush_failed"


def test_the_request_body_is_projected_as_a_form_and_a_body_reference():
    artifact, bodies = normalize_cdp_flow(
        flow(
            method="POST",
            request_headers={"Content-Type": "application/x-www-form-urlencoded"},
            request_body="user=alice&pass=hunter2",
        ),
        project_id="proj-1",
        capture_context=context(),
    )

    assert [(item.name, item.value) for item in artifact.request.form] == [
        ("user", "alice"),
        ("pass", "hunter2"),
    ]
    assert artifact.request.body_ref is not None
    assert artifact.request.capture_state == "captured"
    assert bodies[artifact.request.body_ref] == b"user=alice&pass=hunter2"


def test_the_client_splits_a_batch_when_the_payload_size_cap_is_reached():
    edge = FakeEdge()
    client = HistoryClient(
        "http://edge.example.test:8001",
        "token-1",
        http_fn=edge,
        max_artifacts=10,
        max_bytes=1,
    )
    artifacts = [
        normalize_cdp_flow(
            flow(request_id=f"r{index}"), project_id="proj-1", capture_context=context()
        )
        for index in range(2)
    ]

    client.ingest("proj-1", "run-1", artifacts)

    assert [len(call["payload"]["artifacts"]) for call in edge.calls] == [1, 1]
