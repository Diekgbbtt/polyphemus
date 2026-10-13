"""Shape extraction and per-unit session lifecycle for the app-side HTTP-history
client (no live MCP)."""
from __future__ import annotations

import pytest

import polymerhus.app.clients.kali_http_history as H
from polymerhus.app.clients.kali_http_history import (
    _session,
    close_unit_session,
    default_http_search_fn,
    structured_payload,
)


class _FakeSession:
    """A stand-in for `_UnitSession`: records construction, calls and close."""

    instances: list["_FakeSession"] = []

    def __init__(self, url: str):
        self.url = url
        self.calls: list = []
        self.closed = False
        _FakeSession.instances.append(self)

    def call(self, name: str, args: dict):
        self.calls.append((name, args))
        return {"summaries": []}

    def close(self):
        self.closed = True


@pytest.fixture
def fake_sessions(monkeypatch):
    _FakeSession.instances = []
    monkeypatch.setattr(H, "_UnitSession", _FakeSession)
    monkeypatch.setattr(H, "_SESSION", None)
    monkeypatch.setattr(H, "_SESSION_KEY", None)
    return _FakeSession


def test_session_reused_across_calls_in_one_unit(fake_sessions):
    """One unit pays ONE MCP handshake, not one per tool call."""
    assert _session("p") is _session("p")
    assert len(fake_sessions.instances) == 1


def test_session_replaced_when_the_unit_changes(fake_sessions, monkeypatch):
    first = _session("p")
    monkeypatch.setattr(H, "_unit_key", lambda pid: (pid, "unit-2"))
    second = _session("p")
    assert first.closed
    assert second is not first
    assert len(fake_sessions.instances) == 2


def test_close_unit_session_closes_and_is_idempotent(fake_sessions):
    opened = _session("p")
    close_unit_session()
    assert opened.closed
    close_unit_session()


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


def test_search_fn_degrades_fail_open_when_the_session_cannot_open(
    fake_sessions, monkeypatch
):
    """A session that never opens (a hung MCP read) must degrade to the error
    bundle, never raise into the proposer turn."""

    def _boom(*_args, **_kwargs):
        raise TimeoutError("hung")

    monkeypatch.setattr(H, "_UnitSession", _boom)
    out = default_http_search_fn("p", [], None, 50, None)
    assert out["error"] == "http_history_failed"
    assert "hung" in out["detail"]
