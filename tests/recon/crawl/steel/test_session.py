"""Seam under test: the `SteelSession` CLI envelope through a fake `exec_fn`.

The client is the only place a steel-crawl command is rendered and the only
place a CLI error becomes a typed failure. Every test here drives the public
client and asserts the exact command the fake recorded; no test reaches into a
private method or asserts an internal call sequence.
"""
from __future__ import annotations

import json
import logging

import pytest

from polymerhus.recon.crawl.steel.session import (
    BrowserStuck,
    CommandFailed,
    GuardError,
    InvalidCommand,
    SessionMissing,
    SessionStillLive,
    SessionTaken,
    SteelSession,
    SteelSessionClient,
    SteelSessionRegistry,
    TargetLost,
    UnknownSession,
    steel_prefix,
)
from tests.recon.crawl.steel.fixtures import load_cli
from tests.recon.crawl.steel.support import FakeExecFn

CATALOGUE_COMMAND = ["steel", "browser", "sessions", "--json"]


def test_catalogue_lists_live_sessions_with_the_global_read():
    exec_fn = FakeExecFn(load_cli("catalogue"))
    client = SteelSessionClient(exec_fn=exec_fn)

    sessions = client.catalogue()

    assert exec_fn.commands == [CATALOGUE_COMMAND]
    assert [session.name for session in sessions] == ["crawl-fixture"]
    assert sessions[0].session_id == "9f8e7d6c-5b4a-4321-8765-fedcba987654"
    assert sessions[0].status == "live"


def test_catalogue_uses_the_injected_prefix_with_an_api_url():
    exec_fn = FakeExecFn(load_cli("catalogue"))
    api_url = "https://steel.example.test/v1"
    client = SteelSessionClient(
        exec_fn=exec_fn, prefix=steel_prefix(api_url=api_url)
    )

    client.catalogue()

    assert exec_fn.commands == [
        ["steel", "--api-url", api_url, "browser", "sessions", "--json"]
    ]


def test_attach_binds_name_runtime_id_websocket_and_clocks():
    exec_fn = FakeExecFn(load_cli("catalogue"), load_cli("session"))
    client = SteelSessionClient(exec_fn=exec_fn)

    session = client.attach("crawl-fixture")

    assert exec_fn.commands == [
        CATALOGUE_COMMAND,
        [
            "steel",
            "browser",
            "sessions",
            "get",
            "--session",
            "crawl-fixture",
            "--json",
        ],
    ]
    assert session.name == "crawl-fixture"
    assert session.session_id == "9f8e7d6c-5b4a-4321-8765-fedcba987654"
    assert session.status == "live"
    assert session.source == "catalogue"
    assert session.viewer_url == (
        "https://app.example.test/sessions/9f8e7d6c-5b4a-4321-8765-fedcba987654"
    )
    assert session.debug_url.endswith("/debug")
    assert session.debugger_url.endswith("/debugger")
    assert session.created_at == "2026-11-02T10:00:00Z"
    assert session.remaining_ms == 298900
    assert session.inactivity_timeout_ms == 300000
    assert session.websocket_url is not None
    assert session.websocket_url.get_secret_value() == (
        "wss://cdp.example.test/v1/sessions/9f8e7d6c-5b4a-4321-8765-fedcba987654"
    )
    assert client.attached is session


def test_the_websocket_never_appears_in_repr_str_a_dump_or_a_log(caplog):
    exec_fn = FakeExecFn(load_cli("catalogue"), load_cli("session"))
    client = SteelSessionClient(exec_fn=exec_fn)
    session = client.attach("crawl-fixture")
    assert session.websocket_url is not None
    secret = session.websocket_url.get_secret_value()

    logger = logging.getLogger("polymerhus.recon.crawl.steel.session")
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        logger.info("attached %s", session)

    assert secret not in repr(session)
    assert secret not in str(session)
    assert secret not in json.dumps(session.model_dump(mode="json"))
    assert secret not in caplog.text


def test_attach_a_name_never_observed_live_is_unknown_session():
    exec_fn = FakeExecFn({"success": True, "data": []})
    client = SteelSessionClient(exec_fn=exec_fn)

    with pytest.raises(UnknownSession) as excinfo:
        client.attach("ghost")

    assert excinfo.value.code == "unknown_session"
    assert exec_fn.commands == [CATALOGUE_COMMAND]


