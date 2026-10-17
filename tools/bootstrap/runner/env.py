"""Target-environment drivers: accurate signals, no symbolic verdicts.

The architecture doc (section 5) splits the environment seam in two:

* raw actuators - `up(target)` and `down(target)`, each returning the raw
  `CommandResult` (the exit code and the command text are evidence, not a
  boolean);
* one READ-ONLY observation - `observe(target)` returns container facts from the
  docker engine, the target's accessible URL as targetctl itself prints it, and
  the URL's raw HTTP status.

Interpretation lives OUTSIDE this module's drivers: `not_ready_reason` and
`leftovers` are pure helpers (readiness reuses the platform's own
`ServiceHealth.ready` rules and its non-5xx HTTP rule), and the orchestrator is
the only caller that turns them into a decision. A driver never returns "ready".

Three drivers cover the environments (section 4 of the audit):

* `SshServerEnv` - the W2 regeneration path. The lifecycle runs ONLY through the
  pinned `/root/wb` wrapper over the configured ssh alias, because that wrapper
  owns the server's environment contract (amd64 emulation, native redis,
  excluded evaluator). It never issues a prune of any kind: the pre-pulled
  images on the shared server are the reason the plan is a shell-out here.
* `LocalEnv` - `bash scripts/targetctl` in a local checkout, with
  `DOCKER_DEFAULT_PLATFORM=linux/amd64` (arm64 host, amd64 targets) and bash 5.
* `AttachEnv` - lifecycle no-ops; the caller supplies the base URL and owns the
  lifecycle. Container facts are unavailable here by construction, so teardown
  cannot be verified and the orchestrator reports that rather than assuming it.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

from orchestrator.commands import Command, CommandResult
from orchestrator.readiness import ServiceHealth, http_ready
from orchestrator.targets.targetctl import TargetctlError, parse_targetctl_url

# The docker label `scripts/targetctl` sets per compose project, and the one it
# sets per compose service.
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
# The no-answer status curl's `%{http_code}` prints when nothing answered.
NO_ANSWER = "000"

_HTTP_STATUS_RE = re.compile(r"(\d{3})")

Executor = Callable[[Command], CommandResult]


@dataclass(frozen=True)
class ContainerFact:
    """One container of the target's compose project, as the docker engine sees it.

    These are the four facts the architecture doc pins: the engine's own
    `State.Status`, `State.Health.Status`, and `State.ExitCode`, plus the compose
    service label. `state` is lowercased to compose's vocabulary
    (`running`/`exited`/`created`/...), matching the platform's readiness rules.
    """

    name: str
    service: str
    state: str
    health: str
    exit_code: int


@dataclass(frozen=True)
class Observation:
    """One read-only look at a target: containers, targetctl's URL, HTTP status.

    `url` None means targetctl reported none (the target is not up, or the
    transport/parse failed); `http_status` is the target's root status as
    answered, `NO_ANSWER` when nothing answered. Both are raw: the caller
    decides what they mean.
    """

    target: str
    containers: tuple[ContainerFact, ...]
    url: str | None
    http_status: str
    output: str = ""
    returncode: int = 0
    command: tuple[str, ...] = ()
    hello: tuple[CommandResult, ...] = field(default_factory=tuple)


class TargetEnv(Protocol):
    """The environment seam: raw lifecycle commands plus one read-only observation."""

    def up(self, target: str) -> CommandResult: ...

    def down(self, target: str) -> CommandResult: ...

    def observe(self, target: str) -> Observation: ...

    def supported_containers(self) -> bool: ...


class LocalExecutor:
    """The production executor: one bounded subprocess, captured. Never a shell."""

    def __init__(self, *, timeout_s: float = 300.0) -> None:
        self._timeout_s = timeout_s

    def __call__(self, command: Command) -> CommandResult:
        env = None
        if command.env:
            import os

            env = {**os.environ, **command.env}
        try:
            proc = subprocess.run(
                list(command.argv),
                cwd=command.cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except FileNotFoundError as exc:
            return CommandResult(127, "", f"{command.argv[0]}: {exc}")
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", f"timeout after {self._timeout_s}s")
        return CommandResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def ssh_command(ssh: str, remote: str) -> Command:
    """One non-interactive ssh invocation carrying a single remote command.

    The remote command is `shlex.quote`d so every target name and path crosses
    the transport as one shell word; `-o BatchMode=yes` makes an unusable key
    fail immediately instead of hanging on a prompt.
    """
    return Command(
        argv=("ssh", "-o", "BatchMode=yes", ssh, remote),
        description=f"ssh {ssh}",
    )


def shell_remote(argv: Sequence[str]) -> str:
    """Render an argv as the remote shell line ssh will run."""
    return " ".join(shlex.quote(part) for part in argv)


class _DockerEnv:
    """Shared observation logic over the docker engine for one transport."""

    def __init__(self, *, executor: Executor | None = None) -> None:
        self._executor = executor or LocalExecutor()

    # --- each concrete driver supplies these two ---

    def _run(self, remote: Sequence[str]) -> CommandResult:
        """Run one remote (or local) argv through this driver's transport."""
        raise NotImplementedError

    def url_command(self, target: str) -> tuple[str | None, Command | None]:
        """The URL this driver can supply without running a command, plus the command."""
        raise NotImplementedError

    # --- shared: the read-only observation ---

    def ps_command(self, target: str) -> Command:
        """Container ids of the target's compose project, by the project label."""
        return Command(
            argv=(
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label={COMPOSE_PROJECT_LABEL}={project_name(target)}",
                "--format",
                "{{.ID}}",
            ),
            description=f"docker ps {project_name(target)}",
        )

    def inspect_command(self, container_ids: Sequence[str]) -> Command | None:
        if not container_ids:
            return None
        return Command(
            argv=("docker", "inspect", *container_ids),
            description=f"docker inspect {len(container_ids)} container(s)",
        )

    def hello_command(self, base_url: str) -> Command:
        """The target root's HTTP status, as answered (never a readiness verdict)."""
        return Command(
            argv=(
                "curl",
                "-sS",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "-L",
                "--max-time",
                "10",
                "--",
                base_url,
            ),
            description=f"curl -w %{{http_code}} {base_url}",
        )

    def containers(self, target: str) -> tuple[tuple[ContainerFact, ...], CommandResult]:
        listing = self._run_command(self.ps_command(target))
        ids = [line.strip() for line in (listing.stdout or "").splitlines() if line.strip()]
        inspect = self.inspect_command(ids)
        if inspect is None:
            return (), listing
        measured = self._run_command(inspect)
        return parse_containers(measured.stdout or ""), listing

    def observe(self, target: str) -> Observation:
        configured_url, url_cmd = self.url_command(target)
        url_result = self._run_command(url_cmd) if url_cmd is not None else None
        url = configured_url
        if url is None and url_result is not None and url_result.returncode == 0:
            try:
                url = parse_targetctl_url(url_result.stdout or "")
            except TargetctlError:
                url = None
        facts, listing = self.containers(target)
        hello: tuple[CommandResult, ...] = ()
        status = NO_ANSWER
        if url:
            result = self._run_command(self.hello_command(url))
            hello = (result,)
            status = url_hello(result.stdout or "") or NO_ANSWER
        output = "\n".join(
            part
            for part in (
                (url_result.stdout or "").strip() if url_result is not None else "",
                (listing.stdout or "").strip(),
            )
            if part
        )
        returncode = max(
            url_result.returncode if url_result is not None else 0, listing.returncode
        )
        command = url_cmd.argv if url_cmd is not None else ()
        return Observation(
            target=target,
            containers=facts,
            url=url,
            http_status=status,
            output=output,
            returncode=returncode,
            command=tuple(command),
            hello=hello,
        )

    def _run_command(self, command: Command) -> CommandResult:
        """Run a docker/curl probe through this driver's TRANSPORT.

        `_run` is the transport seam: the ssh driver wraps the argv into one
        `ssh <alias> <cmd>` call so the engine probes run beside the containers,
        and the local driver runs it as-is. The executor underneath is the
        process seam (a fake in tests, a subprocess in production).
        """
        return self._run(command.argv)

    def supported_containers(self) -> bool:
        return True


