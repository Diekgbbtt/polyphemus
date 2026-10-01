"""Tests for the delivery plane's fast-forward script (`eval/deploy/ff_dev.sh`).

The script owns exactly one reference: `origin/dev` -> the canonical server
checkout's local `dev`. These tests exercise it directly against local git
repositories (a bare repo standing in for the public HTTPS origin), no ssh:
the workflow's ssh wiring is thin and asserted separately in
`test_deploy_workflow.py`.

Covered, per ticket #268:
  (a) first run clones the checkout and lands on origin's `dev` SHA;
  (b) a later upstream commit is fast-forwarded;
  (c) a diverged `dev` fails loudly and leaves the working tree untouched;
  (d) an `eval` branch in the origin is never checked out or modified;
  (e) a missing required env var names the variable in the failure;
  (f) a checkout whose `origin` is a stale URL is repointed to the configured
      origin, so the pushed commit is delivered instead of a no-op.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "eval" / "deploy" / "ff_dev.sh"


def git(*args: str, cwd: Path) -> str:
    """Run git with a fixed identity so the tests need no global config."""
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def commit(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    git("add", name, cwd=repo)
    git(
        "-c",
        "user.email=eval@test",
        "-c",
        "user.name=eval",
        "commit",
        "-q",
        "-m",
        message,
        cwd=repo,
    )
    return rev(repo, "HEAD")


def rev(repo: Path, ref: str) -> str:
    return git("rev-parse", ref, cwd=repo).strip()


@pytest.fixture
def origin(tmp_path: Path) -> tuple[Path, Path]:
    """A bare repo as `origin`, with a `dev` branch and an `eval` branch.

    Returns `(seed, bare)`: `seed` is a working clone wired to `bare` so new
    upstream commits can be pushed; `bare` is what the script clones from.
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-q", "-b", "dev", cwd=seed)
    commit(seed, "app.txt", "v1\n", "v1")

    # An `eval` branch exists in the origin and carries an eval-only file - the
    # script must never check it out or let it reach the server's working tree.
    git("checkout", "-q", "-b", "eval", cwd=seed)
    commit(seed, "eval-only.txt", "eval marker\n", "eval marker")
    git("checkout", "-q", "dev", cwd=seed)

    bare = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(seed), str(bare), cwd=tmp_path)
    git("remote", "add", "origin", str(bare), cwd=seed)
    return seed, bare


def run_ff(
    bare: Path, dev_dir: Path, *, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "EVAL_DEV_DIR"}
    env["EVAL_DEV_DIR"] = str(dev_dir)
    env["EVAL_DEV_ORIGIN"] = str(bare)
    env.update(extra or {})
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env
    )


def bump_dev(seed: Path, content: str, message: str) -> str:
    sha = commit(seed, "app.txt", content, message)
    git("push", "-q", "origin", "dev", cwd=seed)
    return sha


def test_first_run_clones_and_lands_on_origin_dev(tmp_path: Path, origin) -> None:
    seed, bare = origin
    dev_dir = tmp_path / "server" / "dev"

    result = run_ff(bare, dev_dir)

    assert result.returncode == 0, result.stderr
    assert (dev_dir / ".git").exists()
    expected = rev(seed, "dev")
    assert rev(dev_dir, "HEAD") == expected
    assert rev(dev_dir, "dev") == expected
    assert expected in result.stdout  # the success line carries the new SHA


def test_second_run_fast_forwards_a_new_upstream_commit(tmp_path: Path, origin) -> None:
    seed, bare = origin
    dev_dir = tmp_path / "server" / "dev"
    assert run_ff(bare, dev_dir).returncode == 0

    new_sha = bump_dev(seed, "v2\n", "v2")
    result = run_ff(bare, dev_dir)

    assert result.returncode == 0, result.stderr
    assert rev(dev_dir, "HEAD") == new_sha
    assert (dev_dir / "app.txt").read_text(encoding="utf-8") == "v2\n"
    assert new_sha in result.stdout


