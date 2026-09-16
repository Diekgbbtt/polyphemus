"""The production runner can execute a spec's request_ref."""
from __future__ import annotations

import json

from polymerhus.attack.hunting.pod.agents import runner_react_tools


def _tools(**kwargs):
    return {
        tool.name: tool
        for tool in runner_react_tools(
            exec_fn=lambda *a, **k: None,
            memory_store=None, spec_id="s", log=None, variant_ref="v0", **kwargs,
        )
    }


def test_replay_tool_is_absent_without_the_seam():
    assert "replay" not in _tools()


def test_replay_tool_returns_the_status_of_the_new_artifact():
    seen = {}

    def replay_fn(project_id, artifact_id, overrides):
        seen["args"] = (project_id, artifact_id, overrides)
        return {"status": 200, "artifact_id": "http_NEW"}

    tools = _tools(replay_fn=replay_fn, project_id="proj-1")
    out = json.loads(tools["replay"].invoke(
        {"artifact_id": "http_OLD", "overrides": {"query": {"q": "x"}}}
    ))
    assert out["status"] == 200
    assert seen["args"] == ("proj-1", "http_OLD", {"query": {"q": "x"}})


def test_replay_tool_reports_a_missing_reference_as_null_status():
    tools = _tools(replay_fn=lambda *a: {"status": None}, project_id="proj-1")
    out = json.loads(tools["replay"].invoke({"artifact_id": "http_MISSING"}))
    assert out["status"] is None
