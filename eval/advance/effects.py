"""effects.py - the one subprocess seam for the advancement plane.

Every advance module that shells out (`images`, `app_state`, `manifest`, and the
daemon's alert hook) shares this `CommandResult` type and one `run_process`
wrapper, so the result shape and the capture flags cannot drift between the
digest collector, the psql fallback, git, and the alert hook. The runner stays
injectable everywhere: importing this module performs no I/O.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class CommandResult:
    """A finished external command: its exit code and captured streams."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str]], CommandResult]


def run_process(args: Sequence[str]) -> CommandResult:
    """Run `args` and capture stdout/stderr as text (the production runner)."""
    proc = subprocess.run(list(args), capture_output=True, text=True)
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)
