"""The orchestrator over one `EvalSetup` (ticket #269, D1/D14/D29, spec #301).

`plan()` builds every instance and target command without a runner. `up()`
gates the eval-wide work items first, then brings up each instance stack and
its serial target pipeline; `down()` tears targets down in reverse and then the
instance stacks. All effects flow through the injected runner.

Per target, the orchestrator resolves its domain objects from the setup's eval
root (spec #301): the `BenchmarkDataset` keyed by `TargetRun.target_key`, the
target's `TargetConfiguration`, and the dataset helper, then hands that triple to
`build_strategy`. `up` starts each target and then verifies readiness through the
strategy's bounded plan - the target's own `up` never blocks on health.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from orchestrator import front, instances, routing
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.dataset import DATASET_DIRNAME, BenchmarkDataset, load_benchmark_dataset
from orchestrator.datasets import DatasetHelper
from orchestrator.datasets.base import helper_for
from orchestrator.instances import COMPOSE_FILES, InstanceError, InstancePaths
from orchestrator.setup import EvalSetup, Instance, TargetRun
from orchestrator.target_config import TargetConfiguration, load_target_configuration
from orchestrator.targets import TargetError, TargetStrategy, TargetUpResult, build_strategy
from orchestrator.workitems import require_complete

# Every lifecycle is local (D45), so each runner is fronted by the shared :80
# container.
LOCAL_RUNNERS = ("targetctl", "image", "compose")


class OrchestratorError(RuntimeError):
    """The orchestrator was asked to execute without a runner, or a target could
    not be resolved to its dataset/target configuration."""


@dataclass(frozen=True)
class OrchestratorConfig:
    """Where the eval lives: the canonical repo, instances root, and branch.

    `eval_root` is the setup file's `eval/` directory, against which the dataset
    YAMLs (`eval/datasets/<key>.yaml`) and the target YAMLs
    (`eval/targets/<key>/<target>.yaml`) are resolved (spec #301).
    """

    repo: Path
    instances_root: Path
    branch: str = "eval"
    compose_files: tuple[str, ...] = COMPOSE_FILES
    eval_root: Path | None = None


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


@dataclass(frozen=True)
class TeardownError:
    """One target's or instance's teardown failure, for per-target reporting."""

    label: str
    error: str

    def __str__(self) -> str:
        return f"{self.label}: {self.error}"


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
        # Resolved domain objects, cached per dataset/target so a plan does not
        # re-read a YAML for every pass.
        self._datasets: dict[str, BenchmarkDataset] = {}
        self._helpers: dict[str, DatasetHelper] = {}
        self._target_configs: dict[tuple[str, str], TargetConfiguration] = {}

    # --- collaborators --------------------------------------------------------

    def _paths(self, instance: Instance) -> InstancePaths:
        return instances.instance_paths(
            instance,
            self.config.instances_root,
            repo=self.config.repo,
            branch=self.config.branch,
            compose_files=self.config.compose_files,
        )

    def _dataset(self, dataset_id: str) -> BenchmarkDataset:
        if dataset_id in self._datasets:
            return self._datasets[dataset_id]
        root = self.config.eval_root
        if root is None:
            raise OrchestratorError(
                "resolving a target requires OrchestratorConfig.eval_root "
                "(the setup file's eval/ directory)"
            )
        root = Path(root)
        path = root / DATASET_DIRNAME / f"{dataset_id}.yaml"
        dataset = load_benchmark_dataset(path, eval_root=root)
        self._datasets[dataset_id] = dataset
        return dataset

    def _resolve(
        self, run: TargetRun
    ) -> tuple[BenchmarkDataset, DatasetHelper, TargetConfiguration]:
        """Resolve a TargetRun's dataset, helper, and bring-up configuration."""
        dataset = self._dataset(run.dataset_id)
        key = (dataset.id, run.target)
        config = self._target_configs.get(key)
        if config is None:
            config = load_target_configuration(dataset.target_config_search(run.target))
            self._target_configs[key] = config
        helper = self._helpers.get(dataset.id)
        if helper is None:
            helper = helper_for(dataset)
            self._helpers[dataset.id] = helper
        return dataset, helper, config

    def _strategy(self, paths: InstancePaths, run: TargetRun) -> TargetStrategy:
        dataset, helper, config = self._resolve(run)
        return build_strategy(
            config, dataset, helper, paths, run, env=self._env, sleep=self._sleep
        )

    def _require_runner(self) -> CommandRunner:
        if self._runner is None:
            raise OrchestratorError("execution requires a command runner")
        return self._runner

    def _needs_front(self) -> bool:
        """True when any target is local, so the shared :80 front is required.

        Every lifecycle is local (D45): `targetctl` runs on the eval host like
        `image` and `compose`, so all three are fronted by the shared container
        on :80 rather than a per-host nginx reached over ssh.
        """
        return any(
            self._resolve(run)[2].runner in LOCAL_RUNNERS
            for instance in self.setup.instances
            for run in instance.targets
        )

    def _ensure_front(self, runner: CommandRunner) -> None:
        """Create the shared front container before the first local target."""
        command = front.plan_container_up()
        require_ok(runner(command), command, error=OrchestratorError)

    def _remove_front(self, runner: CommandRunner) -> None:
        """Remove the shared front container after the last local target."""
        command = front.plan_container_down()
        require_ok(runner(command), command, error=OrchestratorError)

    # --- planning -------------------------------------------------------------

    def plan(self) -> list[PlanStep]:
        """Every instance and target command, in execution order; no runner."""
        steps: list[PlanStep] = []
        if self._needs_front():
            steps.append(
                PlanStep("front container (local targets)", (front.plan_container_up(),))
            )
        for instance in self.setup.instances:
            paths = self._paths(instance)
            steps.append(
                PlanStep(
                    f"instance {instance.instance_id} ({paths.compose_project})",
                    tuple(instances.plan_up(paths)),
                )
            )
            for run in instance.targets:
                _, _, config = self._resolve(run)
                strategy = self._strategy(paths, run)
                steps.append(
                    PlanStep(
                        f"target {instance.instance_id}/{run.target_id} "
                        f"({config.runner})",
                        tuple(strategy.plan_up()),
                    )
                )
        return steps

    # --- execution ------------------------------------------------------------

    def up(self, *, target_id: str | None = None) -> list[InstanceResult]:
        """Gate the work items, then bring up every instance and its targets.

        Each target is started, then its readiness is verified under the
        strategy's bounded plan; the target's own `up` never blocks on health.

        `target_id` scopes the target bring-up to ONE target while still
        bringing up every instance stack. A single trial passes its own target,
        so a multi-target setup never starts the whole serial pipeline at once
        (the chain's `next-target` already brought the target up; this keeps a
        bare `trial` self-contained without the blow-up). `None` brings up every
        target, the whole-setup `up` verb's behaviour.
        """
        require_complete(self.setup.work_items)
        runner = self._require_runner()
        if self._needs_front():
            self._ensure_front(runner)
        results: list[InstanceResult] = []
        for instance in self.setup.instances:
            paths = self._paths(instance)
            instances.up(paths, runner)
            target_results: list[TargetUpResult] = []
            for run in instance.targets:
                if target_id is not None and run.target_id != target_id:
                    continue
                strategy = self._strategy(paths, run)
                target_results.append(strategy.up(runner))
                strategy.await_ready(runner)
            results.append(InstanceResult(instance.instance_id, tuple(target_results)))
        return results

    def down(self) -> list[TeardownError]:
        """Tear every target down (reverse order), then every instance stack.

        Non-aborting for one target's failure (SP3): each failure is recorded and
        the teardown continues, so one stuck target cannot strand the rest. The
        returned errors are reported by the CLI; the last local target's down
        also removes the shared front container.
        """
        runner = self._require_runner()
        errors: list[TeardownError] = []
        for instance in reversed(self.setup.instances):
            paths = self._paths(instance)
            for run in reversed(instance.targets):
                label = f"{instance.instance_id}/{run.target_id}"
                try:
                    self._strategy(paths, run).down(runner)
                except TargetError as exc:
                    errors.append(TeardownError(label, str(exc)))
            try:
                instances.down(paths, runner)
            except InstanceError as exc:
                errors.append(TeardownError(instance.instance_id, str(exc)))
        if self._needs_front():
            try:
                self._remove_front(runner)
            except OrchestratorError as exc:
                errors.append(TeardownError(front.FRONT_CONTAINER, str(exc)))
        return errors

    def remove_worktrees(self) -> list[TeardownError]:
        """Operator-only: drop every instance worktree (and its data root).

        NEVER part of the stack lifecycle - `down` keeps the worktrees so the
        instance data root survives stop/drain and eval termination. This is the
        explicit, out-of-loop action the operator invokes when an instance is
        meant to be re-provisioned from scratch.
        """
        runner = self._require_runner()
        errors: list[TeardownError] = []
        for instance in self.setup.instances:
            paths = self._paths(instance)
            try:
                instances.remove_worktree(paths, runner)
            except InstanceError as exc:
                errors.append(TeardownError(instance.instance_id, str(exc)))
        return errors

    def status(self) -> dict:
        """Per-instance stack status, live kali aliases, and per-target status.

        The aliases are read from each instance's kali `/etc/hosts` through the
        runner, so the report shows what is actually present, not what was
        planned. An unreadable kali is reported truthfully (an error entry),
        never silently omitted.
        """
        runner = self._require_runner()
        report: dict = {}
        for instance in self.setup.instances:
            paths = self._paths(instance)
            report[instance.instance_id] = {
                "stack": instances.status(paths, runner),
                "aliases": self._kali_aliases(paths, runner),
                "targets": {
                    run.target_id: self._target_status(paths, run, runner)
                    for run in instance.targets
                },
            }
        return report

    def _target_status(
        self, paths: InstancePaths, run: TargetRun, runner: CommandRunner
    ) -> dict:
        strategy = self._strategy(paths, run)
        return {
            "status": strategy.status(runner),
            "host": strategy.host,
            "front_url": strategy.front_url,
        }

    def _kali_aliases(self, paths: InstancePaths, runner: CommandRunner) -> dict:
        command = routing.kali_hosts_command(paths)
        result = runner(command)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return {"error": detail or f"kali /etc/hosts unreadable (exit {result.returncode})"}
        return routing.parse_synthetic_aliases(result.stdout)
