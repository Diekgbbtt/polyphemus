"""The `compose` strategy: a local pullable compose stack.

The stack comes from the resolved `TargetConfiguration` (spec #301): the compose
file (relative to the target's platform bank entry, via the dataset helper), the
published port, the project, and the target's canonical tags. It runs under its
own compose project (`ph-target-<short>`), distinct from the instance projects.
It is fronted on `http://<host>/` (port 80) by the shared host-level nginx
container (`orchestrator/front.py`, SP2), and the instance kali aliases the
synthetic Host to the Docker host gateway resolved to a NUMERIC address (SP1) -
never `127.0.0.1`, because kali is not on the host network and `127.0.0.1` is
kali itself. The gateway is a host interface, so the target compose file MUST
publish on an interface it can reach (all interfaces); a loopback-only
(`127.0.0.1:<port>:...`) binding is unreachable from kali and the front. `down`
removes that project's containers and volumes, idempotently, and always clears
the alias.

`up` starts the stack and stops there; readiness is verified separately, and
never blocks, through the helper's bounded compose-health plan. Provisioning
binds the target's canonical tags by store -> pull -> build (the stack's own
`docker compose build`); reclaim removes exactly those tags, and only when the
target is reclaimable.
"""
from __future__ import annotations

import time
from dataclasses import replace

from orchestrator import docker as docker_images
from orchestrator import front, routing
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.datasets.base import canonical_tag
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
        config = context.target_config
        self.context = context
        self.config = config
        self.host = context.host
        self.paths = context.paths
        self.compose_file = str(context.helper.compose_path(config.target, config))
        self.port = int(config.port)
        self.ready_path = config.ready_path
        self.project = config.project or f"ph-target-{short_id(context.host)}"
        self.cwd = config.cwd or str(context.paths.worktree)
        # An amd64-only stack on an aarch64 host needs an explicit platform so
        # the build/run is emulated rather than "no matching manifest" (D46).
        # Empty keeps docker's native default.
        self.platform = config.platform
        self.canonical_tags = context.helper.canonical_tags(config.target, config)
        self.reclaimable = config.reclaimable
        self._sleep = sleep or time.sleep

    def _env(self) -> dict[str, str]:
        return {"DOCKER_DEFAULT_PLATFORM": self.platform} if self.platform else {}

    def _wrap(self, command: Command) -> Command:
        """Run a docker primitive locally, selecting the target platform (D46)."""
        return replace(command, env={**(command.env or {}), **self._env()})

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
        return Command(
            argv=argv,
            cwd=self.cwd,
            env=self._env() or None,
            description=f"target compose {' '.join(verbs)}",
        )

    def _readiness_plan(self):
        return self.context.helper.readiness_plan(
            self.config.target,
            self.config,
            project=self.project,
            port=self.port,
            host=self.host,
        )

    def plan_up(self) -> list[Command]:
        return [
            self._compose("up", "-d"),
            *self._readiness_plan().commands,
            front.plan_conf_apply(self.host, self.port),
            routing.plan_gateway_resolve(self.paths),
            routing.kali_alias_command(self.paths, self.host, routing.PLAN_GATEWAY_IP),
        ]

    def up(self, run: CommandRunner) -> TargetUpResult:
        up_cmd = self._compose("up", "-d")
        require_ok(run(up_cmd), up_cmd, error=ComposeTargetError)
        conf = front.plan_conf_apply(self.host, self.port)
        require_ok(run(conf), conf, error=ComposeTargetError)
        alias = routing.kali_alias_command(
            self.paths, self.host, self._gateway_address(run)
        )
        require_ok(run(alias), alias, error=ComposeTargetError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=self.backend, ready=True
        )

    def await_ready(self, run: CommandRunner) -> str:
        plan = self._readiness_plan()
        if not wait_readiness(run, plan, sleep=self._sleep):
            raise TargetNotReadyError(
                f"compose target {self.compose_file!r} did not become ready "
                f"at {self.front_url}"
            )
        return f"{plan.kind} ready"

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

    # --- image lifecycle (the chain's store/pull/build/reclaim seam) ----------

    def _build_mapping(self) -> dict[str, str]:
        """canonical tag -> the compose's own built reference for that service."""
        built = self.context.helper.built_images(self.config.target, self.config)
        return {
            canonical_tag(self.context.dataset.id, self.config.target, item.service): item.reference
            for item in built
        }

    def provision(self, run: CommandRunner) -> tuple[ProvisionOutcome, ...]:
        """Bind this target's canonical tags by store -> pull -> build.

        A store hit is left alone; a declared pull reference is pulled and bound;
        otherwise `docker compose build` runs (once) and the produced images are
        bound to their canonical tags.
        """

        def build() -> dict[str, str]:
            command = self._compose("build")
            require_ok(run(command), command, error=ComposeTargetError)
            return self._build_mapping()

        return docker_images.provision_tags(
            run,
            self.canonical_tags,
            pull_refs=self.config.pull,
            build=build,
            wrap=self._wrap,
            error=ComposeTargetError,
        )

    def reclaim(self, run: CommandRunner) -> tuple[str, ...]:
        """Remove this target's canonical tags; best-effort and opt-in."""
        if not self.reclaimable:
            return ()
        labels: list[str] = []
        for tag in self.canonical_tags:
            labels.extend(docker_images.remove(run, tag, wrap=self._wrap))
        return tuple(labels)
