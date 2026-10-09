"""The single external-effect seam: a command, its result, and its runner.

Every effect the orchestrator performs - `git worktree`, the env preflight,
`docker compose`, the local `scripts/targetctl`, `docker exec` into kali - is a
`Command`. The real runner is deliberately thin; tests inject a recording fake
and plan mode never constructs one.
"""
from __future__ import annotations

import os
import signal
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
    `log_path` is where the runner tees the child's captured output so a
    dispatch leaves a diagnostic log beside its destination; it is never an
    input to a decision.
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


# The wall-clock bound on any one synchronous command (#350). A subagent that
# hangs (a fatal provider error leaves `opencode run` idle forever) must become a
# non-zero result, never a blocked caller.
DEFAULT_COMMAND_TIMEOUT_S = float(os.environ.get("EVAL_COMMAND_TIMEOUT_S", 7200.0))
# How long SIGTERM is given before the process group is SIGKILLed.
KILL_GRACE_S = 10.0
# The exit code a timed-out command reports (the shell's convention, 128+16).
TIMEOUT_RETURNCODE = 124

Spawn = Callable[..., subprocess.Popen]


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Terminate and reap the command's whole process group.

    The child runs in its own session (`start_new_session=True`), so killing its
    group reaches anything it spawned. SIGTERM first, a bounded grace, then
    SIGKILL, then `wait()` so the child is reaped rather than left a zombie.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        proc.wait()
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=KILL_GRACE_S)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()


class LocalRunner:
    """The thin production runner: a bounded, process-group-isolated subprocess.

    The command runs in its own session so a wall-clock timeout can kill the
    whole process group (the subagent and anything it spawned) and reap it. A
    timeout returns a non-zero `CommandResult` (never a hang), so a stuck caller
    such as `close-verify` returns and records an escalation. Captured stdout
    and stderr are teed to `command.log_path` when one is set.
    """

    def __init__(
        self, *, timeout_s: float | None = None, spawn: Spawn = subprocess.Popen
    ) -> None:
        self._timeout_s = DEFAULT_COMMAND_TIMEOUT_S if timeout_s is None else timeout_s
        self._spawn = spawn

    def __call__(self, command: Command) -> CommandResult:
        env = None
        if command.env:
            env = {**os.environ, **command.env}
        proc = self._spawn(
            list(command.argv),
            stdin=subprocess.PIPE if command.stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=command.cwd,
            env=env,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(
                input=command.stdin, timeout=self._timeout_s
            )
            result = CommandResult(proc.returncode, stdout or "", stderr or "")
        except subprocess.TimeoutExpired:
            _kill_process_group(proc)
            stdout, stderr = proc.communicate()
            detail = f"\ntimeout after {self._timeout_s}s"
            result = CommandResult(
                TIMEOUT_RETURNCODE, stdout or "", (stderr or "") + detail
            )
        self._tee_log(command, result)
        return result

    @staticmethod
    def _tee_log(command: Command, result: CommandResult) -> None:
        if command.log_path is None:
            return
        target = Path(command.log_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.stdout + result.stderr, encoding="utf-8")


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
