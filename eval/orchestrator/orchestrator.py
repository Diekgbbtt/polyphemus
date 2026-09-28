"""The orchestrator over one `EvalSetup` (ticket #269, D1/D14/D29).

`plan()` builds every instance and target command without a runner. `up()`
gates the eval-wide work items first, then brings up each instance stack and
its serial target pipeline; `down()` tears targets down in reverse and then the
instance stacks. All effects flow through the injected runner.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from orchestrator import instances
from orchestrator.commands import Command, CommandRunner
from orchestrator.instances import COMPOSE_FILES, InstancePaths
from orchestrator.setup import EvalSetup, Instance, TargetRun
from orchestrator.targets import TargetStrategy, TargetUpResult, build_strategy
from orchestrator.workitems import require_complete


class OrchestratorError(RuntimeError):
    """The orchestrator was asked to execute without a runner."""


@dataclass(frozen=True)
class OrchestratorConfig:
    """Where the eval lives: the canonical repo, instances root, and branch."""

    repo: Path
    instances_root: Path
    branch: str = "eval"
    compose_files: tuple[str, ...] = COMPOSE_FILES


@dataclass(frozen=True)
class PlanStep:
    """A labelled group of commands in a plan (one instance or target)."""

    label: str
    commands: tuple[Command, ...]


@dataclass(frozen=True)
class InstanceResult:
    """The target runs brought up on one instance."""

    instance_id: str
    targets: tuple[TargetUpResult, ...]


class Orchestrator:
    def __init__(
        self,
        setup: EvalSetup,
        config: OrchestratorConfig,
        *,
        runner: CommandRunner | None = None,
        sleep=None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.setup = setup
        self.config = config
        self._runner = runner
        self._sleep = sleep
        self._env = env

    # --- collaborators --------------------------------------------------------

    def _paths(self, instance: Instance) -> InstancePaths:
        return instances.instance_paths(
            instance,
            self.config.instances_root,
            repo=self.config.repo,
            branch=self.config.branch,
            compose_files=self.config.compose_files,
        )

    def _strategy(self, paths: InstancePaths, run: TargetRun) -> TargetStrategy:
        return build_strategy(run, paths, env=self._env, sleep=self._sleep)

    def _require_runner(self) -> CommandRunner:
        if self._runner is None:
            raise OrchestratorError("execution requires a command runner")
        return self._runner

    # --- planning -------------------------------------------------------------

    def plan(self) -> list[PlanStep]:
        """Every instance and target command, in execution order; no runner."""
        steps: list[PlanStep] = []
        for instance in self.setup.instances:
            paths = self._paths(instance)
            steps.append(
                PlanStep(
                    f"instance {instance.instance_id} ({paths.compose_project})",
                    tuple(instances.plan_up(paths)),
                )
            )
            for run in instance.targets:
                strategy = self._strategy(paths, run)
                steps.append(
                    PlanStep(
                        f"target {instance.instance_id}/{run.target_id} "
                        f"({run.target_config.lifecycle})",
                        tuple(strategy.plan_up()),
                    )
                )
        return steps

    # --- execution ------------------------------------------------------------

    def up(self) -> list[InstanceResult]:
        """Gate the work items, then bring up every instance and its targets."""
        require_complete(self.setup.work_items)
        runner = self._require_runner()
        results: list[InstanceResult] = []
        for instance in self.setup.instances:
            paths = self._paths(instance)
            instances.up(paths, runner)
            target_results = tuple(
                self._strategy(paths, run).up(runner) for run in instance.targets
            )
            results.append(InstanceResult(instance.instance_id, target_results))
        return results

    def down(self) -> None:
        """Tear every target down (reverse order), then every instance stack."""
        runner = self._require_runner()
        for instance in reversed(self.setup.instances):
            paths = self._paths(instance)
            for run in reversed(instance.targets):
                self._strategy(paths, run).down(runner)
            instances.down(paths, runner)

    def status(self) -> dict:
        """Per-instance stack status and per-target status."""
        runner = self._require_runner()
        report: dict = {}
        for instance in self.setup.instances:
            paths = self._paths(instance)
            report[instance.instance_id] = {
                "stack": instances.status(paths, runner),
                "targets": {
                    run.target_id: self._strategy(paths, run).status(runner)
                    for run in instance.targets
                },
            }
        return report