def test_diverged_dev_fails_loudly_and_leaves_the_tree_untouched(
    tmp_path: Path, origin
) -> None:
    seed, bare = origin
    dev_dir = tmp_path / "server" / "dev"
    assert run_ff(bare, dev_dir).returncode == 0

    # Diverge: a local commit on `dev` that is not upstream...
    local_sha = commit(dev_dir, "local-only.txt", "local\n", "local work")
    # ...and a different upstream commit, so no fast-forward is possible.
    upstream_sha = bump_dev(seed, "v2\n", "v2")
    assert upstream_sha != local_sha

    result = run_ff(bare, dev_dir)

    assert result.returncode != 0
    assert rev(dev_dir, "HEAD") == local_sha
    assert (dev_dir / "local-only.txt").exists()
    assert git("status", "--porcelain", cwd=dev_dir).strip() == ""


def test_eval_branch_is_never_checked_out_or_modified(tmp_path: Path, origin) -> None:
    seed, bare = origin
    eval_sha_before = rev(bare, "refs/heads/eval")
    dev_dir = tmp_path / "server" / "dev"

    assert run_ff(bare, dev_dir).returncode == 0
    bump_dev(seed, "v2\n", "v2")
    assert run_ff(bare, dev_dir).returncode == 0

    # The eval branch cannot exist locally, nor as a remote-tracking ref
    # (the clone is single-branch on `dev`).
    for ref in ("refs/heads/eval", "refs/remotes/origin/eval"):
        assert (
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", ref],
                cwd=dev_dir,
                capture_output=True,
                text=True,
            ).returncode
            != 0
        ), f"{ref} unexpectedly exists"
    assert not (dev_dir / "eval-only.txt").exists()
    # The origin's own eval ref is untouched by any run.
    assert rev(bare, "refs/heads/eval") == eval_sha_before


def test_second_run_is_idempotent_when_already_current(tmp_path: Path, origin) -> None:
    seed, bare = origin
    dev_dir = tmp_path / "server" / "dev"
    assert run_ff(bare, dev_dir).returncode == 0
    sha = rev(dev_dir, "HEAD")

    result = run_ff(bare, dev_dir)

    assert result.returncode == 0, result.stderr
    assert rev(dev_dir, "HEAD") == sha
    assert sha in result.stdout


def test_repoints_a_stale_origin_and_delivers_the_pushed_commit(
    tmp_path: Path, origin
) -> None:
    seed, bare = origin
    dev_dir = tmp_path / "server" / "dev"

    # The checkout is first cloned from a *stale* origin (a bare copy of the
    # real origin made before the new commit)...
    stale = tmp_path / "stale.git"
    git("clone", "-q", "--bare", str(bare), str(stale), cwd=tmp_path)
    git(
        "clone", "-q", "--single-branch", "--branch", "dev",
        str(stale), str(dev_dir), cwd=tmp_path,
    )
    old_sha = rev(dev_dir, "HEAD")
    assert git("remote", "get-url", "origin", cwd=dev_dir).strip() == str(stale)

    # ...and the real upstream `dev` gains a commit the stale origin lacks.
    new_sha = bump_dev(seed, "v2\n", "v2")
    assert new_sha != old_sha

    result = run_ff(bare, dev_dir)

    assert result.returncode == 0, result.stderr
    # The remote was repointed to the configured origin and the commit delivered
    # (without the repoint this would have fast-forwarded stale -> itself).
    assert git("remote", "get-url", "origin", cwd=dev_dir).strip() == str(bare)
    assert "repointing origin" in result.stdout
    assert rev(dev_dir, "HEAD") == new_sha


def test_refuses_a_checkout_not_on_dev(tmp_path: Path, origin) -> None:
    seed, bare = origin
    dev_dir = tmp_path / "server" / "dev"
    git("clone", "-q", str(bare), str(dev_dir), cwd=tmp_path)
    git("checkout", "-q", "-b", "other", cwd=dev_dir)
    before = rev(dev_dir, "HEAD")

    result = run_ff(bare, dev_dir)

    assert result.returncode != 0
    assert "dev" in result.stderr
    assert rev(dev_dir, "HEAD") == before


def test_missing_required_env_names_the_variable(tmp_path: Path, origin) -> None:
    seed, bare = origin
    env = {k: v for k, v in os.environ.items() if k != "EVAL_DEV_DIR"}
    env["EVAL_DEV_ORIGIN"] = str(bare)

    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env
    )

    assert result.returncode != 0
    assert "EVAL_DEV_DIR" in result.stderr
