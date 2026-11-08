"""#196: the hunter's read-only search/get tools (sanitized, replay stays in-pod)."""
from __future__ import annotations

import json


from polymerhus.attack.hunting.hunter_tools import (
    HttpHistoryGetTool,
    HttpHistorySearchTool,
    build_hunter_tools,
)
from polymerhus.attack.hunting.pod.agents import runner_react_tools


def test_search_tool_returns_sanitized_summaries():
    seen = {}

    def search_fn(project_id, filters, cursor, limit, text):
        seen["args"] = (project_id, filters, cursor, limit, text)
        return {"summaries": [{"artifact_id": "http_A", "method": "POST", "status": 200}]}

    tool = HttpHistorySearchTool(http_search_fn=search_fn, project_id="proj-1")
    out = json.loads(tool.invoke({"filters": [{"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "POST"}]}))
    assert out["summaries"][0]["artifact_id"] == "http_A"
    assert seen["args"][0] == "proj-1"


def test_search_tool_is_fail_open_when_unwired():
    out = json.loads(HttpHistorySearchTool(project_id="proj-1").invoke({}))
    assert out["ok"] is False and out["degraded"] is True


def test_get_tool_never_accepts_include_body():
    seen = {}

    def get_fn(project_id, artifact_id, include_body):
        seen["include_body"] = include_body
        return {"artifact_id": artifact_id, "request": {"method": "GET"}}

    tool = HttpHistoryGetTool(http_get_fn=get_fn, project_id="proj-1")
    out = json.loads(tool.invoke({"artifact_id": "http_A"}))
    assert out["artifact_id"] == "http_A"
    assert seen["include_body"] is False
    assert "include_body" not in tool.args_schema.model_json_schema()["properties"]


def test_build_hunter_tools_binds_the_read_only_pair():
    names = {t.name for t in build_hunter_tools()}
    assert {"search_http_history", "get_http_artifact"} <= names


def test_descriptions_teach_the_chain():
    tools = {t.name: t for t in build_hunter_tools()}
    assert "candidate" in tools["search_http_history"].description
    assert "capture_state" in tools["get_http_artifact"].description
    assert "lineage" in tools["exec"].description


def test_the_search_contract_names_the_verbatim_row():
    """The row is verbatim by operator decision: the model must not assume a
    redaction boundary that `get_http_artifact` still enforces."""
    description = {
        t.name: t for t in build_hunter_tools()
    }["search_http_history"].description

    assert "`url` (raw)" in description
    assert "(verbatim)" in description
    assert "`capture_state` is on `get_http_artifact`" in description


def _pod_tools():
    return {
        tool.name: tool
        for tool in runner_react_tools(
            exec_fn=lambda *a, **k: None, memory_store=None, spec_id="s",
            log=None, variant_ref="v0",
            replay_fn=lambda *a: {"status": 200}, project_id="proj-1",
        )
    }


def test_the_http_history_descriptions_come_from_one_single_sourced_contract():
    """#196 stability: the three model-facing verbs (search/get on the hunter,
    replay on the pod runner) read ONE canonical description each, so no binding
    site can drift from the others."""
    from polymerhus.attack.hunting import http_history_contract as contract

    hunter = {t.name: t for t in build_hunter_tools()}
    assert hunter["search_http_history"].description == \
        contract.SEARCH_HTTP_HISTORY_DESCRIPTION
    assert hunter["get_http_artifact"].description == \
        contract.GET_HTTP_ARTIFACT_DESCRIPTION
    assert _pod_tools()["replay"].description == \
        contract.REPLAY_HTTP_REQUEST_DESCRIPTION


def test_every_http_history_description_states_the_contract_and_the_model():
    from polymerhus.attack.hunting.http_history_contract import (
        GET_HTTP_ARTIFACT_DESCRIPTION,
        REPLAY_HTTP_REQUEST_DESCRIPTION,
        SEARCH_HTTP_HISTORY_DESCRIPTION,
    )

    for text in (SEARCH_HTTP_HISTORY_DESCRIPTION, GET_HTTP_ARTIFACT_DESCRIPTION,
                 REPLAY_HTTP_REQUEST_DESCRIPTION):
        # the minimal domain model rides EVERY verb
        assert "artifact_id" in text
        assert "capture_state" in text
        assert "derived_from" in text and "replay_kind" in text

    # search: the filter grammar, the deterministic paging, the role in the chain
    search = SEARCH_HTTP_HISTORY_DESCRIPTION
    assert "conjunctive" in search.lower()
    assert "next_cursor" in search
    assert "absent" in search
    assert "provenance.baseline_ref" in search
    # T8 (#381): the retired D4 field never names the baseline again.
    assert "payload_vector_space" not in search and "request_ref" not in search
    # FM-B: the filter-vocabulary anti-patterns are taught, not just listed
    assert "TWO DIFFERENT AXES" in search
    assert "no `present` op" in search
    assert "does not accept booleans" in search

    # get: what makes a baseline replayable, and what is visible
    get = GET_HTTP_ARTIFACT_DESCRIPTION
    assert "captured" in get
    assert "provenance.baseline_ref" in get
    assert "payload_vector_space" not in get and "request_ref" not in get

    # replay: the CLOSED override vocabulary and the lineage of the new artifact
    replay = REPLAY_HTTP_REQUEST_DESCRIPTION
    for key in ("remove_header", "form", "json", "mutated"):
        assert key in replay

