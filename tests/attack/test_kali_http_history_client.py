"""Shape extraction for the app-side HTTP-history client (no live MCP)."""
from __future__ import annotations

from polymerhus.app.clients.kali_http_history import structured_payload


def test_structured_payload_reads_the_artifact_dict():
    assert structured_payload({"structured_content": {"summaries": []}}) == {
        "summaries": []
    }


def test_structured_payload_returns_error_on_a_bare_message():
    out = structured_payload("boom")
    assert out["error"] == "unstructured_response"
    assert "boom" in out["detail"]


def test_structured_payload_decodes_the_live_mcp_content_block():
    """The kali MCP adapter answers a dict-returning tool with
    `[{"type": "text", "text": "<json>"}]` (verified against the live server)."""
    live = [{"type": "text", "text": '{"summaries": [{"artifact_id": "http_A"}]}',
             "id": "lc_1"}]
    assert structured_payload(live) == {"summaries": [{"artifact_id": "http_A"}]}


def test_structured_payload_refuses_a_non_json_text_block():
    out = structured_payload([{"type": "text", "text": "not json"}])
    assert out["error"] == "unstructured_response"
