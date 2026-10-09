"""The bounded command runner (#350).

Every synchronous external command runs in its own process group under a hard
wall-clock timeout. On timeout the whole group is killed and reaped, and the
call returns a non-zero result instead of blocking the caller forever. This
replaced the old detached `BackgroundRunner` (which discarded the `Popen` and
leaked a hung subagent) and the unbounded `subprocess.run` in `LocalRunner`.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from orchestrator.commands import Command, CommandResult, LocalRunner


def test_local_runner_captures_stdout_stderr_and_stdin() -> None:
    result = LocalRunner()(
        Command(argv=("sh", "-c", "cat; echo err >&2"), stdin="hello\n")
    )
    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert result.stderr == "err\n"


def test_local_runner_tees_captured_output_to_the_log(tmp_path) -> None:
    log = tmp_path / "verdicts.yaml.dispatch.log"
    result = LocalRunner()(
        Command(argv=("sh", "-c", "echo agent output"), log_path=log)
    )
    assert result.returncode == 0
    assert log.read_text(encoding="utf-8") == "agent output\n"


def test_local_runner_kills_a_timed_out_command_group_and_reaps_it(tmp_path) -> None:
    pid_file = tmp_path / "pid"
    command = Command(
        argv=("sh", "-c", f"echo $$ > {pid_file}; exec sleep 30"),
    )
    start = time.monotonic()
    result = LocalRunner(timeout_s=0.5)(command)
    elapsed = time.monotonic() - start

    assert result.returncode == 124
    assert "timeout" in result.stderr
    assert elapsed < 10.0  # the SIGTERM grace, never the 30s sleep

    pid = int(pid_file.read_text().strip())
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"timed-out child {pid} was not reaped")


def test_local_runner_result_is_hashable_and_equal() -> None:
    assert CommandResult(0) == CommandResult(0, "", "")
