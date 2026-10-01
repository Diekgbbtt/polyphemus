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

from orchestrator import front, instances, routing
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.instances import COMPOSE_FILES, InstanceError, InstancePaths
from orchestrator.setup import EvalSetup, Instance, TargetRun
from orchestrator.targets import TargetError, TargetStrategy, TargetUpResult, build_strategy
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
        registry = self.setup.dataset.registry if self.setup.dataset else ""
        return build_strategy(run, paths, registry=registry, env=self._env, sleep=self._sleep)

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
            run.target_config.lifecycle in ("targetctl", "image", "compose")
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
        if self._needs_front():
            self._ensure_front(runner)
        results: list[InstanceResult] = []
        for instance in self.setup.instances:
            paths = self._paths(instance)
            instances.up(paths, runner)
            target_results = tuple(
                self._strategy(paths, run).up(runner) for run in instance.targets
            )
            results.append(InstanceResult(instance.instance_id, target_results))
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