class SshServerEnv(_DockerEnv):
    """The eval server: lifecycle ONLY through the pinned `/root/wb` wrapper, over ssh.

    The wrapper pins `DOCKER_DEFAULT_PLATFORM=linux/amd64`,
    `TARGETCTL_NO_WAIT_DEPS=1`, `TARGETCTL_NO_BUILD=1`,
    `TARGETCTL_EXCLUDE_SERVICES=evaluator`, and `TARGETCTL_NATIVE_SERVICES=redis`
    in its own body (the audit read it verbatim); this driver calls it with the
    target as its only argument and never sets or overrides those pins.

    Nothing here prunes. Between targets `down` plus a targeted container removal
    is allowed by the server rules, `docker system prune -a` is forbidden (it
    destroys the pre-pulled image cache), and the plan is serial, so the driver
    exposes no prune path at all.
    """

    def __init__(
        self,
        *,
        ssh: str,
        targetctl: str = "/root/wb",
        executor: Executor | None = None,
    ) -> None:
        super().__init__(executor=executor)
        self.ssh = ssh
        self.targetctl = targetctl

    def _run(self, remote: Sequence[str]) -> CommandResult:
        return self._executor(ssh_command(self.ssh, shell_remote(remote)))

    def up(self, target: str) -> CommandResult:
        return self._run((self.targetctl, "up", target))

    def down(self, target: str) -> CommandResult:
        return self._run((self.targetctl, "down", target))

    def url_command(self, target: str) -> tuple[str | None, Command]:
        return None, Command(
            argv=(self.targetctl, "ps", target),
            description=f"targetctl ps {target}",
        )

    def lifecycle_hints(self, target: str) -> tuple[str, ...]:
        """The read-only command hints every wrapper carries for this driver."""
        return (
            f"ssh {self.ssh} {self.targetctl} ps {target}",
            f"ssh {self.ssh} {self.targetctl} up {target}",
            f"ssh {self.ssh} {self.targetctl} down {target}",
        )


