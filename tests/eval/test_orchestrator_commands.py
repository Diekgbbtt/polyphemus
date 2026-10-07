"""The background launch seam for the assessor/diagnoser dispatch (#316).

The tick control plane must not block while a dispatched subagent runs, so the
production dispatch launches the agent command detached and returns at once.
`BackgroundRunner` is that launch: it starts the process in a new session with
its output redirected to a stable log (inheriting the tick's pipes would signal
the detached child when the tick exits), and it never waits for it.
"""
from __future__ import annotations

import subprocess
import time

import pytest

from orchestrator.commands import BackgroundRunner, Command, CommandResult


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.waited = False

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def poll(self):
        return None


def _spawn_recorder():
    calls = []
    processes = []

    def spawn(*args, **kwargs):
        process = _FakeProcess()
        calls.append((args, kwargs))
        processes.append(process)
        return process

    return calls, processes, spawn


def test_background_runner_launches_detached_and_returns_at_once() -> None:
    calls, processes, spawn = _spawn_recorder()
    runner = BackgroundRunner(spawn=spawn)

    result = runner(Command(argv=("opencode", "run"), description="assess x"))

    assert result == CommandResult(0)
    (args, kwargs), = calls
    assert list(args[0]) == ["opencode", "run"]
    assert kwargs["start_new_session"] is True
    assert not processes[0].waited


def test_background_runner_uses_devnull_without_a_log() -> None:
    calls, _, spawn = _spawn_recorder()
    BackgroundRunner(spawn=spawn)(Command(argv=("agent",)))
    _, kwargs = calls[0]
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL


def test_background_runner_directs_child_output_to_the_log(tmp_path) -> None:
    log = tmp_path / "verdicts.yaml.dispatch.log"
    seen = {}

    def spawn(*args, **kwargs):
        seen["stderr"] = kwargs["stderr"]
        kwargs["stdout"].write(b"agent output\n")
        return _FakeProcess()

    BackgroundRunner(spawn=spawn)(Command(argv=("agent",), log_path=log))

    assert seen["stderr"] is subprocess.STDOUT
    assert log.read_bytes() == b"agent output\n"


def test_background_runner_propagates_a_launch_failure() -> None:
    def spawn(*args, **kwargs):
        raise FileNotFoundError("no such executable")

    with pytest.raises(FileNotFoundError):
        BackgroundRunner(spawn=spawn)(Command(argv=("nope",)))


def test_background_runner_returns_before_a_sleeping_command_finishes(tmp_path) -> None:
    start = time.monotonic()
    BackgroundRunner()(Command(argv=("sleep", "5"), log_path=tmp_path / "d.log"))
    assert time.monotonic() - start < 2.0
