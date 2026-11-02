"""Unit tier: the client-side Steel session object and registry (#395).

The tests use the exact field shapes the CLI and the API returned live:
`viewerUrl` on the catalogue, `liveUrl`/`connectUrl` on start, and
`sessionViewerUrl`/`debugUrl`/`debuggerUrl` on the API record.
"""
from __future__ import annotations

import types

import pytest

from polymerhus.app.steel_session import (
    SteelSession,
    SteelSessionRegistry,
)


def _catalogue(**overrides):
    item = {
        "id": "sid-1",
        "mode": "local",
        "name": "wj-skill-final",
        "status": "live",
        "viewerUrl": "http://192.0.2.10:3000/",
    }
    item.update(overrides)
    return item


def _start(**overrides):
    item = {
        "id": "sid-1",
        "name": "wj-skill-final",
        "mode": "local",
        "liveUrl": "http://192.0.2.10:3000/",
        "connectUrl": "ws://192.0.2.10:3000/",
        "remainingMs": 86398783,
        "inactivityTimeoutMs": 43200000,
    }
    item.update(overrides)
    return item


def _api(**overrides):
    item = {
        "id": "sid-1",
        "status": "live",
        "createdAt": "2026-10-29T20:08:38.114Z",
        "websocketUrl": "ws://192.0.2.10:3000/",
        "debugUrl": "http://192.0.2.10:3000/v1/sessions/debug",
        "debuggerUrl": "http://192.0.2.10:3000/v1/devtools/inspector.html",
        "sessionViewerUrl": "http://192.0.2.10:3000/",
    }
    item.update(overrides)
    return item


def test_from_cli_catalogue_keeps_the_tool_name_and_viewer():
    session = SteelSession.from_cli_catalogue(_catalogue())

    assert session.session_id == "sid-1"
    assert session.name == "wj-skill-final"
    assert session.status == "live"
    assert session.viewer_url == "http://192.0.2.10:3000/"
    assert session.source == "cli.catalogue"


def test_from_cli_start_keeps_the_clock_and_cdp_url():
    session = SteelSession.from_cli_start("wj-skill-final", _start())

    assert session.session_id == "sid-1"
    assert session.name == "wj-skill-final"
    assert session.is_live
    assert session.websocket_url == "ws://192.0.2.10:3000/"
    assert session.remaining_ms == 86398783
    assert session.inactivity_timeout_ms == 43200000
    assert session.source == "cli.start"


def test_from_api_keeps_the_debug_and_viewer_attributes():
    session = SteelSession.from_api(_api())

    assert session.debug_url.endswith("/v1/sessions/debug")
    assert session.debugger_url.endswith("/v1/devtools/inspector.html")
    assert session.viewer_url == "http://192.0.2.10:3000/"
    assert session.created_at.startswith("2026-10-29")
    assert session.source == "api"


def test_from_sdk_reads_the_resource_attributes():
    raw = types.SimpleNamespace(
        id="sid-1", status="live",
        session_viewer_url="https://app.steel.dev/sessions/sid-1",
        websocket_url="wss://connect.steel.dev?sessionId=sid-1",
        debug_url="", debugger_url="", created_at="2026-10-29T20:08:38Z",
    )

    session = SteelSession.from_sdk(raw)

    assert session.session_id == "sid-1"
    assert session.viewer_url.endswith("/sessions/sid-1")
    assert session.websocket_url.endswith("sessionId=sid-1")
    assert session.source == "sdk"


def test_a_cloud_viewer_url_that_carries_the_id_is_addressable():
    session = SteelSession.from_cli_catalogue(_catalogue(
        viewerUrl="https://app.steel.dev/sessions/sid-1",
    ))

    view = session.live_view

    assert view is not None
    assert view.kind == "viewer"
    assert view.addressable is True
    assert view.session_id == "sid-1"


def test_a_shared_viewer_prefers_the_shared_player_and_is_not_addressable():
    session = SteelSession.from_api(_api())

    view = session.live_view

    assert view is not None
    assert view.kind == "player"
    assert view.url.endswith("/v1/sessions/debug")
    assert view.addressable is False
    assert view.session_id == "sid-1"
    assert view.session_name is None


