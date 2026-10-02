"""The `targetctl` strategy: WebExploitBench on the LOCAL eval host.

WebExploitBench targets run on the same host as the eval orchestrator (D45):
the platform scaffold - the dataset checkout, `scripts/targetctl`, and the
target images - lives at the dataset's platform root. Each target is fronted on
`http://<synthetic-host>/` (port 80) by the shared host-level nginx container
(`orchestrator/front.py`), exactly like the `image` and `compose` strategies,
and the instance kali aliases the synthetic Host to the Docker host gateway
resolved to a NUMERIC address. `targetctl` publishes on a random host port, so
the front is both the stable bare-domain face and the port discriminator.

The bring-up data now comes from the resolved domain objects (spec #301): the
checkout and repo from the `BenchmarkDataset` (`platform_root`, `repo`), the
target name, compose, platform, and `reclaimable` from the
`TargetConfiguration`. Provisioning binds the target's canonical tags by
store -> pull -> build; reclaim removes exactly those tags, and only when the
target is reclaimable. Readiness is the helper's bounded plan, never a blocking
`up`.

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
from orchestrator.datasets.base import canonical_tag
from orchestrator.docker import ProvisionOutcome
from orchestrator.readiness import wait_readiness
from orchestrator.targets.base import (
    Sleep,
    TargetContext,
    TargetError,
    TargetNotReadyError,
    TargetUpResult,
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

    Prefer an explicit `UI:` line; otherwise the first URL that carries a port.
    A target may expose a path (ofbiz prints
    `http://0.0.0.0:<port>/webtools/control/main`), so the path is not a filter:
    only the port is needed to point the front at the backend.
    """
    match = _UI_URL_RE.search(output)
    if match:
        return match.group(1)
    for candidate in _ANY_URL_RE.finditer(output):
        url = candidate.group(0)
        if urlparse(url).port is not None:
            return url
    raise TargetctlError("targetctl output carries no accessible URL")


def url_port(url: str) -> str:
    port = urlparse(url).port
    if port is None:
        raise TargetctlError(f"targetctl URL carries no port: {url!r}")
    return str(port)


def targetctl_project(target: str) -> str:
    """The compose project `scripts/targetctl` names a target, `web_<sanitized>`.

    The server scaffold lowercases the target and replaces every non-alphanumeric
    character with `_` (`project_name`/`sanitize_project_part`). The readiness
    poll and the generated-compose path must use the same name (D49).
    """
    return "web_" + re.sub(r"[^a-z0-9]", "_", target.lower())


