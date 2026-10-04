"""The multi-target chain: one instance, many targets, sequentially.

The orchestrator's control plane drives this. Each `next_target` tears the
previous target down (reclaiming its canonical images only when the target opted
in, `reclaimable`), provisions the next target's images by store -> pull ->
build, brings the next target up, verifies its health under the helper's bounded
plan, and records a `bind_artifacts` placeholder - and on failure returns the
full inspectable trace (the step log plus the raised command error and
traceback) so the orchestrator sees what happened, never a bare boolean.

`up` never blocks on health: readiness is the chain's own bounded `health` stage.
A reclaimable target's tags are also reclaimed after a failed `up`, so a half-up
target never leaks its images.

Every effect flows through the injected runner and strategy factory, so the unit
tier sequences a whole chain against fakes with no host.
"""
from __future__ import annotations

import traceback as _traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import yaml

from orchestrator import front
from orchestrator.commands import CommandRunner, require_ok
from orchestrator.docker import PULL, ImagePrimitiveError
from orchestrator.files import FileStore
from orchestrator.instances import InstancePaths
from orchestrator.setup import Instance, TargetRun
from orchestrator.targets.base import TargetError, TargetStrategy, TargetUpResult


@dataclass(frozen=True)
class ChainState:
    """The chain's durable position: which target is up, which are done.

    `active_target` is the target the chain has most recently advanced to, kept
    so a resume knows which target to tear down first. Once every declared
    target is `completed` the chain is terminal: nothing is left to advance to,
    so `active_target` is cleared to `None` (F10). A partial chain keeps its
    position so a resume tears the active target down and continues.
    """

    instance_id: str
    active_target: str | None = None
    completed: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "active_target": self.active_target,
            "completed": list(self.completed),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ChainState":
        return cls(
            instance_id=str(payload.get("instance_id", "")),
            active_target=payload.get("active_target"),
            completed=tuple(payload.get("completed") or ()),
        )


@dataclass(frozen=True)
class TargetStep:
    """One successful `next_target`: what was reclaimed, pulled, brought up.

    `images` are the target's canonical tags (`ph/<dataset>/<target>:<service>`),
    the one symbolic key the store check and reclaim speak; `pulled` are the
    qualified references actually pulled during provisioning.
    """

    target_id: str
    previous: str | None
    reclaimed: tuple[str, ...]
    pulled: tuple[str, ...]
    up: TargetUpResult
    health: str
    images: tuple[str, ...] = ()


class TargetFailure(RuntimeError):
    """A chain step failed; carries the inspectable trace the orchestrator needs.

    `trace` is the ordered step log (down, reclaim, provision, up, health,
    bind_artifacts); `cause` is the Python traceback; `error` is the raised
    command error, which already names the command and its stderr. Together they
    are the "error stack trace and any other programmatically inspectable trace"
    the orchestrator consumes.
    """

    def __init__(
        self,
        target_id: str,
        step: str,
        error: str,
        trace: tuple[str, ...],
        cause: str,
    ) -> None:
        super().__init__(f"target {target_id!r} failed at {step}: {error}")
        self.target_id = target_id
        self.step = step
        self.error = error
        self.trace = trace
        self.cause = cause

    def report(self) -> dict:
        return {
            "target_id": self.target_id,
            "step": self.step,
            "error": self.error,
            "trace": list(self.trace),
            "traceback": self.cause,
        }


