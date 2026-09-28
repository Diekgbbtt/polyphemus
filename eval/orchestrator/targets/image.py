"""The `image` strategy: a local pullable container.

The target is a single image published on loopback; the instance kali aliases
the synthetic Host to the Docker host gateway (`host.docker.internal`), NOT
`127.0.0.1`: kali is not on the host network, so `127.0.0.1` is kali itself.
The stack's compose services reach host-published ports the same way
(`host.docker.internal:host-gateway`). `down` removes exactly the container it
created.
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

DEFAULT_INTERNAL_PORT = 80
LOOPBACK = "127.0.0.1"
HOST_GATEWAY = "host.docker.internal"


class ImageError(TargetError):
    """An image target lifecycle command failed."""


class ImageStrategy:
    """One local `docker run` target."""

    def __init__(
        self, context: TargetContext, *, sleep: Sleep | None = None
    ) -> None:
        params = context.run.target_config.params
        self.context = context
        self.host = context.host
        self.paths = context.paths
        self.image = str(params["image"])
        self.port = int(params["port"])
        self.internal_port = int(params.get("internal_port", DEFAULT_INTERNAL_PORT))
        self.ready_path = str(params.get("ready_path", "/"))
        self.name = str(params.get("name") or f"ph-target-{short_id(context.host)}")
        self._sleep = sleep or time.sleep

    @property
    def backend(self) -> str:
        return f"http://{LOOPBACK}:{self.port}"

    @property
    def front_url(self) -> str:
        return f"http://{self.host}/"

    def _run_cmd(self) -> Command:
        return Command(
            argv=(
                "docker",
                "run",
                "-d",
                "--name",
                self.name,
                "--publish",
                f"127.0.0.1:{self.port}:{self.internal_port}",
                self.image,
            ),
            description=f"run image {self.image}",
        )

    def _remove_cmd(self) -> Command:
        return Command(
            argv=("docker", "rm", "-f", self.name),
            description=f"remove {self.name}",
        )

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
            self._run_cmd(),
            self._probe_cmd(),
            routing.kali_alias_command(self.paths, self.host, HOST_GATEWAY),
        ]

    def up(self, run: CommandRunner) -> TargetUpResult:
        run_cmd = self._run_cmd()
        require_ok(run(run_cmd), run_cmd, error=ImageError)
        if not wait_ready(
            run, self._probe_cmd(), retries=30, interval_s=2.0, sleep=self._sleep
        ):
            raise TargetNotReadyError(
                f"image target {self.image!r} did not answer at {self.front_url}"
            )
        alias = routing.kali_alias_command(self.paths, self.host, HOST_GATEWAY)
        require_ok(run(alias), alias, error=ImageError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=self.backend, ready=True
        )

    def plan_down(self) -> list[Command]:
        return [
            self._remove_cmd(),
            routing.kali_clear_command(self.paths, self.host),
        ]

    def down(self, run: CommandRunner) -> None:
        remove = self._remove_cmd()
        require_ok(run(remove), remove, error=ImageError)
        clear = routing.kali_clear_command(self.paths, self.host)
        require_ok(run(clear), clear, error=ImageError)

    def plan_status(self) -> list[Command]:
        return [
            Command(
                argv=("docker", "inspect", "--format", "{{.State.Status}}", self.name),
                description=f"status {self.name}",
            )
        ]

    def status(self, run: CommandRunner) -> str:
        command = self.plan_status()[0]
        return require_ok(run(command), command, error=ImageError).stdout