class TargetctlStrategy:
    """One WebExploitBench target run on the local eval host."""

    def __init__(
        self,
        context: TargetContext,
        *,
        env: Mapping[str, str] | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        config = context.target_config
        environment = os.environ if env is None else env
        self.context = context
        self.config = config
        self.host = context.host
        self.paths = context.paths
        self.target = config.target
        # The platform root is the dataset's checkout; a `~`-anchored root is
        # expanded here because the checkout runs through `shlex.quote` (which
        # quotes the tilde literal) and the targetctl argv never goes through a
        # shell, so a literal `~/...` would never resolve.
        if context.dataset.platform_root:
            web_dir = str(context.dataset.bank_root())
        else:
            web_dir = DEFAULT_WEB_DIR
        self.web_dir = os.path.expanduser(environment.get("EVAL_WEB_DIR") or web_dir)
        self.repo_url = str(context.dataset.repo or DEFAULT_REPO_URL)
        self.platform = str(
            config.platform
            or environment.get("EVAL_TARGET_PLATFORM")
            or DEFAULT_PLATFORM
        )
        # A per-target window (config) wins over the orchestrator-wide env; the
        # default (60 x 5s) is enough once targets run natively on amd64 (D48).
        self.ready_retries = config.ready_retries or int(
            environment.get("EVAL_READY_RETRIES") or DEFAULT_READY_RETRIES
        )
        self.ready_interval_s = config.ready_interval_s or float(
            environment.get("EVAL_READY_INTERVAL_S") or DEFAULT_READY_INTERVAL_S
        )
        # The D45 server scaffold owns the compose project name (`web_<target>`);
        # the readiness poll and the generated-compose path must speak it, or they
        # address a project/file that does not exist (D49).
        self.project = targetctl_project(self.target)
        # D49: the dataset's excluded services (the WebExploitBench evaluator)
        # merged with any the target itself excludes, de-duplicated, order-stable.
        excluded: list[str] = []
        for service in (*context.dataset.exclude_services, *config.exclude_services):
            if service not in excluded:
                excluded.append(service)
        self.exclude_services = tuple(excluded)
        self.canonical_tags = context.helper.canonical_tags(self.target, config)
        self.reclaimable = config.reclaimable
        self._sleep = sleep or time.sleep

    @property
    def front_url(self) -> str:
        return f"http://{self.host}/"

    # --- command builders (shared by plan and execute) ------------------------

    def _env(self) -> dict[str, str]:
        return {
            "DOCKER_DEFAULT_PLATFORM": self.platform,
            # The benchmark's own `up` waits for dependency healthchecks, which
            # under amd64 emulation blocks for minutes and hides a ready stack
            # behind a slow one. targetctl then starts the dependency chain in
            # order without waiting; the orchestrator asserts readiness itself,
            # under a bounded window, once `up` returns.
            "TARGETCTL_NO_WAIT_DEPS": "1",
            # D48: the chain provisions every image (store -> pull -> build)
            # before `up`. Compose v5 otherwise rebuilds a pulled image that
            # lacks Compose's own labels, so `up` is told never to build; the
            # explicit `targetctl build` step stays the only build path.
            "TARGETCTL_NO_BUILD": "1",
            # D49: services kept out of the target's stack. `scripts/targetctl`
            # renders them behind a Compose `profiles` gate, so `up` never starts
            # them without editing the frozen upstream compose.
            "TARGETCTL_EXCLUDE_SERVICES": ",".join(self.exclude_services),
        }

    def _checkout_cmd(self) -> Command:
        # S5: quote interpolated config; web_dir/repo_url may carry spaces or
        # shell metacharacters and are operator-supplied.
        web_dir = shlex.quote(self.web_dir)
        # The bundled targets vendor their codebase as git submodules, and
        # `targetctl build` refuses an uninitialized one, so the clone recurses
        # (and an existing checkout is repaired in place).
        script = (
            f"test -d {web_dir}/.git || "
            f"(git clone --depth 1 --recurse-submodules "
            f"{shlex.quote(self.repo_url)} {web_dir})"
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

    def _readiness_plan(self):
        return self.context.helper.readiness_plan(
            self.target,
            self.config,
            project=self.project,
            port=self.config.port,
            host=self.host,
            retries=self.ready_retries,
            interval_s=self.ready_interval_s,
            # D49: when services are excluded, `scripts/targetctl` runs `up` from
            # a generated compose; the readiness poll must read that same stack,
            # not the original (which still names the excluded service).
            compose_file=self._effective_compose_path(),
        )

    def _effective_compose_path(self) -> str | None:
        """The generated compose `scripts/targetctl` writes, or None.

        `scripts/targetctl` places it at
        `<web_dir>/.targetctl/compose/<project>.yml` (D49). None when nothing is
        excluded, so the poll reads the target's own compose.
        """
        if not self.exclude_services:
            return None
        return str(
            Path(self.web_dir) / ".targetctl" / "compose" / f"{self.project}.yml"
        )

    # --- lifecycle ------------------------------------------------------------

    def plan_up(self) -> list[Command]:
        return [
            self._checkout_cmd(),
            self._targetctl("build", self.target),
            self._targetctl("up", self.target),
            front.plan_conf_apply(self.host, PLAN_PORT),
            self._readiness_plan().probe,
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

        alias = routing.kali_alias_command(self.paths, self.host, self._gateway_address(run))
        require_ok(run(alias), alias, error=TargetctlError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=backend, ready=True
        )

    def await_ready(self, run: CommandRunner) -> str:
        plan = self._readiness_plan()
        if not wait_readiness(run, plan, sleep=self._sleep):
            raise TargetNotReadyError(
                f"target {self.target!r} did not become ready at {self.front_url}"
            )
        return f"{plan.kind} ready"

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

    # --- image lifecycle (the chain's store/pull/build/reclaim seam) ----------

    def _wrap(self, command: Command) -> Command:
        """Run a docker primitive locally, selecting the target platform (D46)."""
        return replace(command, env={**(command.env or {}), **self._env()})

    def _compose_refs(self) -> dict[str, str]:
        """canonical tag -> the compose's own built reference for that service.

        The mapping is read lazily (only when the store and pull paths both miss)
        so a fully present or fully pulled target never touches the compose file.
        """
        built = self.context.helper.built_images(self.target, self.config)
        return {
            canonical_tag(self.context.dataset.id, self.target, item.service): item.reference
            for item in built
        }

    def _pull_refs(self) -> dict[str, str]:
        """canonical tag -> pull reference: explicit config first, then registry.

        An explicit `config.pull` wins; otherwise a dataset that declares a
        `registry` resolves each built service to `<registry>:<target>-<service>`,
        the tag the CI image workflow pushes (D48). No registry leaves the target
        to build on the host.
        """
        refs = dict(self.config.pull)
        registry = self.context.dataset.registry
        if not registry:
            return refs
        for item in self.context.helper.built_images(self.target, self.config):
            tag = canonical_tag(self.context.dataset.id, self.target, item.service)
            reference = docker_images.registry_reference(registry, self.target, item.service)
            if reference:
                refs.setdefault(tag, reference)
        return refs

    def provision(self, run: CommandRunner) -> tuple[ProvisionOutcome, ...]:
        """Bind this target's canonical tags by store -> pull -> build.

        A store hit is left alone; a declared pull reference is pulled and bound;
        otherwise `targetctl build` runs (once) and the produced compose images
        are bound to their canonical tags.
        """

        def build() -> dict[str, str]:
            command = self._targetctl("build", self.target)
            require_ok(run(command), command, error=TargetctlError)
            return self._compose_refs()

        outcomes = docker_images.provision_tags(
            run,
            self.canonical_tags,
            pull_refs=self._pull_refs(),
            build=build,
            wrap=self._wrap,
            error=TargetctlError,
        )
        # The compose names its own image references, not the canonical tags, so
        # a pulled registry image must also carry the compose reference for the
        # target's own `up` to find it locally. A target that declares its own
        # `images` and has no readable compose has nothing to rebind.
        try:
            compose_refs = self._compose_refs()
        except (OSError, ValueError):
            compose_refs = {}
        for outcome in outcomes:
            if outcome.source != docker_images.PULL:
                continue
            compose_ref = compose_refs.get(outcome.tag)
            if not compose_ref:
                continue
            command = self._wrap(docker_images.plan_tag(outcome.reference, compose_ref))
            require_ok(run(command), command, error=TargetctlError)
        return outcomes

    def reclaim(self, run: CommandRunner) -> tuple[str, ...]:
        """Remove this target's canonical tags; best-effort and opt-in.

        Only a `reclaimable` target is reclaimed, so a base or shared image is
        never removed by a target that did not opt in. An absent image is
        success; a genuine removal failure is reported through the label rather
        than aborting the chain.
        """
        if not self.reclaimable:
            return ()
        labels: list[str] = []
        for tag in self.canonical_tags:
            labels.extend(docker_images.remove(run, tag, wrap=self._wrap))
        return tuple(labels)
