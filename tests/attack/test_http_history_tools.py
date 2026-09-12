"""#196: the hunter's read-only search/get tools (sanitized, replay stays in-pod)."""
from __future__ import annotations

import json

from polymerhus.attack.hunting.hunter_tools import (
    HttpHistoryGetTool,
    HttpHistorySearchTool,
    build_hunter_tools,
)


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
