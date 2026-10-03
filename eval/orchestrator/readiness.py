"""Bounded, non-blocking readiness for a target (spec #301, the D/F fix).

Readiness is the platform's own concern, not `docker compose up`'s. The target's
`up` never blocks on health; this module then verifies readiness under a bounded
window, so a slow or broken healthcheck can never hang the chain.

Two kinds of checker:

* **compose** (the default): read the compose project's OWN health, exhaustively,
  with `docker compose ps -a --format json`. `-a` lists every service, including
  one-shot init services that have exited and services not yet started, so the
  check mirrors the benchmark's own `depends_on` conditions exactly:
  a service is ready when it is `healthy`, or `running` with no healthcheck, or
  `exited` with code 0. Anything else - `created`, `starting`, `unhealthy`,
  `restarting`, a non-zero exit - is not ready. The stack's functional
  dependencies are therefore asserted as the platform declares them, and a
  not-yet-started dependent can never be mistaken for a ready one.
* **http**: probe the target's published port directly, for a target whose
  readiness is an HTTP answer rather than a container healthcheck. A 5xx answer
  (including 500) or no answer is NOT ready.

A dataset helper may name a specific checker for a target; the default is compose.
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
class ReadinessPlan:
    """How a target's readiness is verified: a probe and a bounded window."""

    probe: Command
    retries: int = 60
    interval_s: float = 5.0
    kind: str = "compose"  # compose | http


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
    """Verify `plan` under a bounded window; the caller treats False as fatal."""
    if plan.kind == "compose":
        for _attempt in range(plan.retries):
            result = run(plan.probe)
            if compose_healthy(parse_compose_health(result.stdout or "")):
                return True
            sleep(plan.interval_s)
        return False
    return wait_probe(
        run,
        plan.probe,
        retries=plan.retries,
        interval_s=plan.interval_s,
        sleep=sleep,
    )