class Chain:
    """Sequences one instance through its TargetRuns: reclaim, provision, up, verify."""

    def __init__(
        self,
        *,
        instance: Instance,
        paths: InstancePaths,
        strategy_for: Callable[[TargetRun], TargetStrategy],
        runner: CommandRunner,
        files: FileStore,
        state_path: Path,
        bind_artifacts: Callable[[TargetRun], None] | None = None,
    ) -> None:
        self.instance = instance
        self.paths = paths
        self._strategy_for = strategy_for
        self.runner = runner
        self._files = files
        self.state_path = Path(state_path)
        self._bind_artifacts_seam = bind_artifacts
        self.state = self._load()
        self._trace: list[str] = []
        self._step = "start"

    # --- persistence ----------------------------------------------------------

    def _load(self) -> ChainState:
        if not self._files.exists(self.state_path):
            return ChainState(instance_id=self.instance.instance_id)
        payload = yaml.safe_load(self._files.read_text(self.state_path)) or {}
        return ChainState.from_dict(payload)

    def _save(self) -> None:
        self._files.write_text_atomic(
            self.state_path, yaml.safe_dump(self.state.to_dict(), sort_keys=False)
        )

    # --- lookups --------------------------------------------------------------

    def _target(self, target_id: str) -> TargetRun:
        for run in self.instance.targets:
            if run.target_id == target_id:
                return run
        raise TargetError(f"unknown target {target_id!r} on instance {self.instance.instance_id!r}")

    def _strategy(self, run: TargetRun) -> TargetStrategy:
        return self._strategy_for(run)

    def _terminal(self, completed: tuple[str, ...]) -> bool:
        """True once every declared target is complete: the chain has ended."""
        declared = {run.target_id for run in self.instance.targets}
        return declared <= set(completed)

    # --- steps ----------------------------------------------------------------

    def next_target(self, target_id: str) -> TargetStep:
        """Reclaim the active target, provision and start `target_id`, verify health."""
        self._trace = []
        strategy: TargetStrategy | None = None
        try:
            run = self._target(target_id)
            previous = self.state.active_target
            reclaimed: tuple[str, ...] = ()
            if previous is not None and previous != target_id:
                reclaimed = self._teardown(previous)
            strategy = self._strategy(run)
            self._front()
            pulled = self._provision(run, strategy)
            self._step = f"up {target_id}"
            self._trace.append(self._step)
            up = strategy.up(self.runner)
            health = self._health(strategy)
            self._bind_artifacts(run)
            completed = tuple(dict.fromkeys((*self.state.completed, target_id)))
            # A chain with every declared target done is terminal: it has no
            # further target to advance to, so clear the active target rather
            # than leave a stale one that a re-run would tear down (F10).
            active_target = None if self._terminal(completed) else target_id
            self.state = replace(
                self.state, active_target=active_target, completed=completed
            )
            self._save()
            return TargetStep(
                target_id, previous, reclaimed, pulled, up, health,
                tuple(strategy.canonical_tags),
            )
        except (TargetError, ImagePrimitiveError) as exc:
            # No leak: a reclaimable target that half-came-up has its tags
            # reclaimed before the failure is reported. Best-effort.
            if strategy is not None and strategy.reclaimable:
                try:
                    strategy.reclaim(self.runner)
                except Exception:
                    pass
            raise self._failure(target_id, exc) from exc

    def _teardown(self, target_id: str) -> tuple[str, ...]:
        strategy = self._strategy(self._target(target_id))
        self._step = f"down {target_id}"
        self._trace.append(self._step)
        strategy.down(self.runner)
        self._step = f"reclaim {target_id}"
        self._trace.append(self._step)
        # Only a reclaimable target hands its canonical tags back; a target that
        # did not opt in leaves its images in the store for the next run.
        if not strategy.reclaimable:
            return ()
        return tuple(strategy.reclaim(self.runner))

    def _provision(self, run: TargetRun, strategy: TargetStrategy) -> tuple[str, ...]:
        self._step = f"provision {run.target_id}"
        self._trace.append(self._step)
        outcomes = strategy.provision(self.runner)
        return tuple(outcome.reference for outcome in outcomes if outcome.source == PULL)

    def _front(self) -> None:
        """Ensure the shared front container before a local target starts (D45).

        The chain is the control plane (D42), so `next_target` must be
        self-contained: every lifecycle is now local and fronted by
        `ph-eval-front`, so the container is created (idempotently) here rather
        than relying on the orchestrator's separate `up` path.
        """
        self._step = "front"
        self._trace.append("front")
        command = front.plan_container_up()
        require_ok(self.runner(command), command, error=TargetError)

    def _health(self, strategy: TargetStrategy) -> str:
        self._step = "health"
        self._trace.append("health")
        return strategy.await_ready(self.runner)

    def _bind_artifacts(self, run: TargetRun) -> None:
        """Placeholder stage: delegate artifact seeding to the injected seam.

        The artifact seeding itself is not implemented here; the chain only
        records the step and hands the run to the seam when one is wired, so the
        policy can be filled in without changing the chain's shape.
        """
        self._step = "bind_artifacts"
        self._trace.append(self._step)
        if self._bind_artifacts_seam is not None:
            self._bind_artifacts_seam(run)

    def _failure(self, target_id: str, exc: BaseException) -> TargetFailure:
        return TargetFailure(
            target_id=target_id,
            step=self._step,
            error=str(exc),
            trace=tuple(self._trace),
            cause=_traceback.format_exc(),
        )
