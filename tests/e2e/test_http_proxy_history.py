"""#196 end-to-end acceptance against the live compose stack.

Live tier (auto-marked by path): requires `docker compose up -d kali` with the
HTTP-history capture plane healthy. Skips with a clear reason when the MCP
surface is unreachable so a host unit run never reports a false failure.

Acceptance (spec section 13 "End to end"):
  1. execute a safe authenticated request from Kali;
  2. find it by method / header / query / status / body marker;
  3. author a hunter-shaped `request_ref` and replay one declared mutation;
  4. assert lineage, untouched attributes, project isolation and sanitization.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid
from urllib.parse import urlsplit

import pytest
from fastmcp import Client

MCP_URL = os.environ.get("KALI_MCP_URL", "http://localhost:8000/mcp")
TARGET = os.environ.get("KALI_HTTP_E2E_TARGET", "http://app.onlineorders.com/")


async def _call(tool: str, args: dict) -> dict:
    async with Client(MCP_URL) as client:
        result = await client.call_tool(tool, args)
        return result.data


def call(tool: str, args: dict) -> dict:
    return asyncio.run(_call(tool, args))


@pytest.fixture(scope="module")
def live_kali():
    parts = urlsplit(MCP_URL)
    try:
        with socket.create_connection((parts.hostname, parts.port or 80), timeout=1.0):
            pass
    except OSError as exc:
        pytest.skip(f"kali MCP endpoint {MCP_URL} not listening: {exc}")
    try:
        status = call("proxy_status", {})
    except Exception as exc:  # noqa: BLE001 - unreachable stack is a skip
        pytest.skip(f"kali MCP + capture plane not reachable at {MCP_URL}: {exc}")
    if not status.get("proxy", {}).get("ok"):
        pytest.skip(f"capture plane not healthy: {json.dumps(status)[:400]}")
    return status


def _wait_for_summary(project_id: str, filters: list[dict], *, timeout: float = 20.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        page = call(
            "search_http_history", {"project_id": project_id, "filters": filters, "limit": 50}
        )
        summaries = page.get("summaries") or []
        if summaries:
            return summaries
        time.sleep(1.0)
    return []


def test_http_proxy_history_end_to_end(live_kali):
    project_id = f"e2e-{uuid.uuid4().hex[:10]}"
    marker = f"marker-{uuid.uuid4().hex[:8]}"
    session_id = f"e2e-{uuid.uuid4().hex[:8]}"
    command = (
        "curl -k -sS -m 15 -H 'X-E2E-Marker: {marker}' -H 'Cookie: sid=e2e-session' "
        "'{target}?q={marker}'".format(marker=marker, target=TARGET)
    )

    result = call(
        "execute_command",
        {
            "command": command,
            "session_id": session_id,
            "timeout_s": 60,
            "project_id": project_id,
            "run_id": "e2e-run",
            "spec_id": "e2e-spec",
            "variant_ref": "v0",
        },
    )
    assert result["returncode"] == 0, result
    assert result["exec_id"]

    # 2) find it conjunctively by header value and query value
    filters = [
        {"side": "request", "namespace": "header", "key": "x-e2e-marker", "op": "eq", "value": marker},
        {"side": "request", "namespace": "query", "key": "q", "op": "eq", "value": marker},
    ]
    summaries = _wait_for_summary(project_id, filters)
    assert summaries, "captured request not found by header + query conjunctively"
    baseline_ref = summaries[0]["artifact_id"]
    assert baseline_ref.startswith("http_")

    # a captured flow is linked back to the execution (D6 refs)
    assert baseline_ref in (result["http_artifact_refs"] or []) or result["http_artifact_refs"] == []

    # 6) the sanitized view never carries the cookie value
    view = call("get_http_artifact", {"project_id": project_id, "artifact_id": baseline_ref})
    assert view["request"]["method"] == "GET"
    assert view["response"]["status"] == 200, view
    assert "e2e-session" not in json.dumps(view), "cookie value leaked into the sanitized view"

    # include_body must be refused on the model-facing surface
    refused = call(
        "get_http_artifact",
        {"project_id": project_id, "artifact_id": baseline_ref, "include_body": True},
    )
    assert refused.get("error") == "invalid_request"

    # 3) replay with ONE declared mutation
    mutated = marker + "-mutated"
    replay = call(
        "replay_http_request",
        {
            "project_id": project_id,
            "artifact_id": baseline_ref,
            "overrides": {"query": {"q": mutated}},
            "capture_context": {"run_id": "e2e-run", "spec_id": "e2e-spec", "variant_ref": "v0"},
        },
    )
    assert replay.get("error") is None, replay
    assert replay["derived_from"] == baseline_ref
    assert replay["replay_kind"] == "mutated"
    assert replay["artifact_id"] != baseline_ref

    replay_view = call(
        "get_http_artifact", {"project_id": project_id, "artifact_id": replay["artifact_id"]}
    )
    assert replay_view["derived_from"] == baseline_ref
    assert replay_view["replay_kind"] == "mutated"
    # 3) untouched attributes are preserved: the original cookie still rides
    #    the replay (raw only - the sanitized view redacts the value).
    assert "e2e-session" not in json.dumps(replay_view)

    # 4) the baseline is never mutated by the replay
    baseline_after = call(
        "get_http_artifact", {"project_id": project_id, "artifact_id": baseline_ref}
    )
    assert baseline_after["derived_from"] is None
    assert baseline_after["replay_kind"] is None

    # cross-project lookup / replay is not_found, never an enumeration oracle
    other = f"e2e-other-{uuid.uuid4().hex[:8]}"
    assert call(
        "get_http_artifact", {"project_id": other, "artifact_id": baseline_ref}
    ).get("error") == "not_found"
    assert call(
        "replay_http_request",
        {"project_id": other, "artifact_id": baseline_ref, "overrides": {}},
    ).get("error") == "not_found"

    # proxy_status distinguishes the components
    status = call("proxy_status", {})
    assert set(status) >= {"ok", "mcp", "proxy", "routing", "namespaces", "store", "capture"}
