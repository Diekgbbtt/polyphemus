"""Integration: state-preserving teardown over real HTTP (#395).

A localhost stub speaks the four Steel API calls (`create`, `context`,
`release`) so the client's ordering and the restore round-trip are exercised
over a real socket, with no docker, no browser, and no cloud key.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from polymerhus.app import steel_session_state as st


class _ApiState:
    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.context: dict | None = None
        self.released: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _ApiState

    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict | None:
        length = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(length)) if length else None

    def do_GET(self):
        self.state.calls.append(("GET", self.path, None))
        if self.path.startswith("/v1/sessions/") and self.path.endswith("/context"):
            if self.state.context is None:
                return self._send(404, {"error": "no session"})
            return self._send(200, self.state.context)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self._body()
        self.state.calls.append(("POST", self.path, body))
        if self.path == "/v1/sessions":
            if body and "sessionContext" in body:
                self.state.context = body["sessionContext"]
            return self._send(200, {"id": "stub-1", "status": "live"})
        if self.path.startswith("/v1/sessions/") and self.path.endswith("/release"):
            session_id = self.path.split("/")[3]
            self.state.released.append(session_id)
            return self._send(200, {"success": True, "status": "released"})
        return self._send(404, {"error": "not found"})


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.delenv(st.API_KEY_ENV, raising=False)
    handler = type("Handler", (_Handler,), {"state": _ApiState()})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", handler.state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_capture_store_release_restore_round_trip(api, tmp_path):
    base_url, state = api
    context = {"cookies": [{"name": "sid", "value": "v1", "domain": "target.test"}]}

    created = st.create_session(context, base_url=base_url)
    assert created["id"] == "stub-1"

    store = tmp_path / "state" / "flow.json"
    torn = st.teardown_with_state("stub-1", store, base_url=base_url)
    assert torn["state_path"] == str(store)
    assert state.released == ["stub-1"]
    assert json.loads(store.read_text()) == context

    restored = st.restore_session(store, base_url=base_url)
    assert restored["id"] == "stub-1"
    assert state.context == context

    assert [(method, path) for method, path, _ in state.calls] == [
        ("POST", "/v1/sessions"),
        ("GET", "/v1/sessions/stub-1/context"),
        ("POST", "/v1/sessions/stub-1/release"),
        ("POST", "/v1/sessions"),
    ]


def test_capture_failure_still_releases_the_session(api, tmp_path):
    base_url, state = api
    # No session was created, so the stub answers the context read with 404.
    with pytest.raises(st.SteelStateError, match="session state was not saved"):
        st.teardown_with_state("missing-1", tmp_path / "never.json", base_url=base_url)
    assert state.released == ["missing-1"]
    assert not (tmp_path / "never.json").exists()
