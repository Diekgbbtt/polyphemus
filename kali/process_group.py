"""Bounded process execution with process-group cleanup.

``subprocess.run(timeout=...)`` kills only the direct child. A shell that
started a pipeline, a background job, or a wrapper leaves those descendants
running after the timeout. In a browser runtime that means a stuck CLI keeps a
session busy and the next command sees a wedged page even though the tool
already returned ``timeout``.

Every long-running tool command therefore starts in its own session/process
group. On timeout the whole group is killed, not just the shell. A normal exit
does not kill the group: a caller may intentionally start a background job.

The helper is deliberately small and standard-library only. It performs no I/O
at import.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessOutcome:
    stdout: str
    stderr: str
    returncode: int
    duration_ms: int


def _kill_group(process: subprocess.Popen) -> None:
    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # A child that changed its own group cannot be reached from here; the
        # direct child kill is the best remaining action.
        try:
            process.kill()
        except ProcessLookupError:
            pass


def run_in_process_group(
    command: str | list[str],
    *,
    shell: bool = False,
    cwd: str | None = None,
    env: dict | None = None,
    timeout_s: int | float | None = None,
    text: bool = True,
) -> ProcessOutcome:
    """Run one command in a new process group and reap the whole group on
    timeout. ``returncode`` is 124 on timeout, matching the shell convention
    the rest of the tool stack already classifies.
    """
    start = time.monotonic()
    process = subprocess.Popen(
        command,
        shell=shell,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            timeout=max(1, timeout_s) if timeout_s else None
        )
        return ProcessOutcome(
            stdout=stdout or "",
            stderr=stderr or "",
            returncode=process.returncode,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except subprocess.TimeoutExpired:
        _kill_group(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        message = f"timeout after {timeout_s}s"
        stderr = f"{stderr}\n{message}".strip() if stderr else message
        return ProcessOutcome(
            stdout=stdout or "",
            stderr=stderr,
            returncode=124,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
