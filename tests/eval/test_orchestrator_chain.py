"""The multi-target chain - reclaim the previous, pull the next, bring it up.

`next_target` is the single driver: it tears the active target down, reclaims
its app image, pulls the next target's image, starts it, and verifies health.
These predicates sequence a whole chain against fake strategies with no host,
and pin the inspectable trace a failure hands back to the orchestrator.
"""
from __future__ import annotations

import pytest

from orchestrator import chain as chain_mod
from orchestrator.files import FileStore
from orchestrator.instances import InstancePaths
from orchestrator.setup import Instance, TargetConfig, TargetRun
from orchestrator.targets.base import TargetNotReadyError, TargetUpResult


class FakeStrategy:
    """Records the chain's calls; optionally fails on `up`."""

    def __init__(self, target_id: str, *, fail_up: bool = False) -> None:
        self.host = f"t-{target_id}.target"
        self.target_id = target_id
        self.fail_up = fail_up
        self.calls: list[str] = []

    def up(self, run) -> TargetUpResult:
        self.calls.append("up")
        if self.fail_up:
            raise TargetNotReadyError(f"{self.host} not ready")
        return TargetUpResult(self.host, f"http://{self.host}/", "http://10.0.0.1:1", True)

    def down(self, run) -> None:
        self.calls.append("down")

    def status(self, run) -> str:
        self.calls.append("status")
        return "running"

    def provision(self, run) -> tuple[str, ...]:
        self.calls.append("pull")
        return (f"pull {self.target_id}",)

    def reclaim(self, run) -> tuple[str, ...]:
        self.calls.append("reclaim")
        return (f"reclaim {self.target_id}",)


def _instance(target_ids):
    return Instance(
        instance_id="eval-server-1",
        targets=tuple(
            TargetRun(
                target_id=t,
                target_config=TargetConfig(lifecycle="targetctl", params={"target": t}),
                images=(f"pentestbench-{t}:latest",),
            )
            for t in target_ids
        ),
        env_file="eval-server-1/.env",
    )


def _paths(tmp_path, instance):
    return InstancePaths(
        instance=instance,
        worktree=tmp_path / "wt",
        env_file=tmp_path / "wt" / ".env",
        compose_project="ph-test",
        compose_files=(),
        repo=tmp_path,
        branch="eval",
    )


def _build(tmp_path, target_ids, *, fail_up=None):
    instance = _instance(target_ids)
    strategies: dict[str, FakeStrategy] = {}

    def factory(run):
        if run.target_id not in strategies:
            strategies[run.target_id] = FakeStrategy(
                run.target_id, fail_up=(run.target_id == fail_up)
            )
        return strategies[run.target_id]

    chain = chain_mod.Chain(
        instance=instance,
        paths=_paths(tmp_path, instance),
        strategy_for=factory,
        runner=lambda command: None,
        files=FileStore(),
        state_path=tmp_path / "chain-state.yaml",
    )
    return chain, strategies


def test_first_target_pulls_and_ups(tmp_path):
    chain, strategies = _build(tmp_path, ["a", "b"])
    step = chain.next_target("a")
    assert step.target_id == "a"
    assert step.previous is None
    assert step.reclaimed == ()
    assert step.pulled == ("pull a",)
    assert step.images == ("pentestbench-a:latest",)
    assert strategies["a"].calls == ["pull", "up", "status"]
    assert chain.state.active_target == "a"


def test_second_target_reclaims_previous_then_pulls(tmp_path):
    chain, strategies = _build(tmp_path, ["a", "b"])
    chain.next_target("a")
    strategies["a"].calls.clear()
    step = chain.next_target("b")
    assert step.previous == "a"
    assert strategies["a"].calls == ["down", "reclaim"]
    assert step.reclaimed == ("reclaim a",)
    assert strategies["b"].calls == ["pull", "up", "status"]
    assert chain.state.active_target == "b"
    assert chain.state.completed == ("a", "b")


def test_unknown_target_is_a_failure(tmp_path):
    chain, _ = _build(tmp_path, ["a"])
    with pytest.raises(chain_mod.TargetFailure) as excinfo:
        chain.next_target("nope")
    assert "unknown target" in excinfo.value.error


def test_up_failure_carries_trace_and_traceback(tmp_path):
    chain, _ = _build(tmp_path, ["a"], fail_up="a")
    with pytest.raises(chain_mod.TargetFailure) as excinfo:
        chain.next_target("a")
    failure = excinfo.value
    assert failure.step == "up a"
    assert failure.target_id == "a"
    assert failure.trace[-1] == "up a"
    assert "TargetNotReadyError" in failure.cause
    report = failure.report()
    assert report["trace"] and report["traceback"]


def test_state_persists_across_chain_instances(tmp_path):
    chain, _ = _build(tmp_path, ["a", "b"])
    chain.next_target("a")
    chain2, _ = _build(tmp_path, ["a", "b"])
    assert chain2.state.active_target == "a"
    assert chain2.state.completed == ("a",)
