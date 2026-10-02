"""Bounded, non-blocking readiness for a target (spec #301, the D/F fix).

Readiness is the platform's own concern, not `docker compose up`'s. The target's
`up` never blocks on health; this module then verifies readiness under a bounded
window, so a slow or broken healthcheck can never hang the chain.

Two kinds of checker:

* **compose** (the default): read the target's compose health non-blockingly with
  `docker compose ps --format json` and require every service to be healthy or
  simply running (a service with no healthcheck). This reuses the benchmark's own
  healthchecks where they exist.
* **http**: probe the target's published port directly, for a target whose
  readiness is an HTTP answer rather than a container healthcheck.

A dataset helper may name a specific checker for a target; the default is compose.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from orchestrator.commands import Command, CommandRunner

# The front still answering "backend not ready" while the app boots.
READY_UNREACHABLE = frozenset({"", "000", "502", "503", "504"})
# A service is considered ready when healthy, or running with no healthcheck.
READY_STATES = frozenset({"healthy", "running"})

Sleep = Callable[[float], None]


@dataclass(frozen=True)
class ReadinessPlan:
    """How a target's readiness is verified: a probe and a bounded window."""

    probe: Command
    retries: int = 60
    interval_s: float = 5.0
    kind: str = "compose"  # compose | http


def wait_probe(
    run: CommandRunner,
    probe: Command,
    *,
    retries: int,
    interval_s: float,
    sleep: Sleep = time.sleep,
) -> bool:
    """Poll `probe` until it answers with a non-front code, up to `retries` times."""
    for _attempt in range(retries):
        result = run(probe)
        if (result.stdout or "").strip() not in READY_UNREACHABLE:
            return True
        sleep(interval_s)
    return False


def plan_compose_health(
    compose_file: str, project: str, *, cwd: str | None = None
) -> Command:
    """`docker compose ps --format json`: the target services' live state."""
    return Command(
        argv=(
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            compose_file,
            "ps",
            "--format",
            "json",
        ),
        cwd=cwd,
        description=f"compose health {project}",
    )


def parse_compose_health(output: str) -> tuple[str, ...]:
    """The per-service readiness states from `docker compose ps --format json`.

    Compose emits either a JSON array (v2.21+) or one JSON object per line; both
    are accepted. A service's `Health` wins over its `State`, so a running but
    unhealthy service reads `unhealthy`.
    """
    text = (output or "").strip()
    if not text:
        return ()
    records: list[dict] = []
    try:
        decoded = json.loads(text)
        if isinstance(decoded, list):
            records = [item for item in decoded if isinstance(item, dict)]
        elif isinstance(decoded, dict):
            records = [decoded]
    except json.JSONDecodeError:
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
    states: list[str] = []
    for record in records:
        health = str(record.get("Health") or "").strip().lower()
        state = str(record.get("State") or record.get("Status") or "").strip().lower()
        states.append(health or state)
    return tuple(states)


def compose_healthy(states: tuple[str, ...]) -> bool:
    """True when every service is ready (healthy, or running with no healthcheck)."""
    return bool(states) and all(state in READY_STATES for state in states)


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
