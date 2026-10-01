"""The `image` strategy: a local pullable container.

The target image is published on the host with docker's default binding (all
interfaces, `0.0.0.0`). It is fronted on `http://<host>/` (port 80) by the
shared host-level nginx container (`orchestrator/front.py`, SP2), and the
instance kali aliases the synthetic Host to the Docker host gateway resolved to
a NUMERIC address (SP1) - never `127.0.0.1`, because kali is not on the host
network and `127.0.0.1` is kali itself. The gateway (the bridge's `172.x.0.1`)
is a host interface, so the publish must not be loopback-only or neither kali
nor the front could reach it. `down` removes exactly the container it created,
idempotently (an absent container is success), and always clears the alias.
"""
from __future__ import annotations

import time

from orchestrator import docker as docker_images
from orchestrator import front, routing
from orchestrator.commands import Command, CommandRunner, is_absent_container, require_ok
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
# Single-sourced routing constants (S2): the host loopback and the Docker host
# gateway kali reaches host-published ports through.
LOOPBACK = routing.LOOPBACK
HOST_GATEWAY = routing.HOST_GATEWAY


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
        self.registry = context.registry
        # The target's image identifiers are as-is on the TargetRun; the params
        # `image` is the legacy single-image form.
        self.images = tuple(context.run.images) or (str(params["image"]),)
        self.image = self.images[0]
        self.dockerfile = context.run.target_config.dockerfile
        self.dockerfile_context = context.run.target_config.dockerfile_context
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
                # No host IP: docker's default binds all interfaces, including
                # the bridge gateway `host.docker.internal` resolves to. A
                # `127.0.0.1:` prefix would be unreachable from kali (Linux).
                f"{self.port}:{self.internal_port}",
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
            front.plan_conf_apply(self.host, self.port),
            routing.plan_gateway_resolve(self.paths),
            routing.kali_alias_command(self.paths, self.host, routing.PLAN_GATEWAY_IP),
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
        conf = front.plan_conf_apply(self.host, self.port)
        require_ok(run(conf), conf, error=ImageError)
        alias = routing.kali_alias_command(
            self.paths, self.host, self._gateway_address(run)
        )
        require_ok(run(alias), alias, error=ImageError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=self.backend, ready=True
        )

    def _gateway_address(self, run: CommandRunner) -> str:
        """Resolve the gateway to a numeric address, failing loudly (SP1)."""
        try:
            return routing.resolve_gateway(run, self.paths)
        except routing.RoutingError as exc:
            raise ImageError(str(exc)) from exc

    def plan_down(self) -> list[Command]:
        return [
            self._remove_cmd(),
            front.plan_conf_remove(self.host),
            routing.kali_clear_command(self.paths, self.host),
        ]

    def down(self, run: CommandRunner) -> None:
        # SP3: idempotent and always clears the alias. An absent container is
        # success; a genuine removal failure is reported only after the front
        # conf and the kali alias have been cleaned up.
        remove = self._remove_cmd()
        remove_result = run(remove)
        conf = front.plan_conf_remove(self.host)
        conf_result = run(conf)
        clear = routing.kali_clear_command(self.paths, self.host)
        clear_result = run(clear)
        errors: list[str] = []
        if remove_result.returncode != 0 and not is_absent_container(remove_result):
            errors.append(
                f"remove container {self.name} failed: "
                f"{remove_result.stderr.strip() or remove_result.stdout.strip()}"
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
            raise ImageError("; ".join(errors))

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

    # --- image lifecycle (the chain's build/pull/present/reclaim seam) --------

    def _references(self) -> tuple[str, ...]:
        """The local image names the provisioning precedence leaves."""
        return docker_images.provisioned_references(
            self.images, dockerfile=self.dockerfile, registry=self.registry
        )

    def provision(self, run: CommandRunner) -> tuple[str, ...]:
        outcomes = docker_images.provision_images(
            run,
            self.images,
            dockerfile=self.dockerfile,
            context=self.dockerfile_context,
            registry=self.registry,
            error=ImageError,
        )
        return tuple(outcome.detail for outcome in outcomes)

    def reclaim(self, run: CommandRunner) -> tuple[str, ...]:
        return tuple(
            label
            for reference in self._references()
            for label in docker_images.remove(run, reference)
        )