class LocalEnv(_DockerEnv):
    """The local Docker host: `bash scripts/targetctl`, amd64 emulation, bash 5.

    macOS's system bash is 3.2, which collapses every compose project name to
    `web_` and collides targets; the driver therefore runs the script through an
    explicit bash 5 path when one is configured, and it exports
    `DOCKER_DEFAULT_PLATFORM=linux/amd64` because the targets are amd64 images on
    an arm64 host.
    """

    def __init__(
        self,
        *,
        local_dir: Path,
        bash: str | None = None,
        platform: str = "linux/amd64",
        executor: Executor | None = None,
    ) -> None:
        super().__init__(executor=executor)
        self.local_dir = Path(local_dir)
        self.bash = bash
        self.platform = platform

    @property
    def targetctl(self) -> Path:
        return self.local_dir / "scripts" / "targetctl"

    def _command(self, *args: str) -> Command:
        argv = (str(self.targetctl), *args)
        if self.bash:
            argv = (self.bash, *argv)
        return Command(
            argv=argv,
            cwd=str(self.local_dir),
            env={"DOCKER_DEFAULT_PLATFORM": self.platform},
            description=f"targetctl {' '.join(args)}",
        )

    def _run(self, remote: Sequence[str]) -> CommandResult:
        # `remote` is the docker engine command; locally it runs as-is.
        return self._executor(Command(argv=tuple(remote), description="local docker"))

    def up(self, target: str) -> CommandResult:
        return self._executor(self._command("up", target))

    def down(self, target: str) -> CommandResult:
        return self._executor(self._command("down", target))

    def url_command(self, target: str) -> tuple[str | None, Command]:
        return None, self._command("ps", target)

    def lifecycle_hints(self, target: str) -> tuple[str, ...]:
        prefix = f"{self.bash} " if self.bash else ""
        return (
            f"DOCKER_DEFAULT_PLATFORM={self.platform} {prefix}{self.targetctl} ps {target}",
            f"DOCKER_DEFAULT_PLATFORM={self.platform} {prefix}{self.targetctl} up {target}",
            f"DOCKER_DEFAULT_PLATFORM={self.platform} {prefix}{self.targetctl} down {target}",
        )


