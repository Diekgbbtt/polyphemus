"""Seam under test: the fake `exec_fn` the session client will call.

The fake has the same shape as the production seam: it takes one command
argument list and returns one CLI JSON envelope. Every command is recorded so
a test can assert the exact wire form the client produced.
"""
from __future__ import annotations

import pytest

from tests.recon.crawl.steel.fixtures import load_cli
from tests.recon.crawl.steel.support import ExecQueueExhausted, FakeExecFn

SESSION_COMMAND = [
    "steel",
    "browser",
    "sessions",
    "get",
    "--session",
    "crawl-fixture",
    "--json",
]
NAVIGATE_COMMAND = [
    "steel",
    "browser",
    "navigate",
    "https://example.test/",
    "--session",
    "crawl-fixture",
    "--json",
]
STOP_COMMAND = ["steel", "browser", "stop", "--session", "crawl-fixture", "--json"]


def test_fake_exec_returns_the_queued_envelope_and_records_the_command():
    exec_fn = FakeExecFn(load_cli("session"))

    envelope = exec_fn(SESSION_COMMAND)

    assert envelope["success"] is True
    assert envelope["data"]["name"] == "crawl-fixture"
    assert exec_fn.commands == [SESSION_COMMAND]
    assert exec_fn.last_command == SESSION_COMMAND


def test_fake_exec_returns_envelopes_in_queue_order():
    exec_fn = FakeExecFn(load_cli("navigate"), load_cli("stop"))

    navigate = exec_fn(NAVIGATE_COMMAND)
    stop = exec_fn(STOP_COMMAND)

    assert navigate["data"]["url"] == "https://example.test/products?page=2"
    assert stop["data"]["stoppedSessions"] == ["crawl-fixture"]
    assert exec_fn.commands == [NAVIGATE_COMMAND, STOP_COMMAND]


def test_fake_exec_records_a_copy_of_the_command_it_was_given():
    command = list(SESSION_COMMAND)
    exec_fn = FakeExecFn(load_cli("session"))

    exec_fn(command)
    command.append("--mutated")

    assert exec_fn.commands == [SESSION_COMMAND]


def test_fake_exec_queue_exhaustion_fails_loudly():
    exec_fn = FakeExecFn()

    with pytest.raises(ExecQueueExhausted, match="sessions") as excinfo:
        exec_fn(SESSION_COMMAND)

    assert "no queued envelope" in str(excinfo.value)
    assert exec_fn.commands == [SESSION_COMMAND]
