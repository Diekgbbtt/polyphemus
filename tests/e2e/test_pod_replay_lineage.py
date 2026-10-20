"""The #397 live replay-lineage gate (replaces the retired #196 history gate).

This is deliberately a *live gate*, not a host-unit convenience test. The
retired ``tests/e2e/test_http_proxy_history.py`` died with the legacy
``hunting_pod.py``, but the production capability it guarded did not: the
replay path now lives on the test-executor pod's runner
(``runner_react_tools(...).replay`` bound to ``default_replay_fn``), and the
lineage is the capture plane's ``derived_from`` / ``replay_kind`` stamped on the
new immutable artifact.

If the Kali MCP surface or the capture plane is unavailable the test fails; the
only way to keep a no-stack developer run green is to explicitly set
``KALI_HTTP_E2E_ALLOW_SKIP=1``.

Acceptance (carried from #196, retargeted by #397):
  1. execute a safe authenticated request from Kali;
  2. find it by method / header / cookie / query / status / body marker;
  3. fetch it and assert the captured request bytes are the replay precondition;
  4. author the reduced D4 with ``provenance.baseline_ref`` (no payload vector);
  5. drive the production runner's ``replay`` tool with a declared mutation;
  6. assert lineage, untouched attributes, the unchanged baseline, project
     isolation and sanitization.
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

from polymerhus.attack.hunting.http_history_contract import REPLAY_HTTP_REQUEST_DESCRIPTION
from polymerhus.attack.hunting.pod.agents import runner_react_tools
from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.symbolic import author_probe_from_spec
from polymerhus.attack.hunting.pod.types import (
    TestImplementationSpec as D4Spec,
    baseline_ref_from_spec,
)
from polymerhus.attack.hunting.pod.verification import validate_probe_chain, validate_spec
from polymerhus.app.clients.kali_http_history import close_unit_session, default_replay_fn

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
    """The live policy of the retired gate: fail loudly when the stack is
    absent, unless the operator opts into a skip for a no-stack run."""
    parts = urlsplit(MCP_URL)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname, port), timeout=1.0):
            pass
    except OSError as exc:
        _unavailable(f"kali MCP endpoint {MCP_URL} not listening: {exc}")
    try:
        status = call("proxy_status", {})
    except Exception as exc:  # noqa: BLE001 - fail loudly; this is the live gate
        _unavailable(f"kali MCP + capture plane not reachable at {MCP_URL}: {exc}")
    if not status.get("proxy", {}).get("ok"):
        _unavailable(f"capture plane not healthy: {json.dumps(status)[:400]}")
    yield status
    close_unit_session()


def _wait_for_summary(
    project_id: str, filters: list[dict], *, timeout: float = 30.0
) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        page = call(
            "search_http_history", {"project_id": project_id, "filters": filters, "limit": 200}
        )
        assert not page.get("error"), f"search_http_history failed: {page}"
        summaries = page.get("summaries") or []
        if summaries:
            return summaries
        time.sleep(1.0)
    return []


def _query_value(view: dict, name: str) -> str | None:
    return next(
        (
            item["value"]
            for item in view.get("request", {}).get("query", [])
            if item["name"] == name
        ),
        None,
    )


def _form_value(view: dict, name: str) -> str | None:
    return next(
        (
            item["value"]
            for item in view.get("request", {}).get("form", [])
            if item["name"] == name
        ),
        None,
    )


def _request_body_state(view: dict) -> str | None:
    return (view.get("request", {}).get("body") or {}).get("capture_state")


def _assert_replayable(view: dict, label: str) -> None:
    """The capture contract: only ``captured`` bytes are in the store, so only
    they can be replayed. This gate deliberately records a request body, so a
    replay that succeeded proves the captured bytes round-tripped. The
    fail-closed refusal of an omitted/truncated body is pinned in
    ``tests/kali/test_http_history_service.py``."""
    state = _request_body_state(view)
    assert state == "captured", (
        f"the {label} request body is {state!r}: the bytes are not in the store, "
        "so the replay would have to send a bodyless request"
    )


def _strip_url_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def _request_without_transport_metadata(view: dict) -> dict:
    """A request projection with only per-flow timestamps removed."""
    request = copy.deepcopy(view.get("request", {}))
    request.pop("timestamp_start", None)
    request.pop("timestamp_end", None)
    return request


def _request_without_declared_mutation(view: dict) -> dict:
    """The request projection that must be identical before/after replay.

    The declared mutation is the query value ``q``; timestamps are per-flow
    transport metadata, and the sanitized URL carries the query we deliberately
    removed from this comparison.
    """
    request = _request_without_transport_metadata(view)
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


def _unexpected_exec(*_args, **_kwargs):
    raise AssertionError("the lineage gate drives the replay tool, never exec")


def test_pod_replay_lineage_end_to_end(live_kali):
    project_id = f"e2e-{uuid.uuid4().hex[:10]}"
    marker = f"marker-{uuid.uuid4().hex[:8]}"
    session_id = f"e2e-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    spec_id = f"spec-{uuid.uuid4().hex[:8]}"
    request_body = f"body_marker={marker}&stable_body=1"

    # 1) Execute a safe authenticated request from Kali. The POST body is
    #    deliberate: the gate needs a request whose bytes are CAPTURED, because
    #    only captured bytes are replayable.
    command = (
        "curl -k -sS -m 15 -X POST "
        f"-H 'X-E2E-Marker: {marker}' "
        f"-H 'Authorization: Bearer {AUTH_SECRET}' "
        f"-H 'Cookie: sid={COOKIE_SECRET}; stable_cookie=yes' "
        "-H 'Content-Type: application/x-www-form-urlencoded' "
        f"--data-binary '{request_body}' "
        f"'{TARGET}?q={marker}&stable=1'"
    )
    result = call(
        "execute_command",
        {
            "command": command,
            "session_id": session_id,
            "timeout_s": 60,
            "project_id": project_id,
            "run_id": run_id,
            "spec_id": spec_id,
            "variant_ref": "v0",
        },
    )
    assert result["returncode"] == 0, result
    assert result["exec_id"]
    assert result["http_artifact_refs"], (
        "capture produced no artifact refs; the replay lineage cannot be linked"
    )
    assert "cookie_ok=1" in result["stdout"], result["stdout"]
    assert "auth_header_present=1" in result["stdout"], result["stdout"]
    _assert_no_secret(result, "execute_command result")

    # 2) Find it conjunctively by every acceptance attribute - including the
    #    captured request body marker and its capture state.
    filters = [
        {"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "POST"},
        {"side": "request", "namespace": "header", "key": "x-e2e-marker", "op": "eq", "value": marker},
        {"side": "request", "namespace": "query", "key": "q", "op": "eq", "value": marker},
        {"side": "request", "namespace": "cookie", "key": "sid", "op": "eq", "value": COOKIE_SECRET},
        {"side": "request", "namespace": "body", "key": "marker", "op": "contains", "value": f"body_marker={marker}"},
        {"side": "request", "namespace": "body", "key": "capture_state", "op": "eq", "value": "captured"},
        {"side": "response", "namespace": "core", "key": "status", "op": "eq", "value": 200},
        {"side": "response", "namespace": "body", "key": "marker", "op": "contains", "value": f"marker={marker}"},
    ]
    summaries = _wait_for_summary(project_id, filters)
    assert summaries, "captured request not found by the full conjunctive acceptance set"
    baseline_matches = [
        row for row in summaries if row["artifact_id"] in result["http_artifact_refs"]
    ]
    assert baseline_matches, (
        "the captured baseline is not in the execute_command artifact refs: "
        f"{[row['artifact_id'] for row in summaries]} != {result['http_artifact_refs']}"
    )
    baseline_ref = baseline_matches[0]["artifact_id"]
    assert baseline_ref.startswith("http_")

    # 3) Fetch it and assert the replay precondition: captured request bytes.
    view = call("get_http_artifact", {"project_id": project_id, "artifact_id": baseline_ref})
    assert not view.get("error"), view
    assert view["artifact_id"] == baseline_ref
    assert view["request"]["method"] == "POST"
    assert view["response"]["status"] == 200, view
    assert _query_value(view, "q") == marker
    assert _query_value(view, "stable") == "1"
    assert _form_value(view, "body_marker") == marker
    assert _form_value(view, "stable_body") == "1"
    assert view["request"]["body"]["size"] == len(request_body)
    assert view["response"]["body"]["capture_state"] == "captured"
    _assert_replayable(view, "baseline")
    assert view["derived_from"] is None
    assert view["replay_kind"] is None
    assert view["capture_context"]["run_id"] == run_id
    assert view["capture_context"]["spec_id"] == spec_id
    assert view["capture_context"]["variant_ref"] == "v0"
    assert view["capture_context"]["exec_id"] == result["exec_id"]

    headers = {name.lower(): value for name, value in view["request"]["headers"]}
    assert headers["x-e2e-marker"] == marker
    assert headers["authorization"] == "[redacted]"
    assert headers["cookie"] == "[redacted]"
    _assert_no_secret(view, "baseline sanitized artifact")

    # include_body must be refused on the model-facing surface.
    refused = call(
        "get_http_artifact",
        {"project_id": project_id, "artifact_id": baseline_ref, "include_body": True},
    )
    assert refused.get("error") == "invalid_filter"

    # 4) Author the reduced D4 (S5 8.5): the baseline pointer lives in
    #    provenance.baseline_ref and there is no payload vector space.
    spec = {
        "target_identity": {"url": TARGET, "unit_id": "service:web:http-e2e-target"},
        "verification_symptoms": [f"HTTP 200 with body marker marker={marker}"],
        "assumptions": [],
        "rationale": "the recorded baseline replays with only the declared mutation",
        "provenance": {
            "loop_id": f"loop-{project_id}",
            "unit_id": "service:web:http-e2e-target",
            "canonical_class": "replay-lineage",
            "web_vulnerability_class": "replay-lineage",
            "baseline_ref": baseline_ref,
        },
    }
    assert "payload_vector_space" not in spec
    assert validate_spec(spec) == [], validate_spec(spec)
    typed_spec = D4Spec(**spec)
    assert baseline_ref_from_spec(typed_spec) == baseline_ref
    chain = author_probe_from_spec(spec, "v0")
    assert chain is not None
    core = next(step for step in chain.steps if step.role == "core")
    assert core.request_ref == baseline_ref
    assert validate_probe_chain(chain) == []

    # 5) Drive the PRODUCTION pod runner's replay tool, bound to the real
    #    capture-plane seam, with a declared mutation. `arun_pod` would need a
    #    live LLM turn; the replay capability IS the runner's tool construction,
    #    so drive that construction with the real MCP seam - nothing is mocked.
    log = ExperimentLog()
    tools = {
        tool.name: tool
        for tool in runner_react_tools(
            exec_fn=_unexpected_exec,
            memory_store=None,
            spec_id="replay-lineage",
            log=log,
            variant_ref="v0",
            replay_fn=default_replay_fn,
            project_id=project_id,
        )
    }
    assert "replay" in tools, sorted(tools)
    assert tools["replay"].description == REPLAY_HTTP_REQUEST_DESCRIPTION
    mutated = f"{marker}-mutated"
    replay_out = json.loads(
        tools["replay"].invoke(
            {"artifact_id": baseline_ref, "overrides": {"query": {"q": mutated}}}
        )
    )
    assert replay_out.get("error") is None, replay_out
    assert replay_out["status"] == 200, replay_out
    assert replay_out["artifact_id"] != baseline_ref
    _assert_no_secret(replay_out, "pod replay tool result")

    # The pod's D6 trail records the replay as a probe execution (G4).
    assert len(log.raw_observations) == 1
    observation = log.raw_observations[0]
    assert observation.status == 200
    assert observation.http_artifact_refs == [replay_out["artifact_id"]]
    assert observation.request == {
        "artifact_id": baseline_ref,
        "overrides": {"query": {"q": mutated}},
    }
    _assert_no_secret(observation.model_dump(), "D6 replay observation")

    # 6) The new artifact carries its lineage; only the declared mutation moved.
    replay_view = call(
        "get_http_artifact",
        {"project_id": project_id, "artifact_id": replay_out["artifact_id"]},
    )
    assert not replay_view.get("error"), replay_view
    assert replay_view["artifact_id"] == replay_out["artifact_id"]
    assert replay_view["derived_from"] == baseline_ref
    assert replay_view["replay_kind"] == "mutated"
    assert replay_view["capture_context"]["derived_from"] == baseline_ref
    assert replay_view["capture_context"]["replay_kind"] == "mutated"
    assert _query_value(replay_view, "q") == mutated
    assert _query_value(replay_view, "stable") == "1"
    assert _form_value(replay_view, "body_marker") == marker
    assert replay_view["request"]["body"]["size"] == len(request_body)
    assert replay_view["response"]["body"]["capture_state"] == "captured"
    _assert_replayable(replay_view, "replay")
    _assert_no_secret(replay_view, "replay sanitized artifact")

    assert _request_without_declared_mutation(view) == _request_without_declared_mutation(
        replay_view
    ), "replay changed request attributes beyond the declared query mutation"

    # The response markers prove the untouched transport state reached the
    # target on the replay: header, cookie, authorization and body.
    replay_search = _wait_for_summary(
        project_id,
        [
            {"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "POST"},
            {"side": "request", "namespace": "query", "key": "q", "op": "eq", "value": mutated},
            {"side": "response", "namespace": "core", "key": "status", "op": "eq", "value": 200},
            {"side": "response", "namespace": "body", "key": "marker", "op": "contains", "value": f"query_q={mutated}"},
            {"side": "response", "namespace": "body", "key": "marker", "op": "contains", "value": "cookie_ok=1"},
            {"side": "response", "namespace": "body", "key": "marker", "op": "contains", "value": "auth_header_present=1"},
            {"side": "response", "namespace": "body", "key": "marker", "op": "contains", "value": f"body_marker={request_body}"},
        ],
    )
    assert replay_search, "replayed artifact not found with the preserved-request markers"
    replay_row = next(
        row for row in replay_search if row["artifact_id"] == replay_out["artifact_id"]
    )
    assert replay_row["derived_from"] == baseline_ref
    assert replay_row["replay_kind"] == "mutated"

    # The baseline is never mutated by the replay.
    baseline_after = call(
        "get_http_artifact", {"project_id": project_id, "artifact_id": baseline_ref}
    )
    assert baseline_after["artifact_id"] == baseline_ref
    assert baseline_after["derived_from"] is None
    assert baseline_after["replay_kind"] is None
    assert _query_value(baseline_after, "q") == marker
    assert _request_without_transport_metadata(baseline_after) == (
        _request_without_transport_metadata(view)
    ), "the replay mutated the baseline artifact"

    # Cross-project lookup / replay is not_found, never an enumeration oracle.
    other = f"e2e-other-{uuid.uuid4().hex[:8]}"
    assert (
        call("get_http_artifact", {"project_id": other, "artifact_id": baseline_ref}).get("error")
        == "not_found"
    )
    assert (
        call(
            "replay_http_request",
            {"project_id": other, "artifact_id": baseline_ref, "overrides": {}},
        ).get("error")
        == "not_found"
    )

    # Final gate: proxy_status distinguishes components and is healthy.
    status = call("proxy_status", {})
    assert status["ok"] is True
    assert status["proxy"]["ok"] is True
    assert set(status) >= {"ok", "mcp", "proxy", "routing", "namespaces", "store", "capture"}
