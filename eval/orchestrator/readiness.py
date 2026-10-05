"""Bounded, non-blocking readiness for a target (spec #301, the D/F fix).

Readiness is the platform's own concern, not `docker compose up`'s. The target's
`up` never blocks on health; this module then verifies readiness under a bounded
window, so a slow or broken healthcheck can never hang the chain.

A plan holds one or more probes, and every probe must answer ready. There are two
probe kinds:

* **compose**: read the compose project's OWN health, exhaustively, with
  `docker compose ps -a --format json`. `-a` lists every service, including
  one-shot init services that have exited and services not yet started, so the
  check mirrors the benchmark's own `depends_on` conditions exactly:
  a service is ready when it is `healthy`, or `running` with no healthcheck, or
  `exited` with code 0. Anything else - `created`, `starting`, `unhealthy`,
  `restarting`, a non-zero exit - is not ready. The stack's functional
  dependencies are therefore asserted as the platform declares them, and a
  not-yet-started dependent can never be mistaken for a ready one.
* **http**: probe an HTTP endpoint and read its status. A 5xx answer (including
  500) or no answer is NOT ready. Two builders produce it: `plan_http_port`
  probes a published port on the host loopback, and `plan_front_http` probes the
  target front carrying the synthetic Host. The front is the exact bare-domain
  path recon uses, and it answers `502` while the published port is still binding
  (the #325 boot window). Because the compose poll reads a `running` container
  with no healthcheck as ready, an HTTP probe alone would drop the support-
  service assertion and a compose poll alone would read a booting app as ready;
  a **composite** plan pairs both, so neither footgun survives.

A dataset helper resolves the plan for a target; the default is the compose poll
when the application declares a healthcheck, and the composite front + compose
plan otherwise.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from orchestrator.commands import Command, CommandRunner

# HTTP answers that do NOT signal readiness: no answer, a connection that never
# completed, or a server-side error. A 5xx (500 included) means the app is up but
# broken, so it is never a valid readiness signal.
READY_UNREACHABLE = frozenset({"", "000", "500", "502", "503", "504"})
# A service is considered ready when healthy, running with no healthcheck, or a
# one-shot init that exited cleanly.
READY_STATES = frozenset({"running"})
READY_HEALTH = frozenset({"healthy"})

Sleep = Callable[[float], None]


@dataclass(frozen=True)
class ServiceHealth:
    """One compose service's live state, as `docker compose ps -a` reports it."""

    service: str
    state: str
    health: str
    exit_code: int

    @property
    def ready(self) -> bool:
        """Healthy, or running with no healthcheck, or a clean one-shot exit."""
        if self.health:
            return self.health in READY_HEALTH
        if self.state in READY_STATES:
            return True
        if self.state == "exited":
            return self.exit_code == 0
        return False


@dataclass(frozen=True)
class ReadinessProbe:
    """One readiness assertion: a command and how to read its answer."""

    command: Command
    kind: str  # compose | http

    def ready(self, output: str) -> bool:
        """True when the probe's output is a valid readiness signal."""
        if self.kind == "compose":
            return compose_healthy(parse_compose_health(output))
        return http_ready(output)


@dataclass(frozen=True)
class ReadinessPlan:
    """How a target's readiness is verified: every probe and a bounded window."""

    probes: tuple[ReadinessProbe, ...]
    retries: int = 60
    interval_s: float = 5.0

    def __post_init__(self) -> None:
        if not self.probes:
            raise ValueError("a readiness plan needs at least one probe")

    @property
    def kind(self) -> str:
        """The plan's single probe kind, or `composite` when it pairs probes."""
        if len(self.probes) == 1:
            return self.probes[0].kind
        return "composite"

    @property
    def commands(self) -> tuple[Command, ...]:
        """Every probe command, in plan order; for a dry-run command list."""
        return tuple(probe.command for probe in self.probes)


def http_probe(command: Command) -> ReadinessProbe:
    """Wrap an HTTP command as `http`-kind readiness."""
    return ReadinessProbe(command=command, kind="http")


def compose_probe(compose_file: str, project: str, *, cwd: str | None = None) -> ReadinessProbe:
    """Wrap the compose-health poll as `compose`-kind readiness."""
    return ReadinessProbe(
        command=plan_compose_health(compose_file, project, cwd=cwd), kind="compose"
    )


