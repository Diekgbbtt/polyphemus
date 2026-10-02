"""The `image` strategy: a local pullable container.

The target image comes from the resolved `TargetConfiguration` (spec #301): the
run reference (`image`), the published port, the platform, and the target's
canonical tags (`images`). It is published on the host with docker's default
binding (all interfaces, `0.0.0.0`). It is fronted on `http://<host>/` (port 80)
by the shared host-level nginx container (`orchestrator/front.py`, SP2), and the
instance kali aliases the synthetic Host to the Docker host gateway resolved to a
NUMERIC address (SP1) - never `127.0.0.1`, because kali is not on the host
network and `127.0.0.1` is kali itself. The gateway (the bridge's `172.x.0.1`)
is a host interface, so the publish must not be loopback-only or neither kali
nor the front could reach it. `down` removes exactly the container it created,
idempotently (an absent container is success), and always clears the alias.

`up` starts the container and stops there; readiness is verified separately, and
never blocks, through the helper's bounded plan. Provisioning binds the target's
canonical tags by store -> pull (no local build recipe); reclaim removes exactly
those tags, and only when the target is reclaimable.
"""
from __future__ import annotations

import time
from dataclasses import replace

from orchestrator import docker as docker_images
from orchestrator import front, routing
from orchestrator.commands import Command, CommandRunner, is_absent_container, require_ok
from orchestrator.docker import ProvisionOutcome
from orchestrator.ids import short_id
from orchestrator.readiness import wait_readiness
from orchestrator.targets.base import (
    Sleep,
    TargetContext,
    TargetError,
    TargetNotReadyError,
    TargetUpResult,
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
        config = context.target_config
        self.context = context
        self.config = config
        self.host = context.host
        self.paths = context.paths
        self.image = str(config.image)
        self.port = int(config.port)
        self.internal_port = int(config.internal_port or DEFAULT_INTERNAL_PORT)
        self.ready_path = config.ready_path
        self.name = config.name or f"ph-target-{short_id(context.host)}"
        # An amd64-only image on an aarch64 host needs an explicit platform so
        # the run is emulated rather than "no matching manifest" (D46). Empty
        # keeps docker's native default.
        self.platform = config.platform
        self.canonical_tags = context.helper.canonical_tags(config.target, config)
        self.reclaimable = config.reclaimable
        self._sleep = sleep or time.sleep

    @property
    def backend(self) -> str:
        return f"http://{LOOPBACK}:{self.port}"

    @property
    def front_url(self) -> str:
        return f"http://{self.host}/"

    def _env(self) -> dict[str, str]:
        return {"DOCKER_DEFAULT_PLATFORM": self.platform} if self.platform else {}

    def _wrap(self, command: Command) -> Command:
        """Run a docker primitive locally, selecting the target platform (D46)."""
        return replace(command, env={**(command.env or {}), **self._env()})

    def _run_cmd(self) -> Command:
        argv: tuple[str, ...] = ("docker", "run", "-d", "--name", self.name)
        if self.platform:
            argv += ("--platform", self.platform)
        argv += (
            "--publish",
            # No host IP: docker's default binds all interfaces, including
            # the bridge gateway `host.docker.internal` resolves to. A
            # `127.0.0.1:` prefix would be unreachable from kali (Linux).
            f"{self.port}:{self.internal_port}",
            self.image,
        )
        return Command(argv=argv, description=f"run image {self.image}")

    def _remove_cmd(self) -> Command:
        return Command(
            argv=("docker", "rm", "-f", self.name),
            description=f"remove {self.name}",
        )

    def _readiness_plan(self):
        return self.context.helper.readiness_plan(
            self.config.target,
            self.config,
            project=self.name,
            port=self.port,
            host=self.host,
        )

    def plan_up(self) -> list[Command]:
        return [
            self._run_cmd(),
            self._readiness_plan().probe,
            front.plan_conf_apply(self.host, self.port),
            routing.plan_gateway_resolve(self.paths),
            routing.kali_alias_command(self.paths, self.host, routing.PLAN_GATEWAY_IP),
        ]

    def up(self, run: CommandRunner) -> TargetUpResult:
        run_cmd = self._run_cmd()
        require_ok(run(run_cmd), run_cmd, error=ImageError)
        conf = front.plan_conf_apply(self.host, self.port)
        require_ok(run(conf), conf, error=ImageError)
        alias = routing.kali_alias_command(
            self.paths, self.host, self._gateway_address(run)
        )
        require_ok(run(alias), alias, error=ImageError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=self.backend, ready=True
        )

    def await_ready(self, run: CommandRunner) -> str:
        plan = self._readiness_plan()
        if not wait_readiness(run, plan, sleep=self._sleep):
            raise TargetNotReadyError(
                f"image target {self.image!r} did not become ready at {self.front_url}"
            )
        return f"{plan.kind} ready"

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

    # --- image lifecycle (the chain's store/pull/reclaim seam) ----------------

    def provision(self, run: CommandRunner) -> tuple[ProvisionOutcome, ...]:
        """Bind this target's canonical tags by store -> pull (no local build).

        A store hit is left alone; otherwise a declared pull reference is pulled
        and bound. An absent tag with no pull reference is a hard failure.
        """
        return docker_images.provision_tags(
            run,
            self.canonical_tags,
            pull_refs=self.config.pull,
            build=None,
            wrap=self._wrap,
            error=ImageError,
        )

    def reclaim(self, run: CommandRunner) -> tuple[str, ...]:
        """Remove this target's canonical tags; best-effort and opt-in."""
        if not self.reclaimable:
            return ()
        labels: list[str] = []
        for tag in self.canonical_tags:
            labels.extend(docker_images.remove(run, tag, wrap=self._wrap))
        return tuple(labels)
