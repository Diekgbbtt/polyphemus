"""The single external-effect seam: a command, its result, and its runner.

Every effect the orchestrator performs - `git worktree`, the env preflight,
`docker compose`, the local `scripts/targetctl`, `docker exec` into kali - is a
`Command`. The real runner is deliberately thin; tests inject a recording fake
and plan mode never constructs one.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


@dataclass(frozen=True)
class Command:
    """One external command.

    `stdin` carries piped input (the nginx front block, the kali `/etc/hosts`
    rewrite) so it is part of the recorded command, not a hidden side effect.
    `cwd` is where the command runs (compose resolves relative binds and the
    `.env` from the instance worktree). `env` is the command's environment
    overlay (the trial's L1 scaffold needs `PYTHONPATH=src`), merged over the
    inherited environment by the runner.
    `log_path` is where a background launch redirects the child's output; a
    synchronous `LocalRunner` ignores it.
    """

    argv: tuple[str, ...]
    stdin: str | None = None
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    description: str = ""
    log_path: Path | None = None

    def display(self) -> str:
        """A plan-mode rendering: the shell line plus its cwd, env, and stdin."""
        line = " ".join(self.argv)
        parts = []
        if self.cwd:
            parts.append(f"cwd={self.cwd}")
        if self.env:
            rendered = " ".join(f"{k}={v}" for k, v in sorted(self.env.items()))
            parts.append(f"env({rendered})")
        if self.stdin:
            parts.append(f"<<< {self.stdin.rstrip()}")
        return f"{line}" + (f"   [{', '.join(parts)}]" if parts else "")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Command], CommandResult]


class LocalRunner:
    """The thin production runner: `subprocess.run`, captured, with stdin."""

    def __call__(self, command: Command) -> CommandResult:
        env = None
        if command.env:
            env = {**os.environ, **command.env}
        proc = subprocess.run(
            list(command.argv),
            input=command.stdin,
            cwd=command.cwd,
            env=env,
            capture_output=True,
            text=True,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)


Spawn = Callable[..., subprocess.Popen]


class BackgroundRunner:
    """Launch a command detached and return at once; never wait for it.

    The assessor/diagnoser dispatch is fire-and-forget: a tick must not block
    while the subagent runs, so it can advance other trials. This runner starts
    the command in a new session (so the child outlives the tick) with its
    output redirected to `command.log_path` (a stable sink; inheriting the
    tick's pipes would signal the detached child when the tick exits), and
    returns a synthetic success without waiting.

    Completion is observed out of band by the node's output file, and a launch
    that raises (a missing executable) propagates to the caller's error path.
    """

    def __init__(self, *, spawn: Spawn = subprocess.Popen) -> None:
        self._spawn = spawn

    def __call__(self, command: Command) -> CommandResult:
        env = None
        if command.env:
            env = {**os.environ, **command.env}
        log = command.log_path
        handle = None
        if log is not None:
            target = Path(log)
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = open(target, "ab")
        try:
            self._spawn(
                list(command.argv),
                stdin=subprocess.DEVNULL,
                stdout=handle if handle is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT if handle is not None else subprocess.DEVNULL,
                cwd=command.cwd,
                env=env,
                start_new_session=True,
            )
        finally:
            if handle is not None:
                handle.close()
        return CommandResult(0)


def require_ok(result: CommandResult, command: Command, *, error: type[Exception]) -> CommandResult:
    """Raise `error` naming the failing command and its stderr on a non-zero exit."""
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise error(f"command failed ({result.returncode}): {command.display()}: {detail}")
    return result


def is_absent_container(result: CommandResult) -> bool:
    """True when a `docker rm`/`inspect` failure means the container is absent.

    Teardown is idempotent (SP3): a container that was never running is success,
    not an error to abort the rest of the teardown on.
    """
    text = f"{result.stderr}\n{result.stdout}".lower()
    return "no such container" in text
