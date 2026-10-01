"""The `targetctl` strategy: WebExploitBench on the LOCAL eval host.

WebExploitBench targets run on the same host as the eval orchestrator (D45):
the platform scaffold - the dataset checkout, `scripts/targetctl`, and the
target images - was moved off the remote workshop host onto the eval server, so
deployment is a local command and no ssh is involved. Each target is fronted on
`http://<synthetic-host>/` (port 80) by the shared host-level nginx container
(`orchestrator/front.py`), exactly like the `image` and `compose` strategies,
and the instance kali aliases the synthetic Host to the Docker host gateway
resolved to a NUMERIC address. `targetctl` publishes on a random host port, so
the front is both the stable bare-domain face and the port discriminator.

On an aarch64 eval host the targets are still amd64 (WebExploitBench is defined
for amd64 base images), so every target command runs with
`DOCKER_DEFAULT_PLATFORM=linux/amd64` and the host's qemu binfmt emulation (D46).
"""
from __future__ import annotations

import os
import re
import shlex
import time
from dataclasses import replace
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from orchestrator import docker as docker_images
from orchestrator import front, routing
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.targets.base import (
    Sleep,
    TargetContext,
    TargetError,
    TargetNotReadyError,
    TargetUpResult,
    wait_ready,
)

# The local platform scaffold: the dataset checkout the target is built from.
DEFAULT_WEB_DIR = "~/WebExploitBench"
DEFAULT_REPO_URL = "https://github.com/AgentCyberRange/WebExploitBench.git"
DEFAULT_READY_RETRIES = 60
DEFAULT_READY_INTERVAL_S = 5.0
# WebExploitBench is defined for amd64 base images; the eval host emulates them
# (D46), so every target command selects the amd64 platform explicitly.
DEFAULT_PLATFORM = "linux/amd64"
PLAN_PORT = "<published-port>"
PLAN_IP = "<target-ip>"

_UI_URL_RE = re.compile(r"UI:\s*(https?://\S+)")
_ANY_URL_RE = re.compile(r"https?://\S+")


class TargetctlError(TargetError):
    """A targetctl deployment command failed or its output could not be parsed."""


def parse_targetctl_url(output: str) -> str:
    """Pick the accessible URL from `targetctl up` output.

    Prefer an explicit `UI:` line; otherwise the first URL with no path (a bare
    host:port), matching the shape `targetctl` prints.
    """
    match = _UI_URL_RE.search(output)
    if match:
        return match.group(1)
    for candidate in _ANY_URL_RE.finditer(output):
        url = candidate.group(0)
        parsed = urlparse(url)
        if parsed.path in ("", "/"):
            return url
    raise TargetctlError("targetctl output carries no accessible URL")


def url_port(url: str) -> str:
    port = urlparse(url).port
    if port is None:
        raise TargetctlError(f"targetctl URL carries no port: {url!r}")
    return str(port)


