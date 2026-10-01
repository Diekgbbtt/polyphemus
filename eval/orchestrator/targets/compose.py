"""The `compose` strategy: a local pullable compose stack.

The stack runs under its own compose project (`ph-target-<short>`), distinct
from the instance projects. It is fronted on `http://<host>/` (port 80) by the
shared host-level nginx container (`orchestrator/front.py`, SP2), and the
instance kali aliases the synthetic Host to the Docker host gateway resolved to
a NUMERIC address (SP1) - never `127.0.0.1`, because kali is not on the host
network and `127.0.0.1` is kali itself. The gateway is a host interface, so the
target compose file MUST publish on an interface it can reach (all interfaces);
a loopback-only (`127.0.0.1:<port>:...`) binding is unreachable from kali and
the front. `down` removes that project's containers and volumes, idempotently,
and always clears the alias.
"""
from __future__ import annotations

import time

from orchestrator import front, routing
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

# Single-sourced routing constants (S2).
LOOPBACK = routing.LOOPBACK
HOST_GATEWAY = routing.HOST_GATEWAY


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
            front.plan_conf_apply(self.host, self.port),
            routing.plan_gateway_resolve(self.paths),
            routing.kali_alias_command(self.paths, self.host, routing.PLAN_GATEWAY_IP),
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
        conf = front.plan_conf_apply(self.host, self.port)
        require_ok(run(conf), conf, error=ComposeTargetError)
        alias = routing.kali_alias_command(
            self.paths, self.host, self._gateway_address(run)
        )
        require_ok(run(alias), alias, error=ComposeTargetError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=self.backend, ready=True
        )

    def _gateway_address(self, run: CommandRunner) -> str:
        try:
            return routing.resolve_gateway(run, self.paths)
        except routing.RoutingError as exc:
            raise ComposeTargetError(str(exc)) from exc

    def plan_down(self) -> list[Command]:
        return [
            self._compose("down", "-v", "--remove-orphans"),
            front.plan_conf_remove(self.host),
            routing.kali_clear_command(self.paths, self.host),
        ]

    def down(self, run: CommandRunner) -> None:
        # SP3: best-effort cleanup; the front conf and kali alias are always
        # removed, and an aggregate error is raised at the end for reporting.
        down_cmd = self._compose("down", "-v", "--remove-orphans")
        down_result = run(down_cmd)
        conf = front.plan_conf_remove(self.host)
        conf_result = run(conf)
        clear = routing.kali_clear_command(self.paths, self.host)
        clear_result = run(clear)
        errors: list[str] = []
        if down_result.returncode != 0:
            errors.append(
                f"compose down failed: "
                f"{down_result.stderr.strip() or down_result.stdout.strip()}"
            )
        if conf_result.returncode != 0:
            errors.append(
                f"remove front conf for {self.host} failed: "
                f"{conf_result.stderr.strip() or conf_result.stdout.strip()}"
            )
        if clear_result.returncode != 0:
            errors.append(
                f"clear alias {self.host} failed: "
                f"{clear_result.stderr.strip() or clear_result.stdout.strip()}"
            )
        if errors:
            raise ComposeTargetError("; ".join(errors))

    def plan_status(self) -> list[Command]:
        return [self._compose("ps")]

    def status(self, run: CommandRunner) -> str:
        command = self._compose("ps")
        return require_ok(run(command), command, error=ComposeTargetError).stdout