def http_ready(code: str) -> bool:
    """True when an HTTP status is a valid readiness signal.

    Empty, `000` (no connection), and every 5xx (500 included) are NOT ready:
    a server-side error is not a live target.
    """
    code = (code or "").strip()
    if code in READY_UNREACHABLE:
        return False
    return not (code.isdigit() and code.startswith("5"))


def wait_probe(
    run: CommandRunner,
    probe: Command,
    *,
    retries: int,
    interval_s: float,
    sleep: Sleep = time.sleep,
) -> bool:
    """Poll `probe` until it answers with a ready HTTP code, up to `retries` times."""
    for _attempt in range(retries):
        result = run(probe)
        if http_ready(result.stdout or ""):
            return True
        sleep(interval_s)
    return False


def plan_http_port(port: int | str, ready_path: str = "/") -> Command:
    """Probe a published port on the host loopback for an HTTP status."""
    return Command(
        argv=(
            "curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
            "--max-time", "10", f"http://127.0.0.1:{port}{_norm_path(ready_path)}",
        ),
        description=f"probe port {port}",
    )


def plan_front_http(host: str, ready_path: str = "/") -> Command:
    """Probe the target front on the host loopback, carrying the synthetic Host.

    The front (`ph-eval-front`, host `:80`) is the exact path recon uses: it
    proxies the bare domain to the target's published port and answers `502`
    while that port is not yet serving. The synthetic Host resolves only inside
    the instance kali, so the eval host reaches the front on the loopback and
    names the Host explicitly. A 5xx (the boot window) is not ready.
    """
    return Command(
        argv=(
            "curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
            "--max-time", "10", "-H", f"Host: {host}",
            f"http://127.0.0.1{_norm_path(ready_path)}",
        ),
        description=f"probe front {host}",
    )


def _norm_path(ready_path: str) -> str:
    return "/" + (ready_path or "").lstrip("/")


def plan_compose_health(
    compose_file: str, project: str, *, cwd: str | None = None
) -> Command:
    """`docker compose ps -a --format json`: every service's live state.

    `-a` is essential: without it compose reports only running containers, so a
    service that has not started yet is invisible and a single running service
    would read as a ready stack.
    """
    return Command(
        argv=(
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            compose_file,
            "ps",
            "-a",
            "--format",
            "json",
        ),
        cwd=cwd,
        description=f"compose health {project}",
    )


def _decode_records(text: str) -> list[dict]:
    """Compose emits either a JSON array (v2.21+) or one JSON object per line."""
    records: list[dict] = []
    try:
        decoded = json.loads(text)
        if isinstance(decoded, list):
            return [item for item in decoded if isinstance(item, dict)]
        if isinstance(decoded, dict):
            return [decoded]
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def parse_compose_health(output: str) -> tuple[ServiceHealth, ...]:
    """The per-service readiness states from `docker compose ps -a --format json`."""
    text = (output or "").strip()
    if not text:
        return ()
    services: list[ServiceHealth] = []
    for record in _decode_records(text):
        service = str(record.get("Service") or "").strip()
        state = str(record.get("State") or record.get("Status") or "").strip().lower()
        health = str(record.get("Health") or "").strip().lower()
        services.append(ServiceHealth(service, state, health, _as_int(record.get("ExitCode"))))
    return tuple(services)


def compose_healthy(services: tuple[ServiceHealth, ...]) -> bool:
    """True when every service is ready (and there is at least one service)."""
    return bool(services) and all(service.ready for service in services)


def wait_readiness(
    run: CommandRunner, plan: ReadinessPlan, *, sleep: Sleep = time.sleep
) -> bool:
    """Verify every probe in `plan` under one bounded window.

    Each attempt runs the probes in order and stops at the first that is not
    ready, so a composite plan's support-service poll is only reached once the
    primary (front) answer is live. The caller treats False as fatal.
    """
    for _attempt in range(plan.retries):
        if all(_probe_ready(run, probe) for probe in plan.probes):
            return True
        sleep(plan.interval_s)
    return False


def _probe_ready(run: CommandRunner, probe: ReadinessProbe) -> bool:
    result = run(probe.command)
    return probe.ready(result.stdout or "")