class AttachEnv(_DockerEnv):
    """An already-running target: the caller owns the lifecycle and the URL.

    `up`/`down` are no-ops that report success, and the base URL comes from the
    config. Container facts are NOT available (the caller's environment is not
    ours to inspect), so `supported_containers` is False and the orchestrator
    records teardown as unverifiable instead of pretending it observed zero.
    """

    def __init__(self, *, base_url: str, executor: Executor | None = None) -> None:
        super().__init__(executor=executor)
        self.base_url = base_url

    def _run(self, remote: Sequence[str]) -> CommandResult:
        return CommandResult(0, "", "")

    def up(self, target: str) -> CommandResult:
        return CommandResult(0, "", "")

    def down(self, target: str) -> CommandResult:
        return CommandResult(0, "", "")

    def url_command(self, target: str) -> tuple[str | None, None]:
        return self.base_url, None

    def containers(self, target: str) -> tuple[tuple[ContainerFact, ...], CommandResult]:
        return (), CommandResult(0, "", "")

    def observe(self, target: str) -> Observation:
        result = self._executor(self.hello_command(self.base_url))
        return Observation(
            target=target,
            containers=(),
            url=self.base_url,
            http_status=url_hello(result.stdout or "") or NO_ANSWER,
            hello=(result,),
        )

    def lifecycle_hints(self, target: str) -> tuple[str, ...]:
        return (f"target {target} is externally managed at {self.base_url}",)

    def supported_containers(self) -> bool:
        return False


# --- pure interpretation helpers (the orchestrator's vocabulary) -------------


def project_name(target: str) -> str:
    """The compose project `scripts/targetctl` names a target: `web_<sanitized>`.

    Mirrors `orchestrator.targets.targetctl.targetctl_project` (the server
    scaffold lowercases the target and replaces every non-alphanumeric character
    with `_`), pinned by a test against targetctl's own examples.
    """
    return "web_" + re.sub(r"[^a-z0-9]", "_", target.lower())


def containers_ready(containers: Sequence[ContainerFact]) -> bool:
    """The platform's readiness rules over the engine's facts: every one ready.

    Single source of truth: each fact becomes a `ServiceHealth` and its own
    `.ready` predicate decides (healthy, running with no healthcheck, or a clean
    one-shot exit). Like the platform's compose poll, an empty set is NOT ready.
    """
    if not containers:
        return False
    return all(
        ServiceHealth(
            service=fact.service,
            state=fact.state,
            health=fact.health,
            exit_code=fact.exit_code,
        ).ready
        for fact in containers
    )


def not_ready_reason(observation: Observation, *, require_http: bool = True) -> str | None:
    """Why the target is not ready, or None when every signal agrees it is.

    Composite, like the platform's readiness plan: every container must be ready
    AND the target must answer over HTTP. The default answer rule is the
    platform's - a non-5xx status, because a server-side error is not a live
    target. `require_http=False` relaxes it to "the transport answered at all"
    for a target whose application has a known, permanent 5xx on the probed
    route (the eval-server prestashop and its emulation ICU defect); the raw
    status stays in the observation and the caller records it, so the
    relaxation is evidence, never silence.
    """
    if not observation.containers:
        return f"no containers for {project_name(observation.target)}"
    if not containers_ready(observation.containers):
        states = ", ".join(
            f"{fact.service}:{fact.state or '?'}/{fact.health or '-'}/exit={fact.exit_code}"
            for fact in observation.containers
        )
        return f"containers not ready ({states})"
    if not observation.url:
        return "targetctl reported no accessible url"
    if not http_ready(observation.http_status) and (
        require_http or not _http_answered(observation.http_status)
    ):
        return f"http {observation.http_status or NO_ANSWER} at {observation.url}"
    return None


