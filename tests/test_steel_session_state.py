"""Unit tests for the state-preserving Steel session client (#395).

Seam under test: `polymerhus.app.steel_session_state`. No docker, no network,
no cloud key: `httpx.MockTransport` answers the API calls, so every request is
asserted by path, method, and body.
"""
from __future__ import annotations

import json
import stat

import httpx
import pytest

from polymerhus.app import steel_session_state as st
from polymerhus.app.steel_endpoint import ENV_VAR as ENDPOINT_ENV


class Recorder:
    def __init__(self, *, context: dict | None = None, context_status: int = 200,
                 release_status: int = 200):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.context = context if context is not None else {
            "cookies": [{"name": "sid", "value": "v1", "domain": "example.test"}],
            "localStorage": {},
            "sessionStorage": {},
        }
        self.context_status = context_status
        self.release_status = release_status

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        if request.url.path.endswith("/context"):
            return httpx.Response(self.context_status, json=self.context)
        if request.url.path.endswith("/release"):
            return httpx.Response(self.release_status, json={"success": True, "status": "released"})
        if request.method == "POST" and request.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"id": "new-1", "status": "live"})
        return httpx.Response(404, json={"error": "not found"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_capture_reads_the_context_endpoint():
    rec = Recorder()
    with rec.client() as client:
        out = st.capture_session_context("s1", base_url="http://steel.test", client=client)
    assert out["cookies"][0]["name"] == "sid"
    assert rec.calls == [("GET", "/v1/sessions/s1/context", None)]


def test_release_posts_to_the_release_endpoint():
    rec = Recorder()
    with rec.client() as client:
        out = st.release_session("s1", base_url="http://steel.test", client=client)
    assert out["status"] == "released"
    assert rec.calls == [("POST", "/v1/sessions/s1/release", None)]


def test_create_sends_the_session_context_shape():
    rec = Recorder()
    context = {"cookies": [{"name": "sid", "value": "v1"}]}
    with rec.client() as client:
        st.create_session(context, base_url="http://steel.test", client=client)
    method, path, body = rec.calls[0]
    assert (method, path) == ("POST", "/v1/sessions")
    assert body == {"sessionContext": context}


def test_create_without_context_sends_an_empty_body():
    rec = Recorder()
    with rec.client() as client:
        st.create_session(base_url="http://steel.test", client=client)
    assert rec.calls[0][2] == {}


def test_teardown_captures_stores_then_releases(tmp_path):
    rec = Recorder()
    store = tmp_path / "state" / "flow.json"
    with rec.client() as client:
        out = st.teardown_with_state(
            "s1", store, base_url="http://steel.test", client=client
        )
    assert [c[1] for c in rec.calls] == [
        "/v1/sessions/s1/context",
        "/v1/sessions/s1/release",
    ]
    assert json.loads(store.read_text()) == rec.context
    assert out["state_path"] == str(store)
    assert out["release"]["success"] is True


def test_teardown_releases_even_when_capture_fails(tmp_path):
    rec = Recorder(context_status=500)
    store = tmp_path / "flow.json"
    with rec.client() as client:
        with pytest.raises(st.SteelStateError, match="session state was not saved"):
            st.teardown_with_state(
                "s1", store, base_url="http://steel.test", client=client
            )
    assert [c[1] for c in rec.calls] == [
        "/v1/sessions/s1/context",
        "/v1/sessions/s1/release",
    ]
    assert not store.exists()


def test_restore_reads_the_store_and_posts_the_context(tmp_path):
    rec = Recorder()
    store = st.save_session_context(tmp_path / "flow.json", {"cookies": [{"name": "c"}]})
    with rec.client() as client:
        st.restore_session(store, base_url="http://steel.test", client=client)
    assert rec.calls[0][2] == {"sessionContext": {"cookies": [{"name": "c"}]}}


def test_endpoint_comes_from_the_shared_resolver(monkeypatch):
    monkeypatch.setenv(ENDPOINT_ENV, "http://steel.test:3000/v1")
    rec = Recorder()
    with rec.client() as client:
        st.capture_session_context("s1", client=client)
    # The resolver returns the origin; the client appends the /v1 mount.
    assert rec.calls[0][1] == "/v1/sessions/s1/context"


def test_unset_endpoint_refuses(monkeypatch):
    monkeypatch.delenv("STEEL_BROWSER_API_URL", raising=False)
    with pytest.raises(st.SteelStateError, match="STEEL_BROWSER_API_URL is unset"):
        st.capture_session_context("s1")


def test_api_key_rides_the_authorization_header(monkeypatch):
    monkeypatch.setenv(st.API_KEY_ENV, "ste-test-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        st.release_session("s1", base_url="http://steel.test", client=client)
    assert seen["auth"] == "Bearer ste-test-key"


def test_http_error_and_non_json_are_typed():
    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with httpx.Client(transport=httpx.MockTransport(error_handler)) as client:
        with pytest.raises(st.SteelStateError, match="503"):
            st.release_session("s1", base_url="http://steel.test", client=client)

    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nope</html>")

    with httpx.Client(transport=httpx.MockTransport(html_handler)) as client:
        with pytest.raises(st.SteelStateError, match="non-JSON"):
            st.capture_session_context("s1", base_url="http://steel.test", client=client)


def test_load_rejects_a_missing_or_malformed_store(tmp_path):
    with pytest.raises(st.SteelStateError, match="cannot read"):
        st.load_session_context(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]")
    with pytest.raises(st.SteelStateError, match="not a JSON object"):
        st.load_session_context(bad)


def test_project_session_context_keeps_only_the_four_state_fields():
    raw = {
        "cookies": [{"name": "sid", "value": "v1"}],
        "localStorage": {"https://x.example": {"k": "v"}},
        "sessionStorage": {"https://x.example": {"s": "v"}},
        "indexedDB": {"https://x.example": []},
        "history": ["https://x.example"],
        "fingerprint": {"ua": "x"},
    }
    assert st.project_session_context(raw) == {
        "cookies": raw["cookies"],
        "localStorage": raw["localStorage"],
        "sessionStorage": raw["sessionStorage"],
        "indexedDB": raw["indexedDB"],
    }


def test_project_session_context_accepts_the_sdk_snake_case_shape():
    raw = {
        "cookies": [],
        "local_storage": {"https://x.example": {"k": "v"}},
        "session_storage": {},
        "indexed_db": {},
    }
    assert st.project_session_context(raw) == {
        "cookies": [],
        "localStorage": {"https://x.example": {"k": "v"}},
        "sessionStorage": {},
        "indexedDB": {},
    }


def test_to_sdk_session_context_maps_the_canonical_fields():
    assert st.to_sdk_session_context({
        "cookies": [],
        "localStorage": {},
        "sessionStorage": {},
        "indexedDB": {},
        "extra": 1,
    }) == {
        "cookies": [],
        "local_storage": {},
        "session_storage": {},
        "indexed_db": {},
    }


def test_save_session_context_is_owner_only(tmp_path):
    path = st.save_session_context(tmp_path / "state.json", {
        "cookies": [],
        "localStorage": {},
        "sessionStorage": {},
        "indexedDB": {},
        "extra": "dropped",
    })
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == {
        "cookies": [],
        "localStorage": {},
        "sessionStorage": {},
        "indexedDB": {},
    }


def test_state_path_is_the_one_per_account_location(tmp_path):
    path = st.state_path("proj-1", "alice", root=tmp_path)
    assert path == tmp_path / "proj-1" / "steel-state" / "alice.json"
    with pytest.raises(ValueError):
        st.state_path("proj-1", "../alice", root=tmp_path)


def test_browser_session_name_is_stable_and_account_scoped():
    assert st.browser_session_name("proj-1") == "steel-proj-1"
    assert st.browser_session_name("proj-1", "alice-first_authn_bootstrap") == (
        "steel-proj-1-alice-first_authn_bootstrap"
    )
    assert st.browser_session_name("proj-1", "alice") == st.browser_session_name(
        "proj-1", "alice"
    )


def test_browser_session_name_sanitises_unsafe_characters():
    assert st.browser_session_name("My Project/One", "Alice @ Example") == (
        "steel-my-project-one-alice-example"
    )
    assert st.browser_session_name("...") == "steel-project"


def test_browser_session_name_is_bounded_and_store_safe():
    import re

    name = st.browser_session_name("p" * 200, "a" * 200)

    assert len(name) <= 128
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name)
    assert name == st.browser_session_name("p" * 200, "a" * 200)
