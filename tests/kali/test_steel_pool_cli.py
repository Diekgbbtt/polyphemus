"""Unit tier: the Steel CLI mount, execute, capture, and release.

The CLI is a fake executable. The worker API is a local HTTP server. No Steel
worker is needed. The tests pin the command grammar, the state restore, the
capture fallback, and the compensation paths.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kali.steel_pool.api import WorkerAPI, WorkerAPIError
from kali.steel_pool.cli import (
    CaptureError,
    CapturedContext,
    CliError,
    CliSession,
    RestoreError,
    RestoreReport,
    SteelCli,
    _normalise_storage,
    _split_key,
    _synthetic_origin,
)
from kali.steel_pool.store import BrowserSessionRecord

FAKE_CLI_TEMPLATE = """#!{python}
import json, os, sys, time
calls = os.environ["FAKE_CLI_CALLS"]
with open(calls, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
program_log = os.environ.get("FAKE_CLI_PROGRAM_LOG")
if program_log:
    with open(program_log, "a", encoding="utf-8") as handle:
        handle.write(sys.argv[0] + "\\n")
sleep = os.environ.get("FAKE_CLI_SLEEP")
if sleep:
    time.sleep(float(sleep))
joined = " ".join(sys.argv[1:])
fail_on = os.environ.get("FAKE_CLI_FAIL_ON", "")
if fail_on and fail_on in joined:
    sys.stdout.write(json.dumps({{"success": False, "error": "boom"}}))
    sys.exit(1)
responses = json.loads(os.environ.get("FAKE_CLI_RESPONSES", "{{}}"))
for marker, response in responses.items():
    if marker in joined:
        sys.stdout.write(json.dumps(response))
        sys.exit(0 if response.get("success", True) else 1)
sys.stdout.write(os.environ.get("FAKE_CLI_RESPONSE", json.dumps({{"success": True, "data": {{}}}})))
"""


def _write_cli(path: Path) -> Path:
    path.write_text(FAKE_CLI_TEMPLATE.format(python=sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_cli(tmp_path):
    binary = _write_cli(tmp_path / "steel")
    calls = tmp_path / "calls.jsonl"
    return binary, calls


def _env(calls: Path, **extra) -> dict:
    return {"FAKE_CLI_CALLS": str(calls), **extra}


def _calls(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _session(name: str = "hunt", session_id: str = "steel-1") -> CliSession:
    return CliSession(name=name, session_id=session_id)


@contextmanager
def _api_server(*, status: int = 200, body: object = None):
    requests: list[tuple[str, str, bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length) if length else b""
            requests.append((self.command, self.path, payload))
            data = b"" if body is None else json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        do_GET = _handle
        do_POST = _handle

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_start_builds_the_pinned_command(fake_cli):
    binary, calls = fake_cli
    response = {"success": True, "data": {"id": "steel-1", "name": "hunt"}}
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls, FAKE_CLI_RESPONSE=json.dumps(response)),
    )

    session = cli.start("hunt")

    assert session == _session()
    assert _calls(calls) == [
        [
            "--api-url",
            "http://127.0.0.1:3110/v1",
            "browser",
            "start",
            "--session",
            "hunt",
            "--session-timeout",
            "3600000",
            "--inactivity-timeout",
            "0",
            "--json",
        ]
    ]


def test_start_rejects_a_payload_without_an_id(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls, FAKE_CLI_RESPONSE='{"success": true, "data": {}}'),
    )

    with pytest.raises(CliError):
        cli.start("hunt")


def test_start_rejects_a_failed_envelope(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(
            calls,
            FAKE_CLI_RESPONSE='{"success": false, "error": "no worker"}',
        ),
    )

    with pytest.raises(CliError) as caught:
        cli.start("hunt")

    assert "no worker" in str(caught.value)


def test_start_rejects_a_non_json_output(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls, FAKE_CLI_RESPONSE="not-json"),
    )

    with pytest.raises(CliError):
        cli.start("hunt")


def test_start_rejects_an_invalid_name(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls),
    )

    with pytest.raises(Exception):
        cli.start("../escape")


def test_exec_appends_the_session_and_returns_the_error_envelope(fake_cli):
    binary, calls = fake_cli
    response = {"success": False, "error": "bad selector", "error_code": "x"}
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls, FAKE_CLI_RESPONSE=json.dumps(response)),
    )

    payload = cli.exec(_session(), ["click", "#missing"])

    assert payload == response
    assert _calls(calls) == [
        [
            "--api-url",
            "http://127.0.0.1:3110/v1",
            "browser",
            "click",
            "#missing",
            "--session",
            "hunt",
            "--json",
        ]
    ]


def test_exec_inserts_the_session_before_a_variadic_boundary(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls),
    )

    cli.exec(_session(), ["fill", "--", "#name", "a value with spaces"])

    assert _calls(calls)[0] == [
        "--api-url",
        "http://127.0.0.1:3110/v1",
        "browser",
        "fill",
        "--session",
        "hunt",
        "--json",
        "--",
        "#name",
        "a value with spaces",
    ]


def test_exec_times_out(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        timeout_s=0.2,
        env=_env(calls, FAKE_CLI_SLEEP="5"),
    )

    with pytest.raises(CliError):
        cli.exec(_session(), ["get", "url"])


def test_guard_mode_uses_the_guard_prefix(fake_cli, tmp_path):
    binary, calls = fake_cli
    guard = _write_cli(tmp_path / "guard.py")
    programs = tmp_path / "programs.log"
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        guard_path=guard,
        python=sys.executable,
        env=_env(
            calls,
            FAKE_CLI_PROGRAM_LOG=str(programs),
            FAKE_CLI_RESPONSE='{"success": true, "data": {"id": "s1"}}',
        ),
    )

    cli.start("hunt")

    first = _calls(calls)[0]
    assert programs.read_text(encoding="utf-8").strip() == str(guard)
    assert first[:1] == ["--api-url"]
    assert first[1] == "http://127.0.0.1:3110/v1"
    assert first[2:4] == ["browser", "start"]


def test_restore_sets_cookies_and_local_storage(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls),
    )
    record = BrowserSessionRecord(
        name="hunt",
        cookies=[
            {
                "name": "sid",
                "value": "a value with spaces",
                "domain": "app.test",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "expires": 1893456000,
            },
            {"name": "theme", "value": "dark"},
        ],
        local_storage={
            "https://app.test": {"token": "secret token", "mode": "dark"},
        },
    )

    report = cli.restore(_session(), record)

    assert report == RestoreReport(
        cookies_set=2,
        origins_visited=1,
        storage_keys_set=2,
        warnings=("1 cookie attribute set is not restorable through the CLI",),
    )
    calls_seen = _calls(calls)
    assert calls_seen[0][3:] == [
        "cookies",
        "set",
        "--domain",
        "app.test",
        "--path",
        "/",
        "--secure",
        "--http-only",
        "--session",
        "hunt",
        "--json",
        "--",
        "sid",
        "a value with spaces",
    ]
    assert calls_seen[1][3:] == [
        "cookies",
        "set",
        "--session",
        "hunt",
        "--json",
        "--",
        "theme",
        "dark",
    ]
    assert calls_seen[2][3:] == [
        "navigate",
        "https://app.test",
        "--session",
        "hunt",
        "--json",
    ]
    assert calls_seen[3][3:] == [
        "storage",
        "local",
        "set",
        "--session",
        "hunt",
        "--json",
        "--",
        "token",
        "secret token",
    ]
    assert calls_seen[4][3:] == [
        "storage",
        "local",
        "set",
        "--session",
        "hunt",
        "--json",
        "--",
        "mode",
        "dark",
    ]
    assert calls_seen[5][3:] == [
        "navigate",
        "about:blank",
        "--session",
        "hunt",
        "--json",
    ]


def test_restore_accepts_the_sdk_http_only_alias(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls),
    )
    record = BrowserSessionRecord(
        name="hunt",
        cookies=[{"name": "sid", "value": "v", "http_only": True}],
    )

    cli.restore(_session(), record)

    assert "--http-only" in _calls(calls)[0]


def test_restore_without_state_makes_no_calls(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls),
    )

    report = cli.restore(_session(), BrowserSessionRecord(name="hunt"))

    assert report == RestoreReport(0, 0, 0, ())
    assert _calls(calls) == []


def test_restore_fails_closed_on_a_malformed_cookie(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls),
    )
    record = BrowserSessionRecord(name="hunt", cookies=[{"name": "sid"}])

    with pytest.raises(RestoreError):
        cli.restore(_session(), record)


def test_restore_fails_closed_on_a_non_string_storage_value(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls),
    )
    record = BrowserSessionRecord(
        name="hunt", local_storage={"https://app.test": {"n": 1}}
    )

    with pytest.raises(RestoreError):
        cli.restore(_session(), record)


def test_restore_failure_raises_restore_error(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli(
        "http://127.0.0.1:3110",
        binary=binary,
        env=_env(calls, FAKE_CLI_FAIL_ON="cookies"),
    )
    record = BrowserSessionRecord(
        name="hunt", cookies=[{"name": "sid", "value": "v"}]
    )

    with pytest.raises(RestoreError):
        cli.restore(_session(), record)


def test_capture_uses_the_api_context(fake_cli):
    binary, calls = fake_cli
    context = {"cookies": [{"name": "sid", "value": "v"}], "localStorage": {}}
    with _api_server(body=context) as (url, requests):
        cli = SteelCli(url, binary=binary, env=_env(calls))

        captured = cli.capture(_session())

    assert captured == CapturedContext(context=context, source="api")
    assert _calls(calls) == []
    assert requests == [("GET", "/v1/sessions/steel-1/context", b"")]


def test_capture_normalises_a_host_key_to_the_current_origin(fake_cli):
    binary, calls = fake_cli
    context = {
        "cookies": [],
        "localStorage": {"localhost": {"token": "t"}},
        "sessionStorage": {"localhost": {"flow": "f"}},
    }
    responses = {"get url": {"success": True, "data": "http://localhost:3000/app"}}
    with _api_server(body=context) as (url, _):
        cli = SteelCli(
            url,
            binary=binary,
            env=_env(calls, FAKE_CLI_RESPONSES=json.dumps(responses)),
        )

        captured = cli.capture(_session())

    assert captured.context == {
        "cookies": [],
        "localStorage": {"http://localhost:3000": {"token": "t"}},
        "sessionStorage": {"http://localhost:3000": {"flow": "f"}},
    }
    assert _calls(calls)[0][3:7] == ["get", "url", "--session", "hunt"]


def test_capture_falls_back_to_a_synthetic_origin_when_get_url_fails(fake_cli):
    binary, calls = fake_cli
    context = {
        "localStorage": {"localhost": {"token": "t"}, "app.test": {"k": "v"}},
        "indexedDB": {"app.test": [{"name": "db"}]},
    }
    with _api_server(body=context) as (url, _):
        cli = SteelCli(
            url,
            binary=binary,
            env=_env(calls, FAKE_CLI_FAIL_ON="get url"),
        )

        captured = cli.capture(_session())

    assert captured.context["localStorage"] == {
        "http://localhost": {"token": "t"},
        "https://app.test": {"k": "v"},
    }
    assert captured.context["indexedDB"] == {"https://app.test": [{"name": "db"}]}


def test_capture_reuses_a_previous_origin_for_a_host_key(fake_cli):
    binary, calls = fake_cli
    previous = BrowserSessionRecord(
        name="hunt", local_storage={"http://app.test:8080": {"old": "1"}}
    )
    context = {"localStorage": {"app.test": {"token": "t"}}}
    with _api_server(body=context) as (url, _):
        cli = SteelCli(url, binary=binary, env=_env(calls))

        captured = cli.capture(_session(), previous)

    assert captured.context["localStorage"] == {
        "http://app.test:8080": {"token": "t"}
    }


def test_normalise_storage_prefers_the_current_origin_over_the_previous_one():
    previous = BrowserSessionRecord(
        name="hunt", local_storage={"http://app.test:8080": {"old": "1"}}
    )
    context = {"localStorage": {"app.test": {"token": "t"}}}

    normalised = _normalise_storage(context, "https://app.test/app", previous)

    assert normalised["localStorage"] == {"https://app.test": {"token": "t"}}


def test_normalise_storage_merges_a_host_key_and_an_origin_key():
    context = {
        "localStorage": {
            "app.test": {"a": "1"},
            "https://app.test": {"b": "2"},
        }
    }

    normalised = _normalise_storage(context, None, None)

    assert normalised["localStorage"] == {
        "https://app.test": {"a": "1", "b": "2"}
    }


def test_normalise_storage_keeps_a_captured_port():
    context = {"localStorage": {"app.test:8443": {"a": "1"}}}

    normalised = _normalise_storage(context, None, None)

    assert normalised["localStorage"] == {"https://app.test:8443": {"a": "1"}}


def test_normalise_storage_handles_a_bracketed_ipv6_host():
    context = {"localStorage": {"[::1]:3000": {"a": "1"}}}

    normalised = _normalise_storage(context, None, None)

    assert normalised["localStorage"] == {"http://[::1]:3000": {"a": "1"}}


def test_normalise_storage_leaves_non_mapping_storage_alone():
    context = {"localStorage": "broken", "cookies": []}

    normalised = _normalise_storage(context, None, None)

    assert normalised == context


def test_normalise_storage_keeps_indexed_db_values_as_lists():
    context = {"indexedDB": {"localhost": [{"name": "db", "data": []}]}}

    normalised = _normalise_storage(context, "http://localhost:3000", None)

    assert normalised["indexedDB"] == {
        "http://localhost:3000": [{"name": "db", "data": []}]
    }


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("localhost", ("localhost", "localhost")),
        ("localhost:3000", ("localhost", "localhost:3000")),
        ("app.test", ("app.test", "app.test")),
        ("[::1]:3000", ("::1", "[::1]:3000")),
        ("https://app.test/x", ("app.test", "app.test")),
    ],
)
def test_split_key(key, expected):
    assert _split_key(key) == expected


@pytest.mark.parametrize(
    ("host", "authority", "expected"),
    [
        ("localhost", "localhost", "http://localhost"),
        ("127.0.0.1", "127.0.0.1:3000", "http://127.0.0.1:3000"),
        ("::1", "[::1]:3000", "http://[::1]:3000"),
        ("app.test", "app.test", "https://app.test"),
        ("app.test", "app.test:8443", "https://app.test:8443"),
    ],
)
def test_synthetic_origin(host, authority, expected):
    assert _synthetic_origin(host, authority) == expected


def test_capture_falls_back_to_the_cli(fake_cli):
    binary, calls = fake_cli
    responses = {
        "cookies": {"success": True, "data": [{"name": "sid", "value": "v"}]},
        "get url": {"success": True, "data": "https://app.test/page"},
        "storage local": {
            "success": True,
            "data": {"token": "t", "mode": "dark"},
        },
    }
    with _api_server(status=500, body={"message": "down"}) as (url, _):
        cli = SteelCli(
            url,
            binary=binary,
            env=_env(calls, FAKE_CLI_RESPONSES=json.dumps(responses)),
        )

        captured = cli.capture(_session())

    assert captured.source == "cli"
    assert captured.context == {
        "cookies": [{"name": "sid", "value": "v"}],
        "localStorage": {"https://app.test": {"token": "t", "mode": "dark"}},
    }


def test_capture_raises_when_both_paths_fail(fake_cli):
    binary, calls = fake_cli
    with _api_server(status=500, body={"message": "down"}) as (url, _):
        cli = SteelCli(
            url,
            binary=binary,
            env=_env(calls, FAKE_CLI_FAIL_ON="cookies"),
        )

        with pytest.raises(CaptureError):
            cli.capture(_session())


def test_stop_and_release(fake_cli):
    binary, calls = fake_cli
    with _api_server(status=200, body={"ok": True}) as (url, requests):
        cli = SteelCli(url, binary=binary, env=_env(calls))

        cli.stop(_session())
        released = cli.release(_session())

    assert released is True
    assert _calls(calls)[0][3:] == [
        "stop",
        "--session",
        "hunt",
        "--json",
    ]
    assert requests == [("POST", "/v1/sessions/steel-1/release", b"")]


def test_release_treats_a_missing_session_as_already_released(fake_cli):
    binary, calls = fake_cli
    with _api_server(status=404, body={"message": "not found"}) as (url, _):
        cli = SteelCli(url, binary=binary, env=_env(calls))

        assert cli.release(_session()) is False


def test_session_handle_does_not_carry_the_worker_url():
    session = _session()

    assert "http" not in repr(session)


@pytest.mark.parametrize(
    "url",
    ["ftp://localhost:1", "http://", "not-a-url", ""],
)
def test_worker_api_rejects_an_invalid_url(url):
    with pytest.raises(ValueError):
        WorkerAPI(url)


@pytest.mark.parametrize("session_id", ["", "../x", "a/b", "a b", None])
def test_worker_api_rejects_an_invalid_session_id(session_id):
    api = WorkerAPI("http://127.0.0.1:1")

    with pytest.raises(ValueError):
        api.context(session_id)


def test_worker_api_wraps_a_transport_error():
    api = WorkerAPI("http://127.0.0.1:1", timeout_s=0.2)

    with pytest.raises(WorkerAPIError):
        api.context("steel-1")


def test_cli_rejects_an_empty_command(fake_cli):
    binary, calls = fake_cli
    cli = SteelCli("http://127.0.0.1:3110", binary=binary, env=_env(calls))

    with pytest.raises(ValueError):
        cli.exec(_session(), [])