def test_attach_a_vanished_live_name_is_session_missing():
    exec_fn = FakeExecFn(load_cli("catalogue"), {"success": True, "data": []})
    client = SteelSessionClient(exec_fn=exec_fn)
    client.catalogue()

    with pytest.raises(SessionMissing) as excinfo:
        client.attach("crawl-fixture")

    assert excinfo.value.code == "session_missing"
    assert exec_fn.commands == [CATALOGUE_COMMAND, CATALOGUE_COMMAND]


def test_a_session_bound_command_carries_the_owned_session_and_json():
    exec_fn = FakeExecFn(
        load_cli("catalogue"), load_cli("session"), load_cli("navigate")
    )
    client = SteelSessionClient(exec_fn=exec_fn)
    client.attach("crawl-fixture")

    envelope = client.execute("navigate", "https://example.test/")

    assert envelope["data"]["url"] == "https://example.test/products?page=2"
    assert exec_fn.last_command == [
        "steel",
        "browser",
        "navigate",
        "https://example.test/",
        "--session",
        "crawl-fixture",
        "--json",
    ]


def test_a_session_bound_command_without_a_session_is_refused_before_execution():
    exec_fn = FakeExecFn()
    client = SteelSessionClient(exec_fn=exec_fn)

    with pytest.raises(InvalidCommand) as excinfo:
        client.execute("snapshot", "-i")
    with pytest.raises(InvalidCommand):
        client.stop()

    assert excinfo.value.code == "invalid_command"
    assert exec_fn.commands == []


def test_stop_releases_the_owned_name_and_proves_the_catalogue_clean():
    exec_fn = FakeExecFn(
        load_cli("catalogue"),
        load_cli("session"),
        load_cli("stop"),
        {"success": True, "data": []},
    )
    client = SteelSessionClient(exec_fn=exec_fn)
    client.attach("crawl-fixture")

    client.stop()

    assert exec_fn.commands == [
        CATALOGUE_COMMAND,
        [
            "steel",
            "browser",
            "sessions",
            "get",
            "--session",
            "crawl-fixture",
            "--json",
        ],
        ["steel", "browser", "stop", "--session", "crawl-fixture", "--json"],
        CATALOGUE_COMMAND,
    ]
    assert client.attached is None
    assert client.registry.get("crawl-fixture").status == "released"
    with pytest.raises(InvalidCommand):
        client.execute("snapshot", "-i")


def test_stop_fails_loudly_when_the_catalogue_still_lists_the_name():
    exec_fn = FakeExecFn(
        load_cli("catalogue"),
        load_cli("session"),
        load_cli("stop"),
        load_cli("catalogue"),
    )
    client = SteelSessionClient(exec_fn=exec_fn)
    client.attach("crawl-fixture")

    with pytest.raises(SessionStillLive) as excinfo:
        client.stop()

    assert "crawl-fixture" in str(excinfo.value)
    assert client.attached is not None


CLI_ERRORS = [
    ("unknown_session", UnknownSession),
    ("session_missing", SessionMissing),
    ("session_taken", SessionTaken),
    ("target_lost", TargetLost),
    ("browser_stuck", BrowserStuck),
    ("invalid_command", InvalidCommand),
    ("command_failed", CommandFailed),
    ("guard_error", GuardError),
]


@pytest.mark.parametrize("code, error_type", CLI_ERRORS)
def test_every_named_cli_error_maps_to_its_typed_failure(code, error_type):
    exec_fn = FakeExecFn({"success": False, "error": code, "returncode": 1})
    client = SteelSessionClient(exec_fn=exec_fn)

    with pytest.raises(error_type) as excinfo:
        client.catalogue()

    assert excinfo.value.code == code


def test_an_unmapped_cli_error_is_command_failed():
    exec_fn = FakeExecFn({"success": False, "error": "surprise_failure"})
    client = SteelSessionClient(exec_fn=exec_fn)

    with pytest.raises(CommandFailed) as excinfo:
        client.catalogue()

    assert excinfo.value.code == "command_failed"
    assert "surprise_failure" in str(excinfo.value)


