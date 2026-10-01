"""The multi-target chain: one instance, many targets, sequentially.

The orchestrator's control plane drives this. Each `next_target` reclaims the
previous target's app image, pulls the next target's image, brings the next
target up, and verifies its health - and on failure returns the full inspectable
trace (the step log plus the raised command error and traceback) so the
orchestrator sees what happened, never a bare boolean.

Every effect flows through the injected runner and strategy factory, so the unit
tier sequences a whole chain against fakes with no host.
"""
from __future__ import annotations

import traceback as _traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import yaml

from orchestrator.commands import CommandRunner
from orchestrator.docker import ImagePrimitiveError
from orchestrator.files import FileStore
from orchestrator.instances import InstancePaths
from orchestrator.setup import Instance, TargetRun
from orchestrator.targets.base import TargetError, TargetStrategy, TargetUpResult


@dataclass(frozen=True)
class ChainState:
    """The chain's durable position: which target is up, which are done."""

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

    `images` are the target's image identifiers as-is (the tool contract exposes
    them to the agent); `pulled` are the qualified references actually pulled.
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

    `trace` is the ordered step log (down, reclaim, pull, up, health); `cause` is
    the Python traceback; `error` is the raised command error, which already
    names the command and its stderr. Together they are the "error stack trace
    and any other programmatically inspectable trace" the orchestrator consumes.
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
    """Sequences one instance through its TargetRuns: reclaim, pull, up, verify."""

    def __init__(
        self,
        *,
        instance: Instance,
        paths: InstancePaths,
        strategy_for: Callable[[TargetRun], TargetStrategy],
        runner: CommandRunner,
        files: FileStore,
        state_path: Path,
    ) -> None:
        self.instance = instance
        self.paths = paths
        self._strategy_for = strategy_for
        self.runner = runner
        self._files = files
        self.state_path = Path(state_path)
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

    # --- steps ----------------------------------------------------------------

    def next_target(self, target_id: str) -> TargetStep:
        """Reclaim the active target, pull and start `target_id`, verify health."""
        self._trace = []
        try:
            run = self._target(target_id)
            previous = self.state.active_target
            reclaimed: tuple[str, ...] = ()
            if previous is not None and previous != target_id:
                reclaimed = self._teardown(previous)
            pulled = self._pull(run)
            strategy = self._strategy(run)
            self._step = f"up {target_id}"
            self._trace.append(self._step)
            up = strategy.up(self.runner)
            health = self._health(strategy)
            completed = tuple(dict.fromkeys((*self.state.completed, target_id)))
            self.state = replace(
                self.state, active_target=target_id, completed=completed
            )
            self._save()
            return TargetStep(
                target_id, previous, reclaimed, pulled, up, health, tuple(run.images)
            )
        except (TargetError, ImagePrimitiveError) as exc:
            raise self._failure(target_id, exc) from exc

    def _teardown(self, target_id: str) -> tuple[str, ...]:
        strategy = self._strategy(self._target(target_id))
        self._step = f"down {target_id}"
        self._trace.append(self._step)
        strategy.down(self.runner)
        self._step = f"reclaim {target_id}"
        self._trace.append(self._step)
        return tuple(strategy.reclaim(self.runner))

    def _pull(self, run: TargetRun) -> tuple[str, ...]:
        self._step = f"pull {run.target_id}"
        self._trace.append(self._step)
        return tuple(self._strategy(run).provision(self.runner))

    def _health(self, strategy: TargetStrategy) -> str:
        self._step = "health"
        self._trace.append("health")
        return strategy.status(self.runner)

    def _failure(self, target_id: str, exc: BaseException) -> TargetFailure:
        return TargetFailure(
            target_id=target_id,
            step=self._step,
            error=str(exc),
            trace=tuple(self._trace),
            cause=_traceback.format_exc(),
        )