class TargetctlStrategy:
    """One WebExploitBench target run on the local eval host."""

    def __init__(
        self,
        context: TargetContext,
        *,
        env: Mapping[str, str] | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        params = context.run.target_config.params
        environment = os.environ if env is None else env
        self.context = context
        self.host = context.host
        self.paths = context.paths
        self.registry = context.registry
        self.images = tuple(context.run.images)
        self.dockerfile = context.run.target_config.dockerfile
        self.dockerfile_context = context.run.target_config.dockerfile_context
        self._sleep = sleep or time.sleep
        self.target = str(params["target"])
        self.web_dir = str(
            params.get("web_dir")
            or environment.get("EVAL_WEB_DIR")
            or DEFAULT_WEB_DIR
        )
        self.repo_url = str(params.get("repo_url") or DEFAULT_REPO_URL)
        self.platform = str(
            params.get("platform")
            or environment.get("EVAL_TARGET_PLATFORM")
            or DEFAULT_PLATFORM
        )
        self.ready_retries = int(
            params.get("ready_retries")
            or environment.get("EVAL_READY_RETRIES")
            or DEFAULT_READY_RETRIES
        )
        self.ready_interval_s = float(
            params.get("ready_interval_s")
            or environment.get("EVAL_READY_INTERVAL_S")
            or DEFAULT_READY_INTERVAL_S
        )

    @property
    def front_url(self) -> str:
        return f"http://{self.host}/"

    # --- command builders (shared by plan and execute) ------------------------

    def _env(self) -> dict[str, str]:
        return {"DOCKER_DEFAULT_PLATFORM": self.platform}

    def _checkout_cmd(self) -> Command:
        # S5: quote interpolated config; web_dir/repo_url may carry spaces or
        # shell metacharacters and are operator-supplied.
        web_dir = shlex.quote(self.web_dir)
        script = (
            f"test -d {web_dir}/.git || "
            f"(git clone --depth 1 {shlex.quote(self.repo_url)} {web_dir})"
        )
        return Command(
            argv=("sh", "-c", script),
            description=f"ensure {self.web_dir}",
        )

    def _targetctl(self, *args: str) -> Command:
        script = str(Path(self.web_dir) / "scripts" / "targetctl")
        return Command(
            argv=(script, *args),
            env=self._env(),
            description=f"targetctl {' '.join(args)}",
        )

    def _probe_cmd(self, port: int | str) -> Command:
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
                "-H",
                f"Host: {self.host}",
                f"http://{routing.LOOPBACK}:{port}/",
            ),
            description=f"probe {self.host}",
        )

    # --- lifecycle ------------------------------------------------------------

    def plan_up(self) -> list[Command]:
        return [
            self._checkout_cmd(),
            self._targetctl("build", self.target),
            self._targetctl("up", self.target),
            front.plan_conf_apply(self.host, PLAN_PORT),
            self._probe_cmd(PLAN_PORT),
            routing.plan_gateway_resolve(self.paths),
            routing.kali_alias_command(self.paths, self.host, PLAN_IP),
        ]

    def up(self, run: CommandRunner) -> TargetUpResult:
        checkout = self._checkout_cmd()
        require_ok(run(checkout), checkout, error=TargetctlError)
        build = self._targetctl("build", self.target)
        require_ok(run(build), build, error=TargetctlError)

        up_cmd = self._targetctl("up", self.target)
        output = require_ok(run(up_cmd), up_cmd, error=TargetctlError).stdout
        port = url_port(parse_targetctl_url(output))
        backend = f"http://{routing.LOOPBACK}:{port}"

        front_conf = front.plan_conf_apply(self.host, port)
        require_ok(run(front_conf), front_conf, error=TargetctlError)

        ready = wait_ready(
            run,
            self._probe_cmd(port),
            retries=self.ready_retries,
            interval_s=self.ready_interval_s,
            sleep=self._sleep,
        )
        if not ready:
            raise TargetNotReadyError(
                f"target {self.target!r} did not answer at {self.front_url} "
                f"after {self.ready_retries} probes"
            )

        alias = routing.kali_alias_command(self.paths, self.host, self._gateway_address(run))
        require_ok(run(alias), alias, error=TargetctlError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=backend, ready=True
        )

    def _gateway_address(self, run: CommandRunner) -> str:
        """Resolve the Docker host gateway to a numeric address, failing loudly (SP1)."""
        try:
            return routing.resolve_gateway(run, self.paths)
        except routing.RoutingError as exc:
            raise TargetctlError(str(exc)) from exc

    def plan_down(self) -> list[Command]:
        return [
            self._targetctl("down", self.target),
            front.plan_conf_remove(self.host),
            routing.kali_clear_command(self.paths, self.host),
        ]

    def down(self, run: CommandRunner) -> None:
        # SP3: the target process and the front are best-effort (either may
        # already be gone); the alias is ALWAYS cleared so teardown leaves
        # nothing behind. Failures are aggregated and raised at the end, once
        # cleanup has run, so the orchestrator can report and continue.
        down_cmd = self._targetctl("down", self.target)
        down_result = run(down_cmd)
        front_conf = front.plan_conf_remove(self.host)
        front_result = run(front_conf)
        clear = routing.kali_clear_command(self.paths, self.host)
        clear_result = run(clear)
        errors: list[str] = []
        if front_result.returncode != 0:
            errors.append(
                f"front removal failed: "
                f"{front_result.stderr.strip() or front_result.stdout.strip()}"
            )
        if clear_result.returncode != 0:
            errors.append(
                f"alias clear failed: "
                f"{clear_result.stderr.strip() or clear_result.stdout.strip()}"
            )
        if down_result.returncode != 0:
            detail = down_result.stderr.strip() or down_result.stdout.strip()
            errors.append(f"targetctl down failed ({down_result.returncode}): {detail}")
        if errors:
            raise TargetctlError("; ".join(errors))

    def plan_status(self) -> list[Command]:
        return [self._targetctl("ps", self.target)]

    def status(self, run: CommandRunner) -> str:
        command = self._targetctl("ps", self.target)
        return require_ok(run(command), command, error=TargetctlError).stdout

    # --- image lifecycle (the chain's build/pull/present/reclaim seam) --------

    def _wrap(self, command: Command) -> Command:
        """Run a docker primitive locally, selecting the target platform (D46)."""
        return replace(command, env={**(command.env or {}), **self._env()})

    def provision(self, run: CommandRunner) -> tuple[str, ...]:
        """Provision this target's images by the precedence, locally.

        A declared Dockerfile builds the app image, a configured registry pulls
        the images, and otherwise the images must already be present. Without
        declared images the idempotent `targetctl build` still builds them
        (`--force` is never used: a forced rebuild is drift, not freshness).
        """
        if not self.images:
            build = self._targetctl("build", self.target)
            require_ok(run(build), build, error=TargetctlError)
            return (f"targetctl build {self.target}",)
        outcomes = docker_images.provision_images(
            run,
            self.images,
            dockerfile=self.dockerfile,
            context=self.dockerfile_context,
            registry=self.registry,
            wrap=self._wrap,
            error=TargetctlError,
        )
        return tuple(outcome.detail for outcome in outcomes)

    def reclaim(self, run: CommandRunner) -> tuple[str, ...]:
        """Remove this target's images, keeping shared bases; best-effort.

        Declared images are removed by their provisioned reference; otherwise
        the built app images are matched by the `pentestbench-<target>` prefix
        (e.g. `pentestbench-siyucms-web`), which reclaims the target's own
        layers without touching the shared evaluator or the bases other targets
        need. An absent image is success; a genuine removal failure is reported
        through the returned label rather than aborting the chain.
        """
        if not self.images:
            pattern = f"pentestbench-{self.target}"
            script = (
                "docker image ls --format '{{.Repository}}:{{.Tag}}' "
                f"| grep -F {shlex.quote(pattern)} | xargs -r docker image rm"
            )
            command = Command(
                argv=("sh", "-c", script),
                env=self._env(),
                description=f"reclaim {pattern}*",
            )
            result = run(command)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                return (f"reclaim {self.target} failed: {detail}",)
            return (f"reclaim pentestbench-{self.target}*",)
        references = docker_images.provisioned_references(
            self.images, dockerfile=self.dockerfile, registry=self.registry
        )
        labels: list[str] = []
        for reference in references:
            command = self._wrap(docker_images.plan_remove(reference))
            result = run(command)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                labels.append(f"reclaim {reference} failed: {detail}")
            else:
                labels.append(f"rm {reference}")
        return tuple(labels)
