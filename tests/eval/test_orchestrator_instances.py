"""Per-instance stack lifecycle (ticket #269, D1/D11/D29/D10).

Each `PolyphemusInstance` is one compose project (`ph-<short>`) in its own git
worktree off the `eval` branch, carrying its own `.env`. The command plans are
pure, so the sequences are asserted without Docker; the worktree commands are
exercised against a real temporary git repository.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orchestrator import instances, setup as setup_mod
from orchestrator.commands import LocalRunner


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def eval_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    # The canonical checkout sits on its own branch; `eval` is the read-only
    # branch instances are added from (a branch cannot be checked out twice).
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "eval@test")
    _git(repo, "config", "user.name", "eval")
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "eval")
    return repo


def _instance(instance_id: str, target_id: str = "t-1") -> setup_mod.Instance:
    run = setup_mod.TargetRun(
        target_key="webexploitbench/jetlinks", target_id=target_id
    )
    return setup_mod.Instance(instance_id=instance_id, targets=(run,))


def _paths(tmp_path: Path, repo: Path, instance, **kwargs) -> instances.InstancePaths:
    return instances.instance_paths(
        instance, tmp_path / "instances", repo=repo, branch="eval", **kwargs
    )


def test_compose_project_is_ph_short_and_unique(tmp_path, eval_repo) -> None:
    a = _paths(tmp_path, eval_repo, _instance("arm-a"))
    b = _paths(tmp_path, eval_repo, _instance("arm-b"))
    a_again = _paths(tmp_path, eval_repo, _instance("arm-a"))

    assert a.compose_project.startswith("ph-")
    assert a.compose_project == a_again.compose_project
    assert a.compose_project != b.compose_project
    assert len(a.compose_project) == len("ph-") + 8


def test_paths_default_env_file_and_worktree(tmp_path, eval_repo) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))

    assert paths.worktree == tmp_path / "instances" / "arm-a"
    assert paths.env_file == paths.worktree / ".env"


def test_overlay_and_dev_files_are_included(tmp_path, eval_repo) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))

    argv = instances.compose_argv(paths, "config")

    assert argv[:3] == ["docker", "compose", "-p"]
    assert argv[3] == paths.compose_project
    assert "docker-compose.yml" in argv
    assert "docker-compose.dev.yml" in argv
    assert instances.OVERLAY_FILE in argv
    assert argv[-1] == "config"


def test_plan_up_sequence(tmp_path, eval_repo) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))

    plan = instances.plan_up(paths)

    worktree_add = plan[0].argv
    assert worktree_add[:3] == ("git", "-C", str(eval_repo))
    assert worktree_add[3:5] == ("worktree", "add")
    # Detached at the eval ref: any number of instances can share one branch
    # (git refuses the same branch in two worktrees).
    assert "--detach" in worktree_add
    assert str(paths.worktree) in worktree_add
    assert "eval" in worktree_add

    seed = plan[1].argv
    assert seed[:2] == ("cp", "-rn")
    assert str(paths.data_root) in seed[-1]

    preflight = plan[2]
    assert "env_preflight.py" in preflight.argv[1]
    assert str(paths.env_file) in preflight.argv
    assert preflight.cwd == str(paths.worktree)

    render = plan[3].argv
    assert render[-1] == "config"
    assert render[render.index("-p") + 1] == paths.compose_project

    up = plan[4].argv
    assert up[-2:] == ("up", "-d")
    assert plan[4].cwd == str(paths.worktree)


def test_plan_down_sequence_only_touches_its_own_project(tmp_path, eval_repo) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))
    other = _paths(tmp_path, eval_repo, _instance("arm-b"))

    plan = instances.plan_down(paths)

    # The worktree (and the instance data root inside it) MUST outlive the
    # stack lifecycle: down is compose-only, never a worktree removal.
    assert len(plan) == 1
    down = plan[0].argv
    assert down[-3:] == ("down", "-v", "--remove-orphans")
    assert down[down.index("-p") + 1] == paths.compose_project
    assert other.compose_project not in down
    assert not any("worktree" in arg for arg in down)


def test_plan_status_is_a_compose_ps(tmp_path, eval_repo) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))

    status = instances.plan_status(paths)

    assert status.argv[-1] == "ps"
    assert status.argv[status.argv.index("-p") + 1] == paths.compose_project


def test_up_runs_the_plan_through_the_runner(
    tmp_path, eval_repo, recording_runner
) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))
    runner = recording_runner()

    instances.up(paths, runner)

    texts = runner.argv_texts
    assert any("worktree add" in t for t in texts)
    assert any("env_preflight.py" in t for t in texts)
    assert any(t.endswith("config") for t in texts)
    assert any(t.endswith("up -d") for t in texts)


def test_down_runs_the_plan_through_the_runner(
    tmp_path, eval_repo, recording_runner
) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))
    paths.worktree.mkdir(parents=True)  # teardown follows a real bring-up
    runner = recording_runner()

    instances.down(paths, runner)

    texts = runner.argv_texts
    assert any("down -v --remove-orphans" in t for t in texts)
    # The worktree survives the teardown (its data root is preserved).
    assert not any("worktree remove" in t for t in texts)
    assert paths.worktree.exists()


def test_up_raises_on_preflight_failure(
    tmp_path, eval_repo, recording_runner, fake_result
) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))
    runner = recording_runner(
        routes={
            "env_preflight.py": fake_result(1, stderr="missing NEO4J_URI"),
        }
    )

    with pytest.raises(instances.InstanceError, match="NEO4J_URI"):
        instances.up(paths, runner)


def test_status_returns_runner_stdout(
    tmp_path, eval_repo, recording_runner, fake_result
) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))
    runner = recording_runner(default=fake_result(0, stdout="NAME  STATUS\nkali  running\n"))

    assert "kali" in instances.status(paths, runner)


def test_real_git_worktree_create_and_remove(tmp_path, eval_repo) -> None:
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))
    git = LocalRunner()

    instances.ensure_worktree(paths, git)

    assert paths.worktree.is_dir()
    assert (paths.worktree / ".git").exists()
    assert (paths.worktree / "tracked.txt").read_text(encoding="utf-8") == "v1\n"

    instances.remove_worktree(paths, git)

    assert not paths.worktree.exists()


def test_down_preserves_the_worktree_and_its_data_root(
    tmp_path, eval_repo, recording_runner
) -> None:
    """down stops the stack but NEVER removes the worktree (its data root)."""
    paths = _paths(tmp_path, eval_repo, _instance("arm-a"))
    (paths.worktree / "data" / "hunting").mkdir(parents=True)
    (paths.worktree / "data" / "hunting" / "hunt.yaml").write_text("keep\n")
    runner = recording_runner()

    instances.down(paths, runner)

    assert paths.worktree.is_dir()
    assert (paths.worktree / "data" / "hunting" / "hunt.yaml").read_text() == "keep\n"
    assert not any("worktree" in t for t in runner.argv_texts)


def test_two_instances_share_the_eval_branch_detached(tmp_path, eval_repo) -> None:
    """The #269 critical: a second instance must be creatable off the one eval branch.

    A branch can be checked out in only one worktree, so instance worktrees are
    created DETACHED at the eval commit (D29); any number can share it.
    """
    a = _paths(tmp_path, eval_repo, _instance("arm-a"))
    b = _paths(tmp_path, eval_repo, _instance("arm-b"))
    git = LocalRunner()
    eval_sha = _git(eval_repo, "rev-parse", "eval").strip()

    instances.ensure_worktree(a, git)
    instances.ensure_worktree(b, git)

    assert a.worktree.is_dir()
    assert b.worktree.is_dir()
    for path in (a.worktree, b.worktree):
        assert _git(path, "rev-parse", "HEAD").strip() == eval_sha
        # Detached: no branch is consumed by the worktree.
        symbolic = subprocess.run(
            ["git", "-C", str(path), "symbolic-ref", "-q", "HEAD"],
            capture_output=True,
            text=True,
        )
        assert symbolic.returncode != 0
    # The eval branch is still available for the next instance.
    assert _git(eval_repo, "rev-parse", "eval").strip() == eval_sha
