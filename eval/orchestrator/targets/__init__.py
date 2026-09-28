"""Target lifecycle strategies behind one interface (D9).

`build_strategy` selects the implementation from the `TargetConfig.lifecycle`
and allocates the TargetRun's unique synthetic Host (D2). Importing this
package performs no I/O.
"""
from __future__ import annotations

from typing import Mapping

from orchestrator import routing
from orchestrator.instances import InstancePaths
from orchestrator.setup import TargetRun
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
    run: TargetRun,
    paths: InstancePaths,
    *,
    env: Mapping[str, str] | None = None,
    sleep: Sleep | None = None,
) -> TargetStrategy:
    """Build the strategy for one TargetRun, with its synthetic Host allocated."""
    identity = f"{paths.instance.instance_id}/{run.target_id}"
    context = TargetContext(paths=paths, host=routing.synthetic_host(identity), run=run)
    lifecycle = run.target_config.lifecycle
    if lifecycle == "targetctl":
        return targetctl_strategy.TargetctlStrategy(context, env=env, sleep=sleep)
    if lifecycle == "image":
        return image_strategy.ImageStrategy(context, sleep=sleep)
    if lifecycle == "compose":
        return compose_strategy.ComposeStrategy(context, sleep=sleep)
    raise TargetError(f"unknown target lifecycle: {lifecycle!r}")