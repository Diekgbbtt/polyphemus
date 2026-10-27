"""Unit tier: process-group execution and timeout cleanup.

The regression is the actual failure mode: a timed-out shell leaves its
background child alive after the tool has returned ``timeout``.
"""
from __future__ import annotations

import subprocess
import time

from kali.process_group import run_in_process_group


def _gone(pid: int) -> bool:
    return subprocess.run(
        ["ps", "-p", str(pid)], capture_output=True, text=True
    ).returncode != 0


def test_a_normal_command_returns_its_output():
    outcome = run_in_process_group("printf hello", shell=True, timeout_s=5)

    assert outcome.returncode == 0
    assert outcome.stdout == "hello"
    assert outcome.stderr == ""


def test_argv_mode_runs_without_a_shell():
    outcome = run_in_process_group(
        ["sh", "-c", "printf argv"], shell=False, timeout_s=5
    )

    assert outcome.returncode == 0
    assert outcome.stdout == "argv"


def test_a_timeout_kills_the_background_child(tmp_path):
    pidfile = tmp_path / "child.pid"
    outcome = run_in_process_group(
        f"sh -c 'sleep 60 & echo $! > {pidfile}; wait'",
        shell=True,
        timeout_s=1,
    )

    assert outcome.returncode == 124
    assert "timeout after 1s" in outcome.stderr
    pid = int(pidfile.read_text().strip())
    deadline = time.time() + 3
    while time.time() < deadline and not _gone(pid):
        time.sleep(0.05)
    assert _gone(pid), f"background child {pid} survived the timeout"


def test_partial_output_before_a_timeout_is_preserved():
    outcome = run_in_process_group(
        "echo before; sleep 60 & wait", shell=True, timeout_s=1
    )

    assert outcome.returncode == 124
    assert "before" in outcome.stdout
