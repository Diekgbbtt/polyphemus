"""The one target-lifecycle interface and its shared readiness seam (D9, spec #301).

`targetctl`, `image`, and `compose` all present `plan_up`/`up`/`plan_down`/
`down`/`plan_status`/`status`, plus the image lifecycle (`provision`/`reclaim`)
and the bounded readiness check (`await_ready`). `up` returns the front URL and
the backend URL and NEVER blocks on health - readiness is verified separately by
`await_ready` through the dataset helper's bounded plan, so a slow or broken
healthcheck can never hang the chain. `down` removes everything it created; a
readiness failure is fatal - an unreachable target is never a silent success.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from orchestrator.commands import Command, CommandRunner
from orchestrator.dataset import BenchmarkDataset
from orchestrator.datasets.base import DatasetHelper
from orchestrator.docker import ProvisionOutcome
from orchestrator.instances import InstancePaths
from orchestrator.readiness import READY_UNREACHABLE, ReadinessPlan, wait_readiness
from orchestrator.setup import TargetRun
from orchestrator.target_config import TargetConfiguration

__all__ = [
    "READY_UNREACHABLE",
    "Sleep",
    "TargetContext",
    "TargetError",
    "TargetNotReadyError",
    "TargetStrategy",
    "TargetUpResult",
    "wait_ready",
]


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
    """Everything a strategy acts on: the instance paths, the synthetic Host, the
    TargetRun, and the resolved dataset/target-config/helper triple (spec #301).

    `target_config` is the bring-up configuration (`TargetConfiguration`);
    `dataset` and `helper` are its BenchmarkDataset and per-dataset helper.
    """

    paths: InstancePaths
    host: str
    run: TargetRun
    target_config: TargetConfiguration
    dataset: BenchmarkDataset
    helper: DatasetHelper


class TargetStrategy(Protocol):
    host: str
    # The canonical image tags this target owns, and whether teardown may reclaim
    # them (spec #301, `TargetConfiguration.reclaimable`).
    canonical_tags: tuple[str, ...]
    reclaimable: bool

    def plan_up(self) -> list[Command]: ...
    def up(self, run: CommandRunner) -> TargetUpResult: ...
    def plan_down(self) -> list[Command]: ...
    def down(self, run: CommandRunner) -> None: ...
    def plan_status(self) -> list[Command]: ...
    def status(self, run: CommandRunner) -> str: ...
    # Bounded, non-blocking readiness: run the helper's plan under its window and
    # raise TargetNotReadyError when it never answers.
    def await_ready(self, run: CommandRunner) -> str: ...
    # The chain's image lifecycle seam: bind the target's canonical tags by
    # store -> pull -> build before it starts, and reclaim them after it stops
    # (only when reclaimable). `reclaim` returns the removal labels.
    def provision(self, run: CommandRunner) -> tuple[ProvisionOutcome, ...]: ...
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
    """Poll an HTTP probe under a bounded window (delegates to `readiness`)."""
    plan = ReadinessPlan(probe=probe, retries=retries, interval_s=interval_s, kind="http")
    return wait_readiness(run, plan, sleep=sleep)