def test_a_mapping_error_object_maps_by_its_code():
    exec_fn = FakeExecFn(
        {
            "success": False,
            "error": {"code": "guard_error", "message": "the guard rejected it"},
        }
    )
    client = SteelSessionClient(exec_fn=exec_fn)

    with pytest.raises(GuardError, match="the guard rejected it") as excinfo:
        client.catalogue()

    assert excinfo.value.code == "guard_error"


def test_the_envelope_error_is_authoritative_over_the_return_code_and_text():
    failing = FakeExecFn(
        {
            "success": False,
            "error": "session_missing",
            "returncode": 0,
            "stdout": "everything looks fine",
        }
    )
    with pytest.raises(SessionMissing):
        SteelSessionClient(exec_fn=failing).catalogue()

    success_with_nonzero_exit = FakeExecFn(
        {"success": True, "data": [], "returncode": 1}
    )
    assert SteelSessionClient(exec_fn=success_with_nonzero_exit).catalogue() == []


def test_the_crawl_never_starts_a_session():
    exec_fn = FakeExecFn(
        load_cli("catalogue"),
        load_cli("session"),
        load_cli("navigate"),
        load_cli("stop"),
        {"success": True, "data": []},
    )
    client = SteelSessionClient(exec_fn=exec_fn)
    client.attach("crawl-fixture")
    client.execute("navigate", "https://example.test/")
    commands_before_start = list(exec_fn.commands)
    with pytest.raises(InvalidCommand):
        client.execute("start", "--session-timeout", "600000")
    assert exec_fn.commands == commands_before_start
    client.stop()

    assert not hasattr(client, "start")
    assert all("start" not in command for command in exec_fn.commands)
    assert all(command[2] != "start" for command in exec_fn.commands)
    assert all("--json" in command for command in exec_fn.commands)
    global_reads = [
        command for command in exec_fn.commands if "--session" not in command
    ]
    assert global_reads == [CATALOGUE_COMMAND, CATALOGUE_COMMAND]
    for command in exec_fn.commands:
        if "--session" in command:
            assert command[command.index("--session") + 1] == "crawl-fixture"


def test_the_runtime_id_is_the_tiebreaker_when_a_name_is_reused():
    reused_id = "11111111-2222-4333-8444-555555555555"
    reused_catalogue = {
        "success": True,
        "data": [
            {
                "id": reused_id,
                "mode": "local",
                "name": "crawl-fixture",
                "status": "live",
                "viewerUrl": f"https://app.example.test/sessions/{reused_id}",
            }
        ],
    }
    reused_record = {
        "success": True,
        "data": {
            "id": reused_id,
            "name": "crawl-fixture",
            "status": "live",
            "viewerUrl": f"https://app.example.test/sessions/{reused_id}",
            "websocketUrl": f"wss://cdp.example.test/v1/sessions/{reused_id}",
            "createdAt": "2026-11-02T11:00:00Z",
            "remainingMs": 120000,
            "inactivityTimeoutMs": 300000,
            "source": "catalogue",
        },
    }
    exec_fn = FakeExecFn(load_cli("catalogue"), reused_catalogue, reused_record)
    registry = SteelSessionRegistry()
    client = SteelSessionClient(exec_fn=exec_fn, registry=registry)
    client.catalogue()

    session = client.attach("crawl-fixture")

    assert session.session_id == reused_id
    assert session.remaining_ms == 120000
    assert registry.get("crawl-fixture").session_id == reused_id


def test_the_registry_observes_a_start_without_running_one():
    registry = SteelSessionRegistry()
    record = SteelSession.from_start(
        "crawl-fixture",
        {
            "id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "liveUrl": "https://app.example.test/sessions/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "connectUrl": "wss://cdp.example.test/v1/sessions/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "remainingMs": 299000,
            "inactivityTimeoutMs": 300000,
        },
    )

    observed = registry.observe_start(record)

    assert observed.is_live
    assert observed.websocket_url is not None
    assert observed.websocket_url.get_secret_value() == (
        "wss://cdp.example.test/v1/sessions/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    )
    assert registry.get("crawl-fixture").session_id == record.session_id
    assert registry.was_live("crawl-fixture")
    assert not hasattr(registry, "start")
    assert not hasattr(registry, "stop")
    assert not hasattr(registry, "release")
