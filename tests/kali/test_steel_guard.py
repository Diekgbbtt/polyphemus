"""Unit tier: the Steel binary guard.

The guard is the public ``steel`` entrypoint. These tests use a fake real
binary and an injected live catalogue, so no Steel runtime is needed. They
prove the guard refuses before execution, records the true command result,
and classifies a masked failure from its own trace.
"""
from __future__ import annotations

import json
import os
import stat
import time

import pytest

import kali.steel_guard as guard_module
from kali.steel_guard import (
    guard_env,
    known_session_names,
    read_events,
    record_live_sessions,
    resolve_guard_path,
    run_guarded,
)


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "KALI_STEEL_SESSION_REGISTRY", str(tmp_path / "sessions.json")
    )


def test_guard_file_is_executable_with_a_python_shebang():
    """The wrapper executes the guard directly. A missing shebang makes the
    kernel run it as a shell script; a missing executable bit makes the
    wrapper fail before every Steel command. Both are release invariants."""
    from pathlib import Path

    assert os.access(guard_module.__file__, os.X_OK)
    first_line = Path(guard_module.__file__).read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!")
    assert "python" in first_line


def _fake_real(tmp_path, monkeypatch):
    marker = tmp_path / "ran.txt"
    script = tmp_path / "steel-real"
    script.write_text(
        """#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ["FAKE_MARKER"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "sleep":
    time.sleep(5)
if mode in ("fail", "cdp"):
    print('{"error":"CDP error (Runtime.evaluate): Session with given id not found.","success":false}')
    sys.exit(1)
if mode == "start":
    print('{"data":{"id":"sid-1","remainingMs":86400000},"success":true}')
    sys.exit(0)
print('{"data":1,"success":true}')
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("FAKE_MARKER", str(marker))
    return script, marker


def _recorded(marker) -> list[list[str]]:
    return [
        json.loads(line)
        for line in marker.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_shell_invocation_gets_the_local_flag_from_the_guard(tmp_path, monkeypatch):
    """The retired wrapper supplied `--local` for a shell caller. The guard
    owns that flag now, so a bare `steel browser ...` still selects local mode."""
    real, marker = _fake_real(tmp_path, monkeypatch)
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://steel.test:3000/v1")

    code = run_guarded(
        ["browser", "eval", "1", "--session", "wj-live", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=_trace(tmp_path),
    )

    assert code == 0
    assert _recorded(marker) == [
        ["--local", "browser", "eval", "1", "--session", "wj-live", "--json"]
    ]


def test_an_explicit_mode_flag_is_not_duplicated(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://steel.test:3000/v1")

    run_guarded(
        ["--local", "browser", "eval", "1", "--session", "wj-live", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=_trace(tmp_path),
    )

    assert _recorded(marker) == [
        ["--local", "browser", "eval", "1", "--session", "wj-live", "--json"]
    ]


def test_a_non_browser_command_does_not_get_the_local_flag(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://steel.test:3000/v1")

    run_guarded(
        ["--version"],
        real_binary=str(real),
        trace_path=_trace(tmp_path),
    )

    assert _recorded(marker) == [["--version"]]


def _trace(tmp_path) -> str:
    return str(tmp_path / "trace.jsonl")


def test_unknown_session_is_denied_before_the_real_binary(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "eval", "1", "--session", "wj-typo", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=trace,
    )

    assert code == 2
    assert not marker.exists()
    events = read_events(trace)
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["error"]["code"] == "unknown_session"
    assert events[0]["error"]["recovery"]["action"] == "use_live"


def test_live_session_runs_and_records_the_true_exit(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "eval", "1", "--session", "wj-live", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=trace,
    )

    assert code == 0
    assert marker.exists()
    event = read_events(trace)[0]
    assert event["decision"] == "allow"
    assert event["returncode"] == 0
    assert event["error"] is None


def test_start_on_an_absent_session_is_allowed(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)

    code = run_guarded(
        ["browser", "start", "--session", "wj-new", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=_trace(tmp_path),
    )

    assert code == 0
    assert marker.exists()


def test_start_on_a_live_session_is_denied(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "start", "--session", "wj-live", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=trace,
    )

    assert code == 2
    assert not marker.exists()
    assert read_events(trace)[0]["error"]["code"] == "session_taken"


def test_masked_failure_is_classified_from_the_trace(tmp_path, monkeypatch):
    real, _ = _fake_real(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_MODE", "cdp")
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "eval", "1", "--session", "wj-live", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=trace,
    )

    assert code == 1
    event = read_events(trace)[0]
    assert event["returncode"] == 1
    assert event["error"]["code"] == "target_lost"
    assert event["error"]["recovery"]["action"] == "tab_new"


def test_timeout_is_classified_as_browser_stuck(tmp_path, monkeypatch):
    real, _ = _fake_real(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_MODE", "sleep")
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "snapshot", "--session", "wj-live", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=trace,
        timeout_s=1,
    )

    assert code == 124
    event = read_events(trace)[0]
    assert event["error"]["code"] == "browser_stuck"
    assert event["error"]["fatal"] is True
    assert event["error"]["recovery"]["action"] == "recreate_session"


def test_a_non_browser_steel_command_passes_through(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)

    code = run_guarded(
        ["--version"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=_trace(tmp_path),
    )

    assert code == 0
    assert marker.exists()


def test_guard_env_sets_the_wrapper_and_the_real_binary(tmp_path, monkeypatch):
    guard = tmp_path / "steel_guard.py"
    guard.write_text("# guard\n", encoding="utf-8")
    guard.chmod(guard.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("KALI_STEEL_GUARD", str(guard))

    env = guard_env(trace_path="/tmp/trace.jsonl", timeout_s=30)

    assert env["STEEL_REAL_BINARY"].endswith("steel_guard.py")
    assert env["STEEL_REAL_BINARY_REAL"] == "/opt/localbin/.steel/steel"
    assert env["KALI_STEEL_TRACE"] == "/tmp/trace.jsonl"
    assert env["KALI_STEEL_TIMEOUT_S"] == "30"


def test_the_real_binary_is_not_in_a_path_directory():
    """A public PATH name would let a nested shell skip the guard entirely."""
    assert guard_module.DEFAULT_REAL_BINARY == "/opt/localbin/.steel/steel"
    assert os.path.dirname(guard_module.DEFAULT_REAL_BINARY) == (
        "/opt/localbin/.steel"
    )


def test_resolve_guard_path_prefers_the_override(tmp_path, monkeypatch):
    guard = tmp_path / "steel_guard.py"
    guard.write_text("# guard\n", encoding="utf-8")
    guard.chmod(guard.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("KALI_STEEL_GUARD", str(guard))

    assert resolve_guard_path() == str(guard)


def test_registry_remembers_a_live_session():
    record_live_sessions(["wj-live"])

    assert known_session_names() == {"wj-live"}


def test_known_but_gone_session_is_a_session_loss(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "eval", "1", "--session", "wj-gone", "--json"],
        real_binary=str(real),
        live_sessions=set(),
        known_sessions={"wj-gone"},
        trace_path=trace,
    )

    assert code == 2
    assert not marker.exists()
    event = read_events(trace)[0]
    assert event["error"]["code"] == "session_missing"
    assert event["error"]["fatal"] is True
    assert event["error"]["recovery"]["action"] == "recreate_session"
    assert event["error"]["recovery"]["requires_state_restore"] is True


def test_a_never_seen_name_remains_an_unknown_session(tmp_path, monkeypatch):
    real, marker = _fake_real(tmp_path, monkeypatch)
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "eval", "1", "--session", "wj-typo", "--json"],
        real_binary=str(real),
        live_sessions=set(),
        known_sessions={"wj-live"},
        trace_path=trace,
    )

    assert code == 2
    assert not marker.exists()
    assert read_events(trace)[0]["error"]["code"] == "unknown_session"


def test_a_command_that_skips_the_catalogue_says_not_required(tmp_path, monkeypatch):
    real, _ = _fake_real(tmp_path, monkeypatch)
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "sessions", "--json"],
        real_binary=str(real),
        live_sessions=None,
        trace_path=trace,
    )

    assert code == 0
    assert read_events(trace)[0]["catalogue"] == "not-required"


def test_a_queried_catalogue_says_live(tmp_path, monkeypatch):
    real, _ = _fake_real(tmp_path, monkeypatch)
    trace = _trace(tmp_path)

    run_guarded(
        ["browser", "eval", "1", "--session", "wj-live", "--json"],
        real_binary=str(real),
        live_sessions={"wj-live"},
        trace_path=trace,
    )

    assert read_events(trace)[0]["catalogue"] == "live"


def test_a_successful_start_is_recorded_immediately(tmp_path, monkeypatch):
    real, _ = _fake_real(tmp_path, monkeypatch)
    trace = _trace(tmp_path)

    code = run_guarded(
        ["browser", "start", "--session", "wj-new", "--json"],
        real_binary=str(real),
        live_sessions=set(),
        trace_path=trace,
    )

    assert code == 0
    assert "wj-new" in known_session_names()


def test_a_failed_start_is_not_recorded(tmp_path, monkeypatch):
    real, _ = _fake_real(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_MODE", "fail")

    code = run_guarded(
        ["browser", "start", "--session", "wj-new", "--json"],
        real_binary=str(real),
        live_sessions=set(),
        trace_path=_trace(tmp_path),
    )

    assert code == 1
    assert "wj-new" not in known_session_names()


def test_a_start_trace_records_the_runtime_session_id_and_lifetime(
        tmp_path, monkeypatch):
    real, _ = _fake_real(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_MODE", "start")
    trace = _trace(tmp_path)

    run_guarded(
        ["browser", "start", "--session", "wj-new", "--json"],
        real_binary=str(real),
        live_sessions=set(),
        trace_path=trace,
    )

    event = read_events(trace)[0]
    assert event["session_id"] == "sid-1"
    assert event["remaining_ms"] == 86400000


def test_a_started_session_that_dies_before_a_catalogue_query_is_a_loss(
        tmp_path, monkeypatch):
    """The catalogue is queried before `start`, so it cannot contain the new
    name. A loss before the next query must still be session_missing."""
    real, _ = _fake_real(tmp_path, monkeypatch)
    start_code = run_guarded(
        ["browser", "start", "--session", "wj-new", "--json"],
        real_binary=str(real),
        live_sessions=set(),
        trace_path=_trace(tmp_path),
    )
    assert start_code == 0

    trace = str(tmp_path / "loss-trace.jsonl")
    code = run_guarded(
        ["browser", "eval", "1", "--session", "wj-new", "--json"],
        real_binary=str(real),
        live_sessions=set(),
        known_sessions=known_session_names(),
        trace_path=trace,
    )

    assert code == 2
    error = read_events(trace)[0]["error"]
    assert error["code"] == "session_missing"
    assert error["recovery"]["action"] == "recreate_session"


def test_concurrent_registry_writes_keep_every_session(tmp_path, monkeypatch):
    """The MCP process and one guard process per command share the registry.
    An unlocked read-modify-write loses names."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    original_write = guard_module._write_registry

    def slow_write(registry):
        time.sleep(0.02)
        original_write(registry)

    monkeypatch.setattr(guard_module, "_write_registry", slow_write)
    barrier = threading.Barrier(8)

    def writer(index):
        barrier.wait()
        record_live_sessions([f"wj-{index}"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(writer, range(8)))

    assert known_session_names() == {f"wj-{i}" for i in range(8)}


def test_read_events_removes_the_trace(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps({"decision": "allow"}) + "\n", encoding="utf-8")

    assert read_events(str(trace)) == [{"decision": "allow"}]
    assert not trace.exists()
    assert read_events(str(trace)) == []
