"""The multi-target chain - reclaim the previous, provision the next, bring it up.

`next_target` is the single driver: it tears the active target down (reclaiming
its canonical images only when the target is `reclaimable`), provisions the next
target's images by store -> pull -> build, starts it, verifies its health under
the bounded plan, and records a `bind_artifacts` placeholder. A reclaimable
target's tags are also reclaimed after a failed `up`, so nothing leaks. These
predicates sequence a whole chain against fake strategies with no host, and pin
the inspectable trace a failure hands back to the orchestrator.
"""
from __future__ import annotations

import pytest
import yaml

from orchestrator import chain as chain_mod
from orchestrator.commands import CommandResult
from orchestrator.docker import PULL, ProvisionOutcome
from orchestrator.files import FileStore
from orchestrator.instances import InstancePaths
from orchestrator.setup import Instance, TargetConfig, TargetRun
from orchestrator.targets.base import TargetError, TargetNotReadyError, TargetUpResult


class FakeStrategy:
    """Records the chain's calls; optionally fails on `up`."""

    def __init__(
        self, target_id: str, *, reclaimable: bool = True, fail_up: bool = False
    ) -> None:
        self.host = f"t-{target_id}.target"
        self.target_id = target_id
        self.reclaimable = reclaimable
        self.canonical_tags = (f"ph/mock/{target_id}:svc",)
        self.fail_up = fail_up
        self.calls: list[str] = []

    def up(self, run) -> TargetUpResult:
        self.calls.append("up")
        if self.fail_up:
            raise TargetNotReadyError(f"{self.host} not ready")
        return TargetUpResult(self.host, f"http://{self.host}/", "http://10.0.0.1:1", True)

    def down(self, run) -> None:
        self.calls.append("down")

    def await_ready(self, run) -> str:
        self.calls.append("await_ready")
        return "running"

    def provision(self, run) -> tuple[ProvisionOutcome, ...]:
        self.calls.append("provision")
        return (
            ProvisionOutcome(
                self.canonical_tags[0], PULL, f"reg/{self.target_id}", "pull"
            ),
        )

    def reclaim(self, run) -> tuple[str, ...]:
        self.calls.append("reclaim")
        return (f"reclaim {self.target_id}",)


