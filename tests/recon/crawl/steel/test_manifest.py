"""Seam under test: the v2 manifest model and writer.

Spec: `docs/design/steel-crawl-spec.md` section 11; seam 9 of
`docs/design/steel-crawl-implementation-plan.md` section 3.

The manifest is the graph input: the run block and the graph-bearing records
only. Pages, actions, flows, artifacts, declared blocks, and coverage are
structural absences, and the v1 parser keeps working. Expected keys and values
come from the spec, never from re-reading the model.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from polymerhus.recon.crawl.steel.capture.typing import RealtimeRecord, ScriptAsset
from polymerhus.recon.crawl.steel.manifest import (
    EndpointRecord,
    ErrorRecord,
    Manifest,
    ParameterRecord,
    RunBlock,
    build_manifest,
    load_manifest,
    write_manifest,
)
from polymerhus.recon.domain.parsers.steel_parser import parse as parse_v1


def run() -> RunBlock:
    return RunBlock(
        crawl_run_id="run-1",
        session_name="session-1",
        account="admin",
        started_at="2026-11-02T10:00:00Z",
        finished_at="2026-11-02T10:10:00Z",
        stop_reason="frontier_empty",
        partial=False,
        scope=["example.test"],
        auth={"classification": "authenticated"},
    )


def endpoint() -> EndpointRecord:
    return EndpointRecord(
        endpoint_id="ep_observed_1",
        provenance="observed",
        method="GET",
        url="https://example.test/api/items?page=2",
        path="/api/items",
        baseurl="https://example.test",
        status_code=200,
        source="cdp",
        resource_type="XHR",
        http_artifact_id="http_ABC",
        source_page_id="page_1",
        action_id="act_1",
    )


def parameter() -> ParameterRecord:
    return ParameterRecord(
        parameter_id="param_observed_1",
        endpoint_id="ep_observed_1",
        provenance="observed",
        endpoint_path="/api/items",
        baseurl="https://example.test",
        position="query",
        name="page",
        value_shape={"type": "number", "length_band": 0},
        http_artifact_id="http_ABC",
    )


def test_the_v2_manifest_carries_only_the_graph_bearing_records():
    manifest = build_manifest(
        run=run(),
        endpoints=[endpoint()],
        parameters=[parameter()],
        scripts=[ScriptAsset(script_url="https://example.test/app.js", script_id="10")],
        realtime=[
            RealtimeRecord(
                request_id="ws-1",
                kind="frame_sent",
                direction="sent",
                opcode=1,
                payload='{"subscribe":"items"}',
            )
        ],
        errors=[
            ErrorRecord(
                code="stale_element",
                message="the reference is gone",
                stage="executor",
                page_id="page_1",
                action_id="act_1",
            )
        ],
        flows=7,
        bytes=4096,
        duration_ms=1000,
        removed_elements=3,
        unrecoverable_pages=1,
    )

    data = manifest.model_dump(mode="json")
    assert set(data) == {
        "schema_version",
        "run",
        "endpoints",
        "parameters",
        "scripts",
        "realtime",
        "errors",
        "stats",
    }
    for forbidden in (
        "pages",
        "actions",
        "flows",
        "artifacts",
        "declared_endpoints",
        "declared_fields",
        "coverage",
    ):
        assert forbidden not in data
    assert data["schema_version"] == "steel-crawl/v2"
    assert data["run"]["crawl_run_id"] == "run-1"
    assert data["run"]["auth"] == {"classification": "authenticated"}
    assert data["endpoints"][0]["provenance"] == "observed"
    assert data["parameters"][0]["value_shape"] == {
        "type": "number",
        "length_band": 0,
    }
    assert data["scripts"][0]["script_url"] == "https://example.test/app.js"
    assert data["realtime"][0]["kind"] == "frame_sent"
    assert data["errors"][0]["code"] == "stale_element"
    assert data["stats"] == {
        "endpoints": 1,
        "parameters": 1,
        "flows": 7,
        "bytes": 4096,
        "duration_ms": 1000,
        "removed_elements": 3,
        "unrecoverable_pages": 1,
    }


def test_the_writer_round_trips_atomically(tmp_path):
    manifest = build_manifest(run=run(), endpoints=[endpoint()])
    path = tmp_path / "manifest.json"

    write_manifest(path, manifest)

    assert load_manifest(path) == manifest
    assert not (tmp_path / "manifest.json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == (
        "steel-crawl/v2"
    )


def test_a_forbidden_top_level_block_is_rejected():
    data = build_manifest(run=run()).model_dump(mode="json")
    data["pages"] = [{"url": "https://example.test/"}]

    with pytest.raises(ValidationError):
        Manifest.model_validate(data)


def test_a_v1_manifest_still_parses_with_the_existing_parser():
    v1 = json.dumps(
        {
            "endpoints": [
                {
                    "method": "GET",
                    "url": "https://example.test/api/items?page=2",
                    "query": ["page"],
                    "status": 200,
                }
            ],
            "js_urls": [],
        }
    )

    deltas = parse_v1(v1)

    assert any(delta.type == "Endpoint" for delta in deltas)
    assert any(delta.type == "Parameter" for delta in deltas)
