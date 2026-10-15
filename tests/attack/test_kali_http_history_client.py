"""Shape extraction and per-unit session lifecycle for the app-side HTTP-history
client (no live MCP)."""
from __future__ import annotations

import threading

import pytest
from anyio import ClosedResourceError

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


def test_parallel_calls_share_one_winner_and_never_kill_a_live_session(monkeypatch):
    """A turn's tool calls run on worker threads. When several miss the cache
    together they all open; the install is install-or-yield, so ONE winner lands,
    every loser closes only its OWN surplus and reuses the winner. Pre-fix the
    second install closed the winner's session out from under its caller - the
    arm H `ClosedResourceError` that appeared in every assigner turn."""
    instances, barrier = [], threading.Barrier(2)

    class _ConcurrentSession:
        def __init__(self, url):
            self.closed = False
            instances.append(self)
            barrier.wait(timeout=10)   # hold BOTH opens open: both callers missed the cache

        def call(self, name, args):
            return {"summaries": []}

        def close(self):
            self.closed = True

    monkeypatch.setattr(H, "_UnitSession", _ConcurrentSession)
    monkeypatch.setattr(H, "_SESSION", None)
    monkeypatch.setattr(H, "_SESSION_KEY", None)
    got, errors = [], []

    def worker():
        try:
            got.append(_session("p"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert not errors
    assert len(instances) == 2, "both callers opened (a miss gives no cheaper way)"
    assert len({id(s) for s in got}) == 1, "one session survives for the unit"
    winner = got[0]
    assert not winner.closed, "the winner's live session is never closed"
    assert all(s.closed for s in instances if s is not winner), "the surplus closes"


def test_the_unit_boundary_closes_the_session_and_the_next_unit_opens_fresh(fake_sessions):
    """T2: `proposer_batch` is the unit scope - leaving it closes the MCP session
    at the same boundary where the agent session is reset (reset, not torn
    down). The next chunk then opens a fresh session instead of reusing a
    closed one."""
    from polymerhus.analysis.proposer_turn import proposer_batch

    with proposer_batch("katana:0"):
        opened = _session("p")
        assert not opened.closed
    assert opened.closed, "the unit's session closed at its boundary"

    with proposer_batch("katana:1"):
        assert _session("p") is not opened
        assert len(fake_sessions.instances) == 2
    assert fake_sessions.instances[1].closed


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
    bundle, never raise into the proposer turn - after the bounded heal
    retries the handshake."""

    def _boom(*_args, **_kwargs):
        raise TimeoutError("hung")

    opens: list = []
    monkeypatch.setattr(H, "_UnitSession", lambda *a, **k: (opens.append(1), _boom())[1])
    monkeypatch.setattr(H, "_HEAL_BACKOFF_S", 0)
    out = default_http_search_fn("p", [], None, 50, None)
    assert out["error"] == "http_history_failed"
    assert "hung" in out["detail"]
    assert len(opens) == 4, "one open plus three heal retries"


def test_transport_death_heals_the_unit_session_silently(fake_sessions, monkeypatch):
    """FM-D: one dead session costs exactly one call. The dead session is
    torn down, a fresh handshake replaces it under the unit key, and the next
    call proceeds - with no healing chatter in either tool result."""
    monkeypatch.setattr(H, "_HEAL_BACKOFF_S", 0)
    dying = _session("p")

    def _die_once(_name, _args):
        raise ClosedResourceError

    dying.call = _die_once
    first = default_http_search_fn("p", [], None, 50, None)
    assert first["error"] == "http_history_failed"
    assert "ClosedResourceError" in first["detail"]
    assert dying.closed, "the dead session is torn down"
    assert len(fake_sessions.instances) == 2, "one fresh handshake"
    assert H._SESSION is fake_sessions.instances[1]
    second = default_http_search_fn("p", [], None, 50, None)
    assert second == {"summaries": []}, "the next call proceeds, no chatter"
    assert len(fake_sessions.instances) == 2, "no further handshake"


def test_heal_gives_up_after_three_handshakes(fake_sessions, monkeypatch):
    """FM-D: when the server stays down the heal is bounded - three
    re-handshakes, then fail-open with nothing cached."""

    def _boom(*_args, **_kwargs):
        raise ConnectionRefusedError("down")

    monkeypatch.setattr(H, "_UnitSession", _boom)
    monkeypatch.setattr(H, "_HEAL_BACKOFF_S", 0)
    out = default_http_search_fn("p", [], None, 50, None)
    assert out["error"] == "http_history_failed"
    assert H._SESSION is None, "nothing cached after an exhausted heal"


def test_a_stale_heal_never_tears_down_a_fresh_session(fake_sessions, monkeypatch):
    """Two calls die on the same dead session; the first heal installs a fresh
    one. The second (stale) heal must find a DIFFERENT session under the key and
    leave it alive. Pre-fix it tore down whatever sat under the key, so every
    heal killed the replacement, which died, which healed again - the kill
    cascade behind the arm H churn (268 handshakes in one analysis window)."""
    monkeypatch.setattr(H, "_HEAL_BACKOFF_S", 0)
    dead = _session("p")

    H._heal_unit_session("p", dead)
    fresh = H._SESSION
    assert fresh is not dead
    assert dead.closed, "the session the call actually used is torn down"
    assert len(fake_sessions.instances) == 2, "one fresh handshake"

    H._heal_unit_session("p", dead)  # the stale healer arrives late
    assert H._SESSION is fresh, "the live replacement survives a stale heal"
    assert not fresh.closed
    assert len(fake_sessions.instances) == 2, "a stale heal spends no handshake"


def test_non_transport_error_does_not_heal(fake_sessions):
    """FM-D: a programming error is not a transport death - the live session
    is kept, no handshake is spent."""
    live = _session("p")

    def _bug(_name, _args):
        raise KeyError("no such tool")

    live.call = _bug
    out = default_http_search_fn("p", [], None, 50, None)
    assert out["error"] == "http_history_failed"
    assert not live.closed
    assert len(fake_sessions.instances) == 1