def _instance(target_ids):
    return Instance(
        instance_id="eval-server-1",
        targets=tuple(
            TargetRun(
                target_key=f"mock/{t}",
                target_id=t,
                target_config=TargetConfig(),
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


def _build(tmp_path, target_ids, *, reclaimable="a", fail_up=None, bind_artifacts=None):
    instance = _instance(target_ids)
    strategies: dict[str, FakeStrategy] = {}

    def factory(run):
        if run.target_id not in strategies:
            strategies[run.target_id] = FakeStrategy(
                run.target_id,
                reclaimable=(run.target_id == reclaimable),
                fail_up=(run.target_id == fail_up),
            )
        return strategies[run.target_id]

    chain = chain_mod.Chain(
        instance=instance,
        paths=_paths(tmp_path, instance),
        strategy_for=factory,
        runner=lambda command: CommandResult(0),
        files=FileStore(),
        state_path=tmp_path / "chain-state.yaml",
        bind_artifacts=bind_artifacts,
    )
    return chain, strategies


def test_first_target_provisions_ups_and_verifies(tmp_path):
    chain, strategies = _build(tmp_path, ["a", "b"])
    step = chain.next_target("a")

    assert step.target_id == "a"
    assert step.previous is None
    assert step.reclaimed == ()
    assert step.pulled == ("reg/a",)
    assert step.images == ("ph/mock/a:svc",)
    assert strategies["a"].calls == ["provision", "up", "await_ready"]
    assert chain.state.active_target == "a"


def test_second_target_reclaims_a_reclaimable_previous_then_provisions(tmp_path):
    # A third target keeps "b" mid-chain, so its active_target is preserved;
    # the terminal clearing is pinned by its own tests below.
    chain, strategies = _build(tmp_path, ["a", "b", "c"], reclaimable="a")
    chain.next_target("a")
    strategies["a"].calls.clear()

    step = chain.next_target("b")

    assert step.previous == "a"
    assert strategies["a"].calls == ["down", "reclaim"]
    assert step.reclaimed == ("reclaim a",)
    assert strategies["b"].calls == ["provision", "up", "await_ready"]
    assert chain.state.active_target == "b"
    assert chain.state.completed == ("a", "b")


def test_second_target_does_not_reclaim_a_non_reclaimable_previous(tmp_path):
    chain, strategies = _build(tmp_path, ["a", "b"], reclaimable="b")

    chain.next_target("a")
    strategies["a"].calls.clear()
    step = chain.next_target("b")

    assert strategies["a"].calls == ["down"]
    assert step.reclaimed == ()


def test_failed_up_reclaims_a_reclaimable_target(tmp_path):
    chain, strategies = _build(tmp_path, ["a"], reclaimable="a", fail_up="a")

    with pytest.raises(chain_mod.TargetFailure):
        chain.next_target("a")

    assert strategies["a"].calls == ["provision", "up", "reclaim"]


def test_failed_up_does_not_reclaim_a_non_reclaimable_target(tmp_path):
    chain, strategies = _build(tmp_path, ["a"], reclaimable="b", fail_up="a")

    with pytest.raises(chain_mod.TargetFailure):
        chain.next_target("a")

    assert strategies["a"].calls == ["provision", "up"]


def test_bind_artifacts_stage_records_and_delegates(tmp_path):
    seen: list[str] = []
    chain, _ = _build(
        tmp_path, ["a"], bind_artifacts=lambda run: seen.append(run.target_id)
    )

    chain.next_target("a")

    assert seen == ["a"]


def test_bind_artifacts_stage_records_the_step(tmp_path):
    def boom(run):
        raise TargetError("artifact bind failed")

    chain, _ = _build(tmp_path, ["a"], reclaimable="b", bind_artifacts=boom)

    with pytest.raises(chain_mod.TargetFailure) as excinfo:
        chain.next_target("a")

    assert excinfo.value.step == "bind_artifacts"
    assert excinfo.value.trace[-1] == "bind_artifacts"


def test_next_target_ensures_the_shared_front(tmp_path):
    """D45: every lifecycle is local, so the chain creates `ph-eval-front` itself."""
    seen: list = []
    instance = _instance(["a"])
    chain = chain_mod.Chain(
        instance=instance,
        paths=_paths(tmp_path, instance),
        strategy_for=lambda run: FakeStrategy(run.target_id),
        runner=lambda command: seen.append(" ".join(command.argv)) or CommandResult(0),
        files=FileStore(),
        state_path=tmp_path / "chain-state.yaml",
    )

    chain.next_target("a")

    assert any("ph-eval-front" in text for text in seen)


def test_unknown_target_is_a_failure(tmp_path):
    chain, _ = _build(tmp_path, ["a"])
    with pytest.raises(chain_mod.TargetFailure) as excinfo:
        chain.next_target("nope")
    assert "unknown target" in excinfo.value.error


def test_up_failure_carries_trace_and_traceback(tmp_path):
    chain, _ = _build(tmp_path, ["a"], reclaimable="b", fail_up="a")
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


# --- terminal chain state (F10) ----------------------------------------------


def test_completed_chain_clears_the_active_target(tmp_path):
    """F10: once every target is complete, no target is active.

    A completed chain leaves no target to advance to, so `active_target` must
    be cleared rather than left pointing at the last target of the run.
    """
    chain, _ = _build(tmp_path, ["a", "b"])
    chain.next_target("a")

    chain.next_target("b")

    assert chain.state.active_target is None
    assert chain.state.completed == ("a", "b")
    on_disk = yaml.safe_load((tmp_path / "chain-state.yaml").read_text(encoding="utf-8"))
    assert on_disk == {
        "instance_id": "eval-server-1",
        "active_target": None,
        "completed": ["a", "b"],
    }


def test_completed_chain_clears_the_active_target_after_its_last_target(tmp_path):
    """The terminal transition happens on the last target in the declared order."""
    chain, _ = _build(tmp_path, ["a"])

    chain.next_target("a")

    assert chain.state.active_target is None
    assert chain.state.completed == ("a",)


def test_rerun_after_a_completed_chain_does_not_teardown_a_stale_target(tmp_path):
    """F10: the stale active target must not make a re-run tear it down again.

    Before the fix, a completed chain left `active_target` set, so the next
    run's first `next_target` tore down a target that was already done.
    """
    chain, strategies = _build(tmp_path, ["a", "b"])
    chain.next_target("a")
    chain.next_target("b")
    strategies["a"].calls.clear()
    strategies["b"].calls.clear()

    step = chain.next_target("a")

    assert step.previous is None
    assert "down" not in strategies["a"].calls
    assert strategies["a"].calls == ["provision", "up", "await_ready"]


def test_partial_chain_keeps_the_active_target_for_resume(tmp_path):
    """A chain that did not finish keeps its position, so a resume tears it down."""
    chain, _ = _build(tmp_path, ["a", "b", "c"])
    chain.next_target("a")
    chain.next_target("b")

    resumed, _ = _build(tmp_path, ["a", "b", "c"])

    assert resumed.state.active_target == "b"
    assert resumed.state.completed == ("a", "b")