def test_a_shared_viewer_without_a_player_is_still_not_addressable():
    session = SteelSession.from_api(_api(debugUrl="", debuggerUrl=""))

    view = session.live_view

    assert view is not None
    assert view.kind == "viewer"
    assert view.addressable is False


def test_a_player_url_that_carries_the_id_is_addressable():
    session = SteelSession.from_api(_api(
        debugUrl="http://192.0.2.10:3000/v1/sessions/debug?sessionId=sid-1",
    ))

    view = session.live_view

    assert view is not None
    assert view.kind == "player"
    assert view.addressable is True


def test_a_debugger_is_the_last_resort():
    session = SteelSession.from_api(_api(
        sessionViewerUrl="", debugUrl="",
        debuggerUrl="http://192.0.2.10:3000/v1/devtools/inspector.html",
    ))

    view = session.live_view

    assert view is not None
    assert view.kind == "debugger"
    assert view.addressable is False


def test_merge_fills_the_api_urls_without_losing_the_start_clock():
    start = SteelSession.from_cli_start("wj-skill-final", _start())
    api = SteelSession.from_api(_api(name=None))

    merged = start.merge(api)

    assert merged.session_id == "sid-1"
    assert merged.name == "wj-skill-final"
    assert merged.remaining_ms == 86398783
    assert merged.debug_url.endswith("/v1/sessions/debug")
    assert merged.websocket_url == "ws://192.0.2.10:3000/"
    assert merged.debug_url == api.debug_url


def test_merge_refuses_two_different_sessions():
    one = SteelSession.from_cli_catalogue(_catalogue(id="sid-1"))
    two = SteelSession.from_cli_catalogue(_catalogue(id="sid-2"))

    with pytest.raises(ValueError):
        one.merge(two)


def test_public_view_has_identity_and_no_secret_material():
    session = SteelSession.from_api(_api())

    public = session.public_view()

    assert public["session_id"] == "sid-1"
    assert public["live_view"]["kind"] == "player"
    assert public["live_view"]["addressable"] is False
    assert "cookie" not in public
    assert "token" not in public


def test_registry_tracks_start_api_stop_and_views():
    registry = SteelSessionRegistry()
    started = registry.observe_start("wj-skill-final", _start())
    assert started.is_live
    assert len(registry.views()) == 1

    observed = registry.observe_api("wj-skill-final", _api())
    assert observed.debug_url.endswith("/v1/sessions/debug")
    assert observed.remaining_ms == 86398783

    transition = registry.observe_stop("wj-skill-final")
    assert transition is not None
    assert transition.kind == "released"
    assert registry.get("wj-skill-final").status == "released"
    assert registry.views() == []


def test_registry_marks_a_vanished_live_session_lost():
    registry = SteelSessionRegistry()
    registry.observe_start("wj-skill-final", _start())

    transitions = registry.observe_catalogue([])

    assert transitions
    assert transitions[-1].kind == "vanished"
    assert registry.get("wj-skill-final").status == "lost"
    assert registry.live() == []


def test_registry_replaces_a_reused_name_with_the_new_runtime_id():
    registry = SteelSessionRegistry()
    registry.observe_start("wj-skill-final", _start())
    registry.observe_stop("wj-skill-final")

    transitions = registry.observe_catalogue(_catalogue(id="sid-2"))

    assert transitions[-1].kind == "appeared"
    assert registry.get("wj-skill-final").session_id == "sid-2"
    assert registry.get("wj-skill-final").is_live


def test_registry_catalogue_preserves_the_debug_url_learned_from_the_api():
    registry = SteelSessionRegistry()
    registry.observe_start("wj-skill-final", _start())
    registry.observe_api("wj-skill-final", _api())

    registry.observe_catalogue(_catalogue())

    session = registry.get("wj-skill-final")
    assert session.debug_url.endswith("/v1/sessions/debug")
    assert session.remaining_ms == 86398783
    assert session.status == "live"
