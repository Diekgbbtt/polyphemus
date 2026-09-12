"""#196 live end-to-end acceptance against the local compose target.

This is deliberately a *live gate*, not a host-unit convenience test. If the
Kali MCP surface or the capture plane is unavailable the test fails; the
only way to keep a no-stack developer run green is to explicitly set
``KALI_HTTP_E2E_ALLOW_SKIP=1``.

Acceptance (spec section 13 "End to end"):
  1. execute a safe authenticated request from Kali;
  2. find it by method / header / cookie / query / status / body marker;
  3. author a hunter-shaped ``request_ref`` spec and run the real pod resolver;
  4. assert lineage, untouched attributes, project isolation and sanitization.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import socket
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastmcp import Client

from polymerhus.attack.hunting.hunting_pod import HuntingHttpPod

MCP_URL = os.environ.get("KALI_MCP_URL", "http://localhost:8000/mcp")
TARGET = os.environ.get("KALI_HTTP_E2E_TARGET", "http://172.28.0.20/")
COOKIE_SECRET = "e2e-session"
AUTH_SECRET = "e2e-secret-token"
ALLOW_SKIP = os.environ.get("KALI_HTTP_E2E_ALLOW_SKIP") == "1"


async def _call(tool: str, args: dict) -> dict:
    async with Client(MCP_URL) as client:
        result = await client.call_tool(tool, args)
        return result.data


def call(tool: str, args: dict) -> dict:
    return asyncio.run(_call(tool, args))


def _unavailable(reason: str) -> None:
    if ALLOW_SKIP:
        pytest.skip(reason)
    pytest.fail(reason)


@pytest.fixture(scope="module")
def live_kali():
    parts = urlsplit(MCP_URL)
    try:
        with socket.create_connection((parts.hostname, parts.port or 80), timeout=1.0):
            pass
    except OSError as exc:
        _unavailable(f"kali MCP endpoint {MCP_URL} not listening: {exc}")
    try:
        status = call("proxy_status", {})
    except Exception as exc:  # noqa: BLE001 - fail loudly; this is the live gate
        _unavailable(f"kali MCP + capture plane not reachable at {MCP_URL}: {exc}")
    if not status.get("proxy", {}).get("ok"):
        _unavailable(f"capture plane not healthy: {json.dumps(status)[:400]}")
    return status


def _wait_for_summary(project_id: str, filters: list[dict], *, timeout: float = 20.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        page = call(
            "search_http_history", {"project_id": project_id, "filters": filters, "limit": 200}
        )
        summaries = page.get("summaries") or []
        if summaries:
            return summaries
        time.sleep(1.0)
    return []


def _query_values(view: dict, name: str) -> list[str]:
    return [item["value"] for item in view.get("request", {}).get("query", []) if item["name"] == name]


def _query_value(view: dict, name: str) -> str | None:
    values = _query_values(view, name)
    return values[0] if values else None


def _strip_url_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def _request_without_declared_mutation(view: dict) -> dict:
    """A request projection that should be identical before/after replay.

    The declared mutation is the query value ``q``; timestamps are per-flow
    transport metadata and the sanitized URL carries the query we deliberately
    removed from this comparison.
    """
    request = copy.deepcopy(view.get("request", {}))
    request.pop("timestamp_start", None)
    request.pop("timestamp_end", None)
    request["query"] = [
        item for item in request.get("query", []) if item.get("name") != "q"
    ]
    request["url"] = _strip_url_query(request.get("url", ""))
    return request


def _assert_no_secret(payload: object, label: str) -> None:
    """The Langfuse/model-facing boundary must never carry raw credentials."""
    text = json.dumps(payload, sort_keys=True, default=str)
    for secret in (COOKIE_SECRET, AUTH_SECRET):
        assert secret not in text, f"{label} leaked raw secret {secret!r}"


def test_http_proxy_history_end_to_end(live_kali):
    project_id = f"e2e-{uuid.uuid4().hex[:10]}"
    marker = f"marker-{uuid.uuid4().hex[:8]}"
    session_id = f"e2e-{uuid.uuid4().hex[:8]}"
    command = (
        "curl -k -sS -m 15 "
        f"-H 'X-E2E-Marker: {marker}' "
        f"-H 'Authorization: Bearer {AUTH_SECRET}' "
        f"-H 'Cookie: sid={COOKIE_SECRET}; stable_cookie=yes' "
        f"'{TARGET}?q={marker}&stable=1'"
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
    assert result["http_artifact_refs"], (
        "capture produced no artifact refs; D6 cannot link the execution"
    )
    _assert_no_secret(result, "execute_command result")

    # 2) find it conjunctively by every acceptance attribute, not only
    #    header + query.
    filters = [
        {"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "GET"},
        {"side": "request", "namespace": "header", "key": "x-e2e-marker", "op": "eq", "value": marker},
        {"side": "request", "namespace": "query", "key": "q", "op": "eq", "value": marker},
        {"side": "request", "namespace": "cookie", "key": "sid", "op": "eq", "value": COOKIE_SECRET},
        {"side": "response", "namespace": "core", "key": "status", "op": "eq", "value": 200},
        {"side": "response", "namespace": "body", "key": "marker", "op": "contains", "value": f"marker={marker}"},
    ]
    summaries = _wait_for_summary(project_id, filters)
    assert summaries, "captured request not found by the full conjunctive acceptance set"
    baseline_ref = summaries[0]["artifact_id"]
    assert baseline_ref.startswith("http_")
    assert baseline_ref in result["http_artifact_refs"], (
        "D6 refs do not include the captured baseline"
    )

    view = call("get_http_artifact", {"project_id": project_id, "artifact_id": baseline_ref})
    assert view["request"]["method"] == "GET"
    assert view["response"]["status"] == 200, view
    assert _query_value(view, "q") == marker
    _assert_no_secret(view, "baseline sanitized artifact")

    # The sanitized view never carries cookie/authorization values.
    for secret in (COOKIE_SECRET, AUTH_SECRET):
        assert secret not in json.dumps(view), "raw secret leaked into the sanitized view"

    # include_body must be refused on the model-facing surface.
    refused = call(
        "get_http_artifact",
        {"project_id": project_id, "artifact_id": baseline_ref, "include_body": True},
    )
    assert refused.get("error") == "invalid_request"

    # 3) author a real hunter spec and let the deterministic pod resolve the
    #    baseline + declared mutations through its own request_ref path.
    mutated = marker + "-mutated"
    replay_state: dict = {}

    def replay_fn(proj: str, ref: str, overrides: dict) -> dict:
        if not overrides:
            resolved = call("get_http_artifact", {"project_id": proj, "artifact_id": ref})
            return {"status": (resolved.get("response") or {}).get("status")}
        replay = call(
            "replay_http_request",
            {
                "project_id": proj,
                "artifact_id": ref,
                "overrides": overrides,
                "capture_context": {
                    "run_id": "e2e-run",
                    "spec_id": "e2e-spec",
                    "variant_ref": "v0",
                },
            },
        )
        if replay.get("error"):
            replay_state["error"] = replay
            return {"status": None}
        replay_view = call(
            "get_http_artifact", {"project_id": proj, "artifact_id": replay["artifact_id"]}
        )
        replay_state["replay"] = replay
        replay_state["replay_view"] = replay_view
        return {
            "status": (replay_view.get("response") or {}).get("status"),
            "artifact_id": replay["artifact_id"],
        }

    spec = {
        "d4_typed_base": {
            "target_identity": {"url": TARGET},
            "payload_vector_space": {
                "request_ref": baseline_ref,
                "mutations": [
                    {"location": "query", "name": "q", "values": [mutated]},
                ],
            },
        }
    }
    pod = HuntingHttpPod(
        target_url=TARGET,
        replay_fn=replay_fn,
        project_id=project_id,
    )
    envelope = pod(spec)
    assert not replay_state.get("error"), replay_state.get("error")
    assert envelope["verdict"] == "unsuccessful"
    assert envelope["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert envelope["evidence"]["clean"] is True
    assert envelope["evidence"]["iterations"] == 1
    interpretations = envelope["evidence"]["interpretations"]
    assert len(interpretations) == 1
    assert interpretations[0]["override"] == {"query": {"q": mutated}}
    assert interpretations[0]["status"] == 200
    _assert_no_secret(envelope, "hunting pod evidence")

    replay = replay_state["replay"]
    assert replay.get("error") is None, replay
    assert replay["derived_from"] == baseline_ref
    assert replay["replay_kind"] == "mutated"
    assert replay["artifact_id"] != baseline_ref

    replay_view = replay_state["replay_view"]
    assert replay_view["derived_from"] == baseline_ref
    assert replay_view["replay_kind"] == "mutated"
    assert _query_value(replay_view, "q") == mutated
    _assert_no_secret(replay_view, "replay sanitized artifact")

    # 4) untouched request attributes are preserved and only q changed.
    assert _request_without_declared_mutation(view) == _request_without_declared_mutation(replay_view), (
        "replay changed request attributes beyond the declared query mutation"
    )
    assert _query_value(view, "stable") == "1"
    assert _query_value(replay_view, "stable") == "1"

    # The local target proves the cookie value was actually replayed by
    # emitting cookie_ok=1 into the response body marker, without echoing the
    # secret itself.
    replay_search = _wait_for_summary(
        project_id,
        [
            {"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "GET"},
            {"side": "request", "namespace": "query", "key": "q", "op": "eq", "value": mutated},
            {"side": "response", "namespace": "core", "key": "status", "op": "eq", "value": 200},
            {"side": "response", "namespace": "body", "key": "marker", "op": "contains", "value": f"query_q={mutated}"},
            {"side": "response", "namespace": "body", "key": "marker", "op": "contains", "value": "cookie_ok=1"},
        ],
    )
    assert replay_search, "replayed artifact not found with cookie-preservation body marker"
    assert any(row["artifact_id"] == replay["artifact_id"] for row in replay_search)

    # The baseline is never mutated by the replay.
    baseline_after = call(
        "get_http_artifact", {"project_id": project_id, "artifact_id": baseline_ref}
    )
    assert baseline_after["derived_from"] is None
    assert baseline_after["replay_kind"] is None
    assert _query_value(baseline_after, "q") == marker

    # Cross-project lookup / replay is not_found, never an enumeration oracle.
    other = f"e2e-other-{uuid.uuid4().hex[:8]}"
    assert call(
        "get_http_artifact", {"project_id": other, "artifact_id": baseline_ref}
    ).get("error") == "not_found"
    assert call(
        "replay_http_request",
        {"project_id": other, "artifact_id": baseline_ref, "overrides": {}},
    ).get("error") == "not_found"

    # Final gate: proxy_status distinguishes components and is healthy.
    status = call("proxy_status", {})
    assert status["ok"] is True
    assert status["proxy"]["ok"] is True
    assert set(status) >= {"ok", "mcp", "proxy", "routing", "namespaces", "store", "capture"}
