"""Target lifecycle strategies behind one interface (D9, spec #301).

`build_strategy` selects the implementation from the resolved
`TargetConfiguration.runner` and allocates the TargetRun's unique synthetic Host
(D2) from `<instance_id>/<target_id>`. Importing this package performs no I/O.
"""
from __future__ import annotations

from typing import Mapping

from orchestrator import routing
from orchestrator.dataset import BenchmarkDataset
from orchestrator.datasets.base import DatasetHelper
from orchestrator.instances import InstancePaths
from orchestrator.setup import TargetRun
from orchestrator.target_config import TargetConfiguration
from orchestrator.targets import compose as compose_strategy
from orchestrator.targets import image as image_strategy
from orchestrator.targets import targetctl as targetctl_strategy
from orchestrator.targets.base import (
    Sleep,
    TargetContext,
    TargetError,
    TargetNotReadyError,
    TargetStrategy,
    TargetUpResult,
    wait_ready,
)

__all__ = [
    "TargetContext",
    "TargetError",
    "TargetNotReadyError",
    "TargetStrategy",
    "TargetUpResult",
    "build_strategy",
    "compose_strategy",
    "image_strategy",
    "targetctl_strategy",
    "wait_ready",
]


def build_strategy(
    target_config: TargetConfiguration,
    dataset: BenchmarkDataset,
    helper: DatasetHelper,
    paths: InstancePaths,
    run: TargetRun,
    *,
    env: Mapping[str, str] | None = None,
    sleep: Sleep | None = None,
) -> TargetStrategy:
    """Build the strategy for one TargetRun, with its synthetic Host allocated.

    The bring-up configuration (`target_config`), its dataset, and the dataset's
    helper are all resolved by the caller (the orchestrator); here we only select
    the runner implementation and seed the shared context.
    """
    identity = f"{paths.instance.instance_id}/{run.target_id}"
    context = TargetContext(
        paths=paths,
        host=routing.synthetic_host(identity),
        run=run,
        target_config=target_config,
        dataset=dataset,
        helper=helper,
    )
    runner = target_config.runner
    if runner == "targetctl":
        return targetctl_strategy.TargetctlStrategy(context, env=env, sleep=sleep)
    if runner == "image":
        return image_strategy.ImageStrategy(context, sleep=sleep)
    if runner == "compose":
        return compose_strategy.ComposeStrategy(context, sleep=sleep)
    raise TargetError(f"unknown target runner: {runner!r}")
