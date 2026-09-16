"""The hunting tools stop degrading when the seams are bound."""
from __future__ import annotations

import json

from polymerhus.attack.hunting.hunter_tools import build_hunter_tools


def test_build_hunter_tools_with_seams_is_not_degraded():
    def search(project_id, filters, cursor, limit, text):
        return {"summaries": [{"artifact_id": "http_A"}]}

    def get(project_id, artifact_id, include_body):
        return {"artifact_id": artifact_id}

    tools = {
        tool.name: tool
        for tool in build_hunter_tools(
            project_id="proj-1", http_search_fn=search, http_get_fn=get,
        )
    }
    out = json.loads(tools["search_http_history"].invoke({}))
    assert out["summaries"][0]["artifact_id"] == "http_A"