def accepted_http_note(observation: Observation) -> str | None:
    """The loud note for a target accepted without the platform's non-5xx rule.

    Only a target whose policy relaxed the rule can be accepted on a 5xx; the
    note carries the raw status, so the run state says why it proceeded.
    """
    code = (observation.http_status or "").strip()
    if not _http_answered(code) or http_ready(code):
        return None
    return (
        f"http {code} at {observation.url} "
        "(accepted: the non-5xx readiness rule is off for this target)"
    )


def _http_answered(status: str) -> bool:
    """True when the probe reached the target and the target answered.

    An empty status and `000` mean no HTTP answer at all; any status the server
    did send is an answer, 5xx included.
    """
    code = (status or "").strip()
    return bool(code) and code != NO_ANSWER


def leftovers(observation: Observation) -> tuple[ContainerFact, ...]:
    """Every container of the project still present after `down`."""
    return tuple(observation.containers)


def url_hello(output: str) -> str:
    """The HTTP status a curl probe answered, or "" when it answered none."""
    matches = _HTTP_STATUS_RE.findall(output or "")
    return matches[-1] if matches else ""


def parse_containers(output: str) -> tuple[ContainerFact, ...]:
    """Container facts from `docker inspect` JSON.

    `State.Health.Status` is present only for containers that declare a
    healthcheck, and a container that never started has no `State.Health` at
    all; both are read defensively so a partial record is still a fact
    (an absent health field means "no healthcheck", not "healthy").
    """
    try:
        decoded = json.loads(output or "")
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(decoded, list):
        return ()
    facts: list[ContainerFact] = []
    for record in decoded:
        if not isinstance(record, dict):
            continue
        state = record.get("State") if isinstance(record.get("State"), dict) else {}
        health = state.get("Health") if isinstance(state.get("Health"), dict) else {}
        config = record.get("Config") if isinstance(record.get("Config"), dict) else {}
        labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
        name = str(record.get("Name") or "").lstrip("/")
        if not name:
            continue
        facts.append(
            ContainerFact(
                name=name,
                service=str(labels.get(COMPOSE_SERVICE_LABEL) or ""),
                state=str(state.get("Status") or "").strip().lower(),
                health=str(health.get("Status") or "").strip().lower(),
                exit_code=_as_int(state.get("ExitCode")),
            )
        )
    return tuple(facts)


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def driver_for(
    driver: str,
    *,
    ssh: str | None = None,
    targetctl: str = "/root/wb",
    local_dir: Path | None = None,
    bash: str | None = None,
    platform: str = "linux/amd64",
    base_url: str | None = None,
    executor: Executor | None = None,
) -> TargetEnv:
    """Build the configured driver; THE factory (the CLI calls this, tests too).

    Fails loudly on an incomplete description: `ssh` without an alias, `local`
    without a checkout, `attach` without a URL. `bash` stays None unless the
    config names one, because macOS's system bash 3.2 collapses the compose
    project names (the class docstring explains).
    """
    executor = executor or LocalExecutor()
    if driver == "ssh":
        if not ssh:
            raise ValueError("the ssh driver needs environment.ssh")
        return SshServerEnv(ssh=ssh, targetctl=targetctl, executor=executor)
    if driver == "local":
        if not local_dir:
            raise ValueError("the local driver needs environment.local_dir")
        return LocalEnv(
            local_dir=Path(local_dir).expanduser(),
            bash=bash or None,
            platform=platform,
            executor=executor,
        )
    if driver == "attach":
        if not base_url:
            raise ValueError("the attach driver needs environment.base_url")
        return AttachEnv(base_url=base_url, executor=executor)
    raise ValueError(f"unknown environment.driver {driver!r} (ssh | local | attach)")
