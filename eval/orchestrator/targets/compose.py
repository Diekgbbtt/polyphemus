"""The `compose` strategy: a local pullable compose stack.

The stack runs under its own compose project (`ph-target-<short>`), distinct
from the instance projects; the instance kali aliases the synthetic Host to
`127.0.0.1`. `down` removes that project's containers and volumes.
"""
from __future__ import annotations

import time

from orchestrator import routing
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.ids import short_id
from orchestrator.targets.base import (
    Sleep,
    TargetContext,
    TargetError,
    TargetNotReadyError,
    TargetUpResult,
    wait_ready,
)

LOOPBACK = "127.0.0.1"


class ComposeTargetError(TargetError):
    """A compose target lifecycle command failed."""


class ComposeStrategy:
    """One local compose-file target."""

    def __init__(
        self, context: TargetContext, *, sleep: Sleep | None = None
    ) -> None:
        params = context.run.target_config.params
        self.context = context
        self.host = context.host
        self.paths = context.paths
        self.compose_file = str(params["compose_file"])
        self.port = int(params["port"])
        self.ready_path = str(params.get("ready_path", "/"))
        self.project = str(params.get("project") or f"ph-target-{short_id(context.host)}")
        self.cwd = str(params.get("cwd") or context.paths.worktree)
        self._sleep = sleep or time.sleep

    @property
    def backend(self) -> str:
        return f"http://{LOOPBACK}:{self.port}"

    @property
    def front_url(self) -> str:
        return f"http://{self.host}/"

    def _compose(self, *verbs: str) -> Command:
        argv = (
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            self.compose_file,
            *verbs,
        )
        return Command(argv=argv, cwd=self.cwd, description=f"target compose {' '.join(verbs)}")

    def _probe_cmd(self) -> Command:
        return Command(
            argv=(
                "curl",
                "-sS",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "--max-time",
                "10",
                f"{self.backend}{self.ready_path}",
            ),
            description=f"probe {self.host}",
        )

    def plan_up(self) -> list[Command]:
        return [
            self._compose("up", "-d"),
            self._probe_cmd(),
            routing.kali_alias_command(self.paths, self.host, LOOPBACK),
        ]

    def up(self, run: CommandRunner) -> TargetUpResult:
        up_cmd = self._compose("up", "-d")
        require_ok(run(up_cmd), up_cmd, error=ComposeTargetError)
        if not wait_ready(
            run, self._probe_cmd(), retries=30, interval_s=2.0, sleep=self._sleep
        ):
            raise TargetNotReadyError(
                f"compose target {self.compose_file!r} did not answer at {self.front_url}"
            )
        alias = routing.kali_alias_command(self.paths, self.host, LOOPBACK)
        require_ok(run(alias), alias, error=ComposeTargetError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=self.backend, ready=True
        )

    def plan_down(self) -> list[Command]:
        return [
            self._compose("down", "-v", "--remove-orphans"),
            routing.kali_clear_command(self.paths, self.host),
        ]

    def down(self, run: CommandRunner) -> None:
        down_cmd = self._compose("down", "-v", "--remove-orphans")
        require_ok(run(down_cmd), down_cmd, error=ComposeTargetError)
        clear = routing.kali_clear_command(self.paths, self.host)
        require_ok(run(clear), clear, error=ComposeTargetError)

    def plan_status(self) -> list[Command]:
        return [self._compose("ps")]

    def status(self, run: CommandRunner) -> str:
        command = self._compose("ps")
        return require_ok(run(command), command, error=ComposeTargetError).stdout