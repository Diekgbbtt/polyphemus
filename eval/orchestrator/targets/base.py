"""The one target-lifecycle interface and its shared readiness probe (D9).

`targetctl`, `image`, and `compose` all present `plan_up`/`up`/`plan_down`/
`down`/`plan_status`/`status`. `up` returns the front URL and the backend URL;
`down` removes everything it created; a readiness failure is fatal - an
unreachable target is never a silent success.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from orchestrator.commands import Command, CommandRunner
from orchestrator.instances import InstancePaths
from orchestrator.setup import TargetRun

# The nginx front still answering "backend not ready" while the app boots.
READY_UNREACHABLE = frozenset({"", "000", "502", "503", "504"})


class TargetError(RuntimeError):
    """A target lifecycle command failed."""


class TargetNotReadyError(TargetError):
    """The target never answered within the readiness window."""


@dataclass(frozen=True)
class TargetUpResult:
    """What a target `up` hands back to the orchestrator and the trial record."""

    host: str
    front_url: str
    backend: str
    ready: bool = True


@dataclass(frozen=True)
class TargetContext:
    """The instance and TargetRun a strategy acts on, plus the synthetic Host.

    `registry` is the dataset's image registry (host plus URL path prefix); a
    strategy joins it with a target image identifier for a pull.
    """

    paths: InstancePaths
    host: str
    run: TargetRun
    registry: str = ""


class TargetStrategy(Protocol):
    host: str

    def plan_up(self) -> list[Command]: ...
    def up(self, run: CommandRunner) -> TargetUpResult: ...
    def plan_down(self) -> list[Command]: ...
    def down(self, run: CommandRunner) -> None: ...
    def plan_status(self) -> list[Command]: ...
    def status(self, run: CommandRunner) -> str: ...
    # The chain's image lifecycle seam: pull the target's image before it starts
    # (verified present), and reclaim the previous target's image after it stops
    # so peak disk is one target. Both return the image references they acted on
    # (the chain record).
    def provision(self, run: CommandRunner) -> tuple[str, ...]: ...
    def reclaim(self, run: CommandRunner) -> tuple[str, ...]: ...


Sleep = Callable[[float], None]


def wait_ready(
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
