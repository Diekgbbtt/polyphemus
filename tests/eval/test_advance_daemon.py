"""Unit and integration tests for the eval sync daemon (`eval/advance/daemon.py`).

D25/D34/D38/D42: the daemon is a mechanical executor. It reads HEADs, checks
ancestry, stashes leaked tracked edits, fast-forwards `eval` to `dev` inside an
all-idle window, records the last-known-good SHA before moving, writes a
heartbeat, and alerts on a non-fast-forward. It never fetches, commits, merges
(except `--ff-only`), checks out another branch, resets, or rewinds during
polling. Rewind is a separate operator-only command.

The git operations are real, against temporary worktrees, so the tests exercise
the same commands the daemon runs; the app-state proxy, clock, alert sink, and
image-digest provider are injected.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest

from advance import app_state, daemon, images, manifest
from advance.fingerprint import fingerprint

DIGESTS = {
    "postgres": "sha256:" + "1" * 64,
    "neo4j": "sha256:" + "2" * 64,
    "lightrag": "sha256:" + "3" * 64,
    "kali": "sha256:" + "4" * 64,
    "litellm": "sha256:" + "5" * 64,
    "agent": "sha256:" + "6" * 64,
}

FORBIDDEN_POLL_SUBCOMMANDS = {
    "fetch",
    "reset",
    "checkout",
    "commit",
    "rebase",
    "pull",
    "push",
    "clean",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


@dataclass
class EvalEnv:
    root: Path
    dev: Path
    evals: tuple[Path, ...]

    def head(self, repo: Path) -> str:
        return git(repo, "rev-parse", "HEAD").strip()

    def advance_dev(self, text: str) -> str:
        write(self.dev, "src/polymerhus/app.py", text)
        return commit_all(self.dev, "dev advance")

    def diverge_eval(self, text: str) -> str:
        write(self.evals[0], "src/polymerhus/app.py", text)
        return commit_all(self.evals[0], "leaked eval commit")


@pytest.fixture()
def eval_env(tmp_path: Path) -> EvalEnv:
    root = tmp_path / "root"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "eval@example.invalid")
    git(root, "config", "user.name", "eval test")
    write(root, "src/polymerhus/app.py", "v0\n")
    write(root, "base.txt", "base\n")
    write(root, "conflict.txt", "base\n")
    commit_all(root, "base")
    git(root, "branch", "dev")

    dev = tmp_path / "dev"
    git(root, "worktree", "add", "-q", str(dev), "dev")
    eval_wt = tmp_path / "eval"
    # #269/D29: eval instances run detached so they can share the read-only
    # `eval` branch; the daemon requires a detached eval worktree (M4).
    git(root, "worktree", "add", "-q", "--detach", str(eval_wt), "dev")
    return EvalEnv(root=root, dev=dev, evals=(eval_wt,))


def make_detached_env(tmp_path: Path, n: int = 2) -> EvalEnv:
    """An env whose eval worktrees are DETACHED at the eval ref (D29, #269).

    A branch can be checked out in one worktree only; the orchestrator creates
    every instance detached so they can share the read-only `eval` branch.
    """
    root = tmp_path / "droot"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "eval@example.invalid")
    git(root, "config", "user.name", "eval test")
    write(root, "src/polymerhus/app.py", "v0\n")
    write(root, "base.txt", "base\n")
    commit_all(root, "base")
    git(root, "branch", "dev")
    git(root, "branch", "eval", "dev")

    dev = tmp_path / "ddev"
    git(root, "worktree", "add", "-q", str(dev), "dev")
    evals = []
    for index in range(n):
        worktree = tmp_path / f"deval{index}"
        git(root, "worktree", "add", "-q", "--detach", str(worktree), "eval")
        evals.append(worktree)
    return EvalEnv(root=root, dev=dev, evals=tuple(evals))


@dataclass
class RecordingGit:
    calls: list[tuple[Path, list[str]]] = field(default_factory=list)

    def __call__(self, repo: Path, args) -> images.CommandResult:
        self.calls.append((Path(repo), list(args)))
        return manifest.default_git_runner(repo, args)

    def subcommands(self) -> list[str]:
        return [args[0] for _repo, args in self.calls]


@dataclass
class PartialMergeGit:
    """A git runner whose `merge --ff-only` fails for one worktree only.

    Models the #267 partial advance: an earlier worktree is already fast-forwarded
    when a later one refuses, so the environment ends split.
    """

    fail_worktree: Path
    calls: list[tuple[Path, list[str]]] = field(default_factory=list)

    def __call__(self, repo: Path, args) -> images.CommandResult:
        self.calls.append((Path(repo), list(args)))
        if list(args)[:2] == ["merge", "--ff-only"] and Path(repo) == self.fail_worktree:
            return images.CommandResult(1, "", "fatal: Not possible to fast-forward")
        return manifest.default_git_runner(repo, args)

    def subcommands(self) -> list[str]:
        return [args[0] for _repo, args in self.calls]


@dataclass
class FakeClock:
    n: int = 0

    def __call__(self) -> datetime:
        self.n += 1
        return datetime(2026, 9, 28, 12, 0, self.n % 60, tzinfo=timezone.utc)


class FakeIdle:
    def __init__(self, idle: bool = True, error: Exception | None = None) -> None:
        self.idle = idle
        self.error = error
        self.calls = 0

    def fetch(self) -> app_state.AppState:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return app_state.AppState(idle=self.idle, projects=())


def make_config(env: EvalEnv, tmp_path: Path, **overrides) -> daemon.DaemonConfig:
    base = dict(
        dev_worktree=env.dev,
        eval_worktrees=env.evals,
        app_state_url="http://agent.invalid:8000",
        heartbeat_path=tmp_path / "heartbeat.json",
        poll_interval=1.0,
        dsn="postgresql://example/db",
        alert_command=None,
    )
    base.update(overrides)
    return daemon.DaemonConfig(**base)


def make_daemon(
    env: EvalEnv,
    tmp_path: Path,
    *,
    idle: bool = True,
    idle_error: Exception | None = None,
    config: daemon.DaemonConfig | None = None,
    image_digests=None,
):
    records: list[dict] = []
    recorder = RecordingGit()
    clock = FakeClock()
    proxy = FakeIdle(idle=idle, error=idle_error)
    d = daemon.Daemon(
        config or make_config(env, tmp_path),
        git_runner=recorder,
        idle_proxy=proxy,
        clock=clock,
        log=records.append,
        image_digests=image_digests or (lambda: dict(DIGESTS)),
    )
    return d, records, recorder, proxy


def assert_poll_commands_safe(recorder: RecordingGit) -> None:
    for _repo, args in recorder.calls:
        assert args[0] not in FORBIDDEN_POLL_SUBCOMMANDS, args
        if args[0] == "merge":
            assert "--ff-only" in args, args


def alert_kinds(records: list[dict]) -> list[str]:
    return [r["alert"] for r in records if "alert" in r]


def read_heartbeat(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- idle gate ---------------------------------------------------------------


def test_non_idle_window_does_not_advance(eval_env: EvalEnv, tmp_path: Path) -> None:
    old = eval_env.head(eval_env.evals[0])
    dev_sha = eval_env.advance_dev("v1\n")
    d, records, recorder, proxy = make_daemon(eval_env, tmp_path, idle=False)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_BUSY
    assert heartbeat["idle"] is False
    assert eval_env.head(eval_env.evals[0]) == old
    assert dev_sha != old
    assert recorder.calls and recorder.subcommands().count("merge") == 0
    hb = read_heartbeat(make_config(eval_env, tmp_path).heartbeat_path)
    assert hb == heartbeat
    assert_poll_commands_safe(recorder)


def test_unknown_idle_state_does_not_advance(eval_env: EvalEnv, tmp_path: Path) -> None:
    old = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")
    d, records, recorder, _proxy = make_daemon(
        eval_env, tmp_path, idle_error=app_state.AppStateUnavailable("down")
    )

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_IDLE_UNKNOWN
    assert heartbeat["idle"] is None
    assert eval_env.head(eval_env.evals[0]) == old
    assert "idle_unknown" in alert_kinds(records)
    assert_poll_commands_safe(recorder)


# --- clean advance -----------------------------------------------------------


def test_clean_advance_when_idle_and_dev_ahead(eval_env: EvalEnv, tmp_path: Path) -> None:
    dev_sha = eval_env.advance_dev("v1\n")
    d, records, recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_ADVANCED
    assert heartbeat["dev_sha"] == dev_sha
    assert heartbeat["eval_sha"] == dev_sha
    assert heartbeat["idle"] is True
    assert heartbeat["last_advance_at"] is not None
    assert eval_env.head(eval_env.evals[0]) == dev_sha
    assert "advanced" in [r.get("event") for r in records]
    assert_poll_commands_safe(recorder)


def test_up_to_date_poll_is_a_noop(eval_env: EvalEnv, tmp_path: Path) -> None:
    d, _records, recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_UP_TO_DATE
    assert heartbeat["dev_sha"] == heartbeat["eval_sha"]
    assert "merge" not in recorder.subcommands()
    assert_poll_commands_safe(recorder)


def test_advance_moves_every_eval_worktree_environment_wide(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    second = tmp_path / "eval2"
    git(eval_env.root, "worktree", "add", "-q", "--detach", str(second), "dev")
    env = EvalEnv(root=eval_env.root, dev=eval_env.dev, evals=eval_env.evals + (second,))
    dev_sha = env.advance_dev("v1\n")
    d, _records, _recorder, _proxy = make_daemon(env, tmp_path, idle=True)

    d.poll_once()

    assert env.head(second) == dev_sha
    assert env.head(env.evals[0]) == dev_sha


def test_advance_moves_detached_worktrees_in_lockstep(tmp_path: Path) -> None:
    """#269: the orchestrator creates detached instances; the daemon still advances them."""
    env = make_detached_env(tmp_path, n=2)
    dev_sha = env.advance_dev("v1\n")
    d, _records, recorder, _proxy = make_daemon(env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_ADVANCED
    assert heartbeat["eval_sha"] == dev_sha
    for worktree in env.evals:
        assert env.head(worktree) == dev_sha
    # A detached HEAD is fast-forwarded by `merge --ff-only`, never reset.
    assert "merge" in recorder.subcommands()
    assert "reset" not in recorder.subcommands()
    assert_poll_commands_safe(recorder)


def test_detached_non_fast_forward_alerts_and_leaves_both_untouched(
    tmp_path: Path,
) -> None:
    env = make_detached_env(tmp_path, n=2)
    leaked = env.diverge_eval("eval-only\n")
    # Both detached worktrees at the SAME leaked commit: no skew, a real
    # non-fast-forward for the whole environment.
    git(env.evals[1], "checkout", "-q", "--detach", leaked)
    env.advance_dev("v1\n")
    before = [env.head(worktree) for worktree in env.evals]
    d, records, recorder, _proxy = make_daemon(env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_NON_FAST_FORWARD
    assert "non_fast_forward" in alert_kinds(records)
    assert [env.head(worktree) for worktree in env.evals] == before
    assert "merge" not in recorder.subcommands()
    assert_poll_commands_safe(recorder)


# --- M4: only a detached eval worktree is advanced ----------------------------


def test_a_branch_checked_out_worktree_is_skipped_and_alerted(tmp_path: Path) -> None:
    env = make_detached_env(tmp_path, n=2)
    base = env.head(env.evals[1])
    git(env.root, "branch", "evalb", "dev")
    git(env.evals[1], "checkout", "-q", "evalb")
    dev_sha = env.advance_dev("v1\n")
    d, records, recorder, _proxy = make_daemon(env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    # The detached worktree moved; the branch checkout was skipped untouched.
    assert env.head(env.evals[0]) == dev_sha
    assert env.head(env.evals[1]) == base
    assert "worktree_not_detached" in alert_kinds(records)
    assert heartbeat["state"] == daemon.STATE_PARTIAL
    assert "advance_failed" not in alert_kinds(records)
    assert_poll_commands_safe(recorder)


def test_all_branch_worktrees_are_not_reported_as_advanced(tmp_path: Path) -> None:
    env = make_detached_env(tmp_path, n=2)
    git(env.root, "branch", "evalb0", "dev")
    git(env.root, "branch", "evalb1", "dev")
    git(env.evals[0], "checkout", "-q", "evalb0")
    git(env.evals[1], "checkout", "-q", "evalb1")
    before = [env.head(worktree) for worktree in env.evals]
    env.advance_dev("v1\n")
    d, records, _recorder, _proxy = make_daemon(env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_WORKTREE_NOT_DETACHED
    assert [env.head(w) for w in env.evals] == before
    assert "worktree_not_detached" in alert_kinds(records)


# --- dirty worktree ----------------------------------------------------------


def test_leaked_tracked_edit_is_stashed_and_popped(eval_env: EvalEnv, tmp_path: Path) -> None:
    eval_wt = eval_env.evals[0]
    write(eval_wt, "base.txt", "workbench edit\n")
    dev_sha = eval_env.advance_dev("v1\n")
    d, _records, recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_ADVANCED
    assert eval_env.head(eval_wt) == dev_sha
    assert (eval_wt / "base.txt").read_text() == "workbench edit\n"
    assert any(args[0] == "stash" and args[1] == "push" for _repo, args in recorder.calls)
    assert any(args[0] == "stash" and args[1] == "pop" for _repo, args in recorder.calls)
    assert_poll_commands_safe(recorder)


def test_untracked_file_is_not_stashed(eval_env: EvalEnv, tmp_path: Path) -> None:
    eval_wt = eval_env.evals[0]
    write(eval_wt, "scratch.txt", "not tracked\n")
    eval_env.advance_dev("v1\n")
    d, _records, recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True)

    d.poll_once()

    assert (eval_wt / "scratch.txt").read_text() == "not tracked\n"
    assert "stash" not in recorder.subcommands()


def test_pop_conflict_alerts_and_keeps_the_work(eval_env: EvalEnv, tmp_path: Path) -> None:
    eval_wt = eval_env.evals[0]
    write(eval_wt, "conflict.txt", "eval edit\n")
    write(eval_env.dev, "conflict.txt", "dev edit\n")
    eval_env.advance_dev("v1\n")
    d, records, recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_POP_CONFLICT
    assert "pop_conflict" in alert_kinds(records)
    # The stash is retained on conflict, so the leaked edit is not lost.
    assert git(eval_wt, "stash", "list").strip() != ""
    assert "<<<<<<<" in (eval_wt / "conflict.txt").read_text()
    assert_poll_commands_safe(recorder)


# --- non-fast-forward --------------------------------------------------------


def test_non_fast_forward_alerts_and_leaves_the_tree_untouched(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    eval_wt = eval_env.evals[0]
    diverged = eval_env.diverge_eval("eval-only\n")
    eval_env.advance_dev("v1\n")
    before = {
        "head": eval_env.head(eval_wt),
        "clean": git(eval_wt, "status", "--porcelain"),
        "content": (eval_wt / "src/polymerhus/app.py").read_text(),
    }
    d, records, recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_NON_FAST_FORWARD
    assert "non_fast_forward" in alert_kinds(records)
    assert eval_env.head(eval_wt) == diverged == before["head"]
    assert git(eval_wt, "status", "--porcelain") == before["clean"]
    assert (eval_wt / "src/polymerhus/app.py").read_text() == before["content"]
    assert "merge" not in recorder.subcommands()
    assert "stash" not in recorder.subcommands()
    assert_poll_commands_safe(recorder)


# --- M6: a git ancestry error is not a non-fast-forward -----------------------


@dataclass
class AncestryFailingGit:
    """A git runner whose `merge-base --is-ancestor` fails (a transient error)."""

    calls: list[tuple[Path, list[str]]] = field(default_factory=list)

    def __call__(self, repo: Path, args) -> images.CommandResult:
        self.calls.append((Path(repo), list(args)))
        if list(args)[:2] == ["merge-base", "--is-ancestor"]:
            return images.CommandResult(2, "", "fatal: bad revision")
        return manifest.default_git_runner(repo, args)

    def subcommands(self) -> list[str]:
        return [args[0] for _repo, args in self.calls]


def test_ancestry_check_failure_is_not_reported_as_non_fast_forward(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    old = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")
    records: list[dict] = []
    runner = AncestryFailingGit()
    d = daemon.Daemon(
        make_config(eval_env, tmp_path),
        git_runner=runner,
        idle_proxy=FakeIdle(True),
        clock=FakeClock(),
        log=records.append,
        image_digests=lambda: dict(DIGESTS),
    )

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_ERROR
    assert "ancestry_check_failed" in alert_kinds(records)
    assert "non_fast_forward" not in alert_kinds(records)
    assert eval_env.head(eval_env.evals[0]) == old
    assert "merge" not in runner.subcommands()


# --- heartbeat and last-known-good ------------------------------------------


def test_partial_advance_reports_each_worktree_actual_head(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    """#267: a later worktree's failure must not report the pre-advance SHA."""
    second = tmp_path / "eval2"
    git(eval_env.root, "worktree", "add", "-q", "--detach", str(second), "dev")
    env = EvalEnv(root=eval_env.root, dev=eval_env.dev, evals=eval_env.evals + (second,))
    base = env.head(env.evals[0])
    dev_sha = env.advance_dev("v1\n")
    records: list[dict] = []
    runner = PartialMergeGit(fail_worktree=second)
    d = daemon.Daemon(
        make_config(env, tmp_path),
        git_runner=runner,
        idle_proxy=FakeIdle(True),
        clock=FakeClock(),
        log=records.append,
        image_digests=lambda: dict(DIGESTS),
    )

    heartbeat = d.poll_once()

    assert runner.subcommands().count("merge") == 2
    assert heartbeat["state"] == daemon.STATE_PARTIAL
    assert env.head(env.evals[0]) == dev_sha  # the first worktree really moved
    assert env.head(second) == base
    by_path = {entry["path"]: entry for entry in heartbeat["worktrees"]}
    assert by_path[str(env.evals[0])]["head"] == dev_sha
    assert by_path[str(env.evals[0])]["at_dev"] is True
    assert by_path[str(second)]["head"] == base
    assert by_path[str(second)]["at_dev"] is False
    # The reported eval SHA is a real observed HEAD, not the stale pre-advance one.
    assert heartbeat["eval_sha"] == dev_sha
    assert "advance_failed" in alert_kinds(records)
    logged = [record for record in records if record.get("event") == daemon.STATE_PARTIAL]
    assert logged and {entry["path"] for entry in logged[0]["worktrees"]} == {
        str(env.evals[0]),
        str(second),
    }


def test_heartbeat_reflects_each_poll_and_carries_the_decision(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    config = make_config(eval_env, tmp_path)
    d, _records, _recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True, config=config)

    first = d.poll_once()
    assert read_heartbeat(config.heartbeat_path) == first
    assert first["state"] == daemon.STATE_UP_TO_DATE

    dev_sha = eval_env.advance_dev("v1\n")
    second = d.poll_once()

    assert second["state"] == daemon.STATE_ADVANCED
    assert read_heartbeat(config.heartbeat_path) == second
    assert second["dev_sha"] == dev_sha
    assert second["last_advance_at"] is not None
    decision = second["decision"]
    assert decision["dev_sha"] == dev_sha
    assert decision["all_idle"] is True
    changed = {c["name"] for c in decision["delta"]["changed"]}
    assert "src" in changed
    assert decision["fingerprints"]["eval"] != decision["fingerprints"]["dev"]

    # A later no-op poll keeps the last advance timestamp.
    third = d.poll_once()
    assert third["state"] == daemon.STATE_UP_TO_DATE
    assert third["last_advance_at"] == second["last_advance_at"]


def test_running_image_digests_flow_into_the_manifest_fingerprint(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    """#266/#267: production digests are the ones the manifest/fingerprint record."""
    dev_sha = eval_env.advance_dev("v1\n")
    d, _records, _recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    repo = eval_env.evals[0]
    expected = fingerprint(
        manifest.build_manifest(repo, dev_sha, DIGESTS, git_runner=manifest.default_git_runner)
    )
    assert heartbeat["decision"]["fingerprints"]["dev"] == expected
    other_digests = {**DIGESTS, "kali": "sha256:" + "f" * 64}
    other = fingerprint(
        manifest.build_manifest(
            repo, dev_sha, other_digests, git_runner=manifest.default_git_runner
        )
    )
    assert heartbeat["decision"]["fingerprints"]["dev"] != other


def test_digest_collection_failure_alerts_and_does_not_advance(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    """#266/#267: an unobservable stack is never advanced on an empty digest map."""
    old = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")

    def explode():
        raise images.ImageDigestError("docker inspect failed for 'kali' (c-kali)")

    d, records, recorder, _proxy = make_daemon(
        eval_env, tmp_path, idle=True, image_digests=explode
    )

    heartbeat = d.poll_once()

    assert eval_env.head(eval_env.evals[0]) == old
    assert heartbeat["state"] == daemon.STATE_IMAGE_DIGESTS_UNKNOWN
    assert "image_digests_unknown" in alert_kinds(records)
    assert heartbeat["eval_sha"] == old
    assert "merge" not in recorder.subcommands()
    assert daemon.last_known_good_shas(
        make_config(eval_env, tmp_path).last_known_good_file
    ) == []
    assert_poll_commands_safe(recorder)


def test_empty_digest_map_alerts_and_does_not_advance(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    """An empty map is the old silent default; it must be treated as unknown."""
    old = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")
    d, records, recorder, _proxy = make_daemon(
        eval_env, tmp_path, idle=True, image_digests=dict
    )

    heartbeat = d.poll_once()

    assert eval_env.head(eval_env.evals[0]) == old
    assert heartbeat["state"] == daemon.STATE_IMAGE_DIGESTS_UNKNOWN
    assert "image_digests_unknown" in alert_kinds(records)
    assert "merge" not in recorder.subcommands()


def test_daemon_defaults_to_collecting_digests_from_config(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    """#266/#267: `Daemon` with no injected provider uses the configured collector."""
    config = make_config(
        eval_env,
        tmp_path,
        image_containers={"kali": "ph-x-kali-1", "agent": "ph-x-agent-1"},
    )
    eval_env.advance_dev("v1\n")
    seen: list[list[str]] = []

    def image_runner(args) -> images.CommandResult:
        seen.append(list(args))
        return images.CommandResult(0, "sha256:" + "a" * 64 + "\n")

    records: list[dict] = []
    d = daemon.Daemon(
        config,
        git_runner=RecordingGit(),
        idle_proxy=FakeIdle(True),
        clock=FakeClock(),
        log=records.append,
        image_runner=image_runner,
    )

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_ADVANCED
    assert [call[-1] for call in seen] == ["ph-x-kali-1", "ph-x-agent-1"]
    assert heartbeat["decision"]["fingerprints"]["dev"]


# --- I1: N-instance idle gate and per-instance digests ------------------------


def make_multi_config(
    eval_env: EvalEnv, tmp_path: Path, instances: tuple[daemon.InstanceConfig, ...]
) -> daemon.DaemonConfig:
    return daemon.DaemonConfig(
        dev_worktree=eval_env.dev,
        eval_worktrees=eval_env.evals,
        app_state_url=instances[0].app_state_url,
        heartbeat_path=tmp_path / "heartbeat.json",
        poll_interval=1.0,
        instances=instances,
    )


def test_two_instances_one_busy_does_not_advance(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    """I1/D36: with N instances, one busy instance refuses the whole advance."""
    old = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")
    config = make_multi_config(
        eval_env,
        tmp_path,
        (
            daemon.InstanceConfig("arm-a", "http://a"),
            daemon.InstanceConfig("arm-b", "http://b"),
        ),
    )
    records: list[dict] = []
    d = daemon.Daemon(
        config,
        git_runner=RecordingGit(),
        idle_proxies={"arm-a": FakeIdle(True), "arm-b": FakeIdle(False)},
        clock=FakeClock(),
        log=records.append,
        image_digests=lambda: dict(DIGESTS),
    )

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_BUSY
    assert heartbeat["idle"] is False
    assert eval_env.head(eval_env.evals[0]) == old


def test_two_instances_any_unknown_does_not_advance(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    """I1/D36: an unknown idle verdict for any instance is never idle."""
    old = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")
    config = make_multi_config(
        eval_env,
        tmp_path,
        (
            daemon.InstanceConfig("arm-a", "http://a"),
            daemon.InstanceConfig("arm-b", "http://b"),
        ),
    )
    records: list[dict] = []
    d = daemon.Daemon(
        config,
        git_runner=RecordingGit(),
        idle_proxies={
            "arm-a": FakeIdle(True),
            "arm-b": FakeIdle(error=app_state.AppStateUnavailable("down")),
        },
        clock=FakeClock(),
        log=records.append,
        image_digests=lambda: dict(DIGESTS),
    )

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_IDLE_UNKNOWN
    assert heartbeat["idle"] is None
    assert eval_env.head(eval_env.evals[0]) == old
    assert "idle_unknown" in alert_kinds(records)


def test_two_instances_both_idle_advances(eval_env: EvalEnv, tmp_path: Path) -> None:
    """I1/D36: every instance idle is the only window that advances."""
    dev_sha = eval_env.advance_dev("v1\n")
    config = make_multi_config(
        eval_env,
        tmp_path,
        (
            daemon.InstanceConfig("arm-a", "http://a"),
            daemon.InstanceConfig("arm-b", "http://b"),
        ),
    )
    d = daemon.Daemon(
        config,
        git_runner=RecordingGit(),
        idle_proxies={"arm-a": FakeIdle(True), "arm-b": FakeIdle(True)},
        clock=FakeClock(),
        log=lambda record: None,
        image_digests=lambda: dict(DIGESTS),
    )

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_ADVANCED
    assert heartbeat["idle"] is True
    assert heartbeat["eval_sha"] == dev_sha


def test_default_image_digests_collects_each_instance_stack() -> None:
    """I1: digests are collected per instance stack and merged qualified."""
    config = daemon.DaemonConfig(
        dev_worktree=Path("/dev"),
        eval_worktrees=(Path("/e1"),),
        app_state_url="http://a",
        heartbeat_path=Path("/hb.json"),
        instances=(
            daemon.InstanceConfig("arm-a", "http://a", compose_project="ph-a"),
            daemon.InstanceConfig("arm-b", "http://b", compose_project="ph-b"),
        ),
    )
    seen: list[list[str]] = []

    def runner(args) -> images.CommandResult:
        seen.append(list(args))
        container = args[-1]
        mark = "a" if "-a-" in container else "b"
        return images.CommandResult(0, "sha256:" + mark * 64 + "\n")

    digests = daemon.default_image_digests(config, run=runner)()

    assert digests["arm-a:postgres"].startswith("sha256:" + "a" * 64)
    assert digests["arm-b:kali"].startswith("sha256:" + "b" * 64)
    assert "postgres" not in digests
    # Each stack's whole component map was inspected.
    assert any("ph-a-postgres-1" in call[-1] for call in seen)
    assert any("ph-b-postgres-1" in call[-1] for call in seen)


def test_two_instance_digests_flow_into_the_manifest_and_fingerprint(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    """I1: the manifest/fingerprint carry both instance-qualified stacks."""
    dev_sha = eval_env.advance_dev("v1\n")
    config = make_multi_config(
        eval_env,
        tmp_path,
        (
            daemon.InstanceConfig("arm-a", "http://a"),
            daemon.InstanceConfig("arm-b", "http://b"),
        ),
    )
    merged = {
        "arm-a:postgres": "sha256:" + "a" * 64,
        "arm-b:postgres": "sha256:" + "b" * 64,
    }
    d = daemon.Daemon(
        config,
        git_runner=RecordingGit(),
        idle_proxies={"arm-a": FakeIdle(True), "arm-b": FakeIdle(True)},
        clock=FakeClock(),
        log=lambda record: None,
        image_digests=lambda: dict(merged),
    )

    heartbeat = d.poll_once()
    decision = heartbeat["decision"]

    assert set(decision["delta"]["images_unchanged"]) >= set(merged)
    expected = fingerprint(
        manifest.build_manifest(
            eval_env.evals[0], dev_sha, merged, git_runner=manifest.default_git_runner
        )
    )
    assert decision["fingerprints"]["dev"] == expected


def test_instances_route_their_fallback_reads_to_their_own_dsn() -> None:
    """R-I1: each instance's postgres fallback reads its own DSN, not a shared one."""
    seen: list[str] = []

    def http(url):  # the API is unreachable, so the fallback applies
        raise OSError("app-state down")

    def dsn_transport(dsn):
        seen.append(dsn)
        return "recon|r1|pid\n" if dsn == "postgresql://a" else ""

    a = daemon.InstanceConfig("arm-a", "http://a", dsn="postgresql://a")
    b = daemon.InstanceConfig("arm-b", "http://b", dsn="postgresql://b")
    proxy_a = daemon.idle_proxy_for(
        a,
        shared_dsn="postgresql://shared",
        http_transport=http,
        dsn_transport=dsn_transport,
    )
    proxy_b = daemon.idle_proxy_for(
        b,
        shared_dsn="postgresql://shared",
        http_transport=http,
        dsn_transport=dsn_transport,
    )

    assert proxy_a.is_idle() is False
    assert proxy_b.is_idle() is True
    assert seen == ["postgresql://a", "postgresql://b"]


def test_an_instance_without_a_dsn_falls_back_to_the_shared_dsn() -> None:
    seen: list[str] = []

    def http(url):
        raise OSError("app-state down")

    def dsn_transport(dsn):
        seen.append(dsn)
        return ""

    instance = daemon.InstanceConfig("arm-a", "http://a")
    proxy = daemon.idle_proxy_for(
        instance,
        shared_dsn="postgresql://shared",
        http_transport=http,
        dsn_transport=dsn_transport,
    )

    assert proxy.is_idle() is True
    assert seen == ["postgresql://shared"]


def test_daemon_builds_a_proxy_per_instance_with_its_own_dsn(monkeypatch) -> None:
    captured: list[tuple[str, str | None]] = []

    class FakeProxy:
        def __init__(self, url, *, dsn=None, **_):
            captured.append((url, dsn))

    monkeypatch.setattr(daemon.app_state, "IdleProxy", FakeProxy)
    config = daemon.DaemonConfig(
        dev_worktree=Path("/dev"),
        eval_worktrees=(Path("/e1"),),
        app_state_url="http://shared",
        heartbeat_path=Path("/hb.json"),
        dsn="postgresql://shared",
        instances=(
            daemon.InstanceConfig("arm-a", "http://a", dsn="postgresql://a"),
            daemon.InstanceConfig("arm-b", "http://b"),
        ),
    )

    daemon.Daemon(config, git_runner=RecordingGit(), image_digests=lambda: dict(DIGESTS))

    assert captured == [
        ("http://a", "postgresql://a"),
        ("http://b", "postgresql://shared"),
    ]


def test_heartbeat_write_is_an_atomic_replace(tmp_path: Path, monkeypatch) -> None:
    import os

    target = tmp_path / "hb" / "heartbeat.json"
    seen: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr("advance.daemon.os.replace", spy)
    daemon.write_heartbeat(target, {"state": "ok"})

    assert seen, "os.replace was not used"
    src, dst = seen[0]
    assert dst == target
    assert src.parent == target.parent
    assert read_heartbeat(target) == {"state": "ok"}
    assert list(target.parent.glob("*.tmp")) == []


def test_last_known_good_is_recorded_before_each_advance(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    config = make_config(eval_env, tmp_path)
    d, _records, _recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True, config=config)
    e0 = eval_env.head(eval_env.evals[0])

    d1 = eval_env.advance_dev("v1\n")
    d.poll_once()
    assert daemon.last_known_good_shas(config.last_known_good_file) == [e0]

    d2 = eval_env.advance_dev("v2\n")
    d.poll_once()
    assert daemon.last_known_good_shas(config.last_known_good_file) == [e0, d1]
    assert d1 != d2


# --- rewind ------------------------------------------------------------------


def test_rewind_requires_explicit_confirmation(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    config = make_config(eval_env, tmp_path)
    recorder = RecordingGit()
    e0 = eval_env.head(eval_env.evals[0])

    with pytest.raises(daemon.RewindRefused):
        daemon.rewind(config, e0, confirm=False, git_runner=recorder)

    assert "reset" not in recorder.subcommands()


def test_rewind_refuses_a_sha_outside_the_recorded_history(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    config = make_config(eval_env, tmp_path)
    d, _records, _recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True, config=config)
    eval_env.advance_dev("v1\n")
    d.poll_once()

    with pytest.raises(daemon.RewindRefused):
        daemon.rewind(config, "deadbeef", confirm=True)


def test_rewind_moves_eval_back_to_a_recorded_good_sha(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    config = make_config(eval_env, tmp_path)
    d, records, recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True, config=config)
    e0 = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")
    d.poll_once()
    assert eval_env.head(eval_env.evals[0]) != e0

    rewind_recorder = RecordingGit()
    result = daemon.rewind(
        config, e0, confirm=True, git_runner=rewind_recorder, log=records.append
    )

    assert result["rewound_to"] == e0
    assert eval_env.head(eval_env.evals[0]) == e0
    assert "reset" in rewind_recorder.subcommands()
    assert "rewind" in alert_kinds(records) or any(
        r.get("event") == "rewound" for r in records
    )


# --- config and CLI ----------------------------------------------------------


def test_config_loads_required_values_from_the_environment(tmp_path: Path) -> None:
    env = {
        "EVAL_ADVANCE_DEV_WORKTREE": str(tmp_path / "dev"),
        "EVAL_ADVANCE_EVAL_WORKTREES": f"{tmp_path / 'e1'}:{tmp_path / 'e2'}",
        "EVAL_ADVANCE_APP_STATE_URL": "http://agent:8000",
        "EVAL_ADVANCE_DSN": "postgresql://example/db",
        "EVAL_ADVANCE_HEARTBEAT": str(tmp_path / "heartbeat.json"),
        "EVAL_ADVANCE_POLL_INTERVAL": "15",
        "EVAL_ADVANCE_ALERT_COMMAND": "/usr/local/bin/eval-alert",
    }

    config = daemon.load_config_from_env(env)

    assert config.dev_worktree == tmp_path / "dev"
    assert config.eval_worktrees == (tmp_path / "e1", tmp_path / "e2")
    assert config.app_state_url == "http://agent:8000"
    assert config.dsn == "postgresql://example/db"
    assert config.heartbeat_path == tmp_path / "heartbeat.json"
    assert config.poll_interval == 15
    assert config.alert_command == "/usr/local/bin/eval-alert"
    assert config.last_known_good_file == tmp_path / "last-known-good.json"


def test_config_requires_the_dev_worktree_and_eval_worktrees() -> None:
    with pytest.raises(daemon.ConfigError):
        daemon.load_config_from_env({})


def test_config_parses_the_compose_project_and_container_map(tmp_path: Path) -> None:
    env = {
        "EVAL_ADVANCE_DEV_WORKTREE": str(tmp_path / "dev"),
        "EVAL_ADVANCE_EVAL_WORKTREES": str(tmp_path / "e1"),
        "EVAL_ADVANCE_APP_STATE_URL": "http://agent:8000",
        "EVAL_ADVANCE_HEARTBEAT": str(tmp_path / "heartbeat.json"),
        "EVAL_ADVANCE_COMPOSE_PROJECT": "ph-arm-a",
        "EVAL_ADVANCE_IMAGE_CONTAINERS": "postgres=ph-arm-a-postgres-1,kali=ph-arm-a-kali-1",
    }

    config = daemon.load_config_from_env(env)

    assert config.compose_project == "ph-arm-a"
    assert config.image_containers == {
        "postgres": "ph-arm-a-postgres-1",
        "kali": "ph-arm-a-kali-1",
    }
    assert config.image_containers is not None


def test_config_parses_a_multi_instance_list(tmp_path: Path) -> None:
    """I1: `EVAL_ADVANCE_INSTANCES` is a JSON/YAML list, one entry per instance."""
    env = {
        "EVAL_ADVANCE_DEV_WORKTREE": str(tmp_path / "dev"),
        "EVAL_ADVANCE_EVAL_WORKTREES": str(tmp_path / "e1"),
        "EVAL_ADVANCE_HEARTBEAT": str(tmp_path / "heartbeat.json"),
        "EVAL_ADVANCE_INSTANCES": json.dumps(
            [
                {
                    "instance_id": "arm-a",
                    "app_state_url": "http://a",
                    "compose_project": "ph-a",
                    "dsn": "postgresql://a",
                    "image_containers": {"kali": "ph-a-kali-1"},
                },
                {"instance_id": "arm-b", "app_state_url": "http://b"},
            ]
        ),
    }

    config = daemon.load_config_from_env(env)

    assert [i.instance_id for i in config.instances] == ["arm-a", "arm-b"]
    assert config.instances[0].compose_project == "ph-a"
    assert config.instances[0].dsn == "postgresql://a"
    assert config.instances[1].dsn is None
    assert config.instances[0].image_containers == {"kali": "ph-a-kali-1"}
    assert config.instances[1].compose_project is None
    assert config.resolved_instances() == config.instances


def test_legacy_single_instance_env_resolves_to_one_instance(tmp_path: Path) -> None:
    """I1: a config from the legacy single-instance envs resolves to one entry."""
    env = {
        "EVAL_ADVANCE_DEV_WORKTREE": str(tmp_path / "dev"),
        "EVAL_ADVANCE_EVAL_WORKTREES": str(tmp_path / "e1"),
        "EVAL_ADVANCE_APP_STATE_URL": "http://agent:8000",
        "EVAL_ADVANCE_HEARTBEAT": str(tmp_path / "heartbeat.json"),
        "EVAL_ADVANCE_COMPOSE_PROJECT": "ph-arm-a",
    }

    config = daemon.load_config_from_env(env)

    assert config.instances == ()
    (resolved,) = config.resolved_instances()
    assert resolved.app_state_url == "http://agent:8000"
    assert resolved.compose_project == "ph-arm-a"


def test_config_rejects_a_malformed_instance_list(tmp_path: Path) -> None:
    env = {
        "EVAL_ADVANCE_DEV_WORKTREE": str(tmp_path / "dev"),
        "EVAL_ADVANCE_EVAL_WORKTREES": str(tmp_path / "e1"),
        "EVAL_ADVANCE_HEARTBEAT": str(tmp_path / "heartbeat.json"),
        "EVAL_ADVANCE_INSTANCES": json.dumps([{"instance_id": "arm-a"}]),
    }

    with pytest.raises(daemon.ConfigError, match="app_state_url"):
        daemon.load_config_from_env(env)


def test_cli_rewind_without_confirm_exits_nonzero(
    eval_env: EvalEnv, tmp_path: Path, monkeypatch
) -> None:
    config = make_config(eval_env, tmp_path)
    monkeypatch.setattr(daemon, "load_config_from_env", lambda env=None: config)
    e0 = eval_env.head(eval_env.evals[0])

    rc = daemon.main(["rewind", e0])

    assert rc != 0
    assert eval_env.head(eval_env.evals[0]) == e0


def test_alert_sink_runs_the_configured_command(tmp_path: Path) -> None:
    seen: list[list[str]] = []
    sink = daemon.AlertSink(
        command="/usr/local/bin/eval-alert",
        run=lambda args: (seen.append(list(args)), images.CommandResult(0, ""))[1],
        log=lambda record: None,
    )

    sink.emit("non_fast_forward", "eval diverged")

    assert seen and seen[0][0] == "sh"
    assert "/usr/local/bin/eval-alert" in seen[0][2]
    assert "non_fast_forward" in seen[0]


# --- integration: one full poll cycle ---------------------------------------


def test_full_poll_cycle_against_temp_repos_and_fake_app_state(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    eval_wt = eval_env.evals[0]
    write(eval_wt, "base.txt", "workbench edit\n")
    e0 = eval_env.head(eval_wt)
    dev_sha = eval_env.advance_dev("v1\n")
    config = make_config(eval_env, tmp_path)
    d, records, recorder, proxy = make_daemon(eval_env, tmp_path, idle=True, config=config)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_ADVANCED
    assert heartbeat["dev_sha"] == dev_sha
    assert heartbeat["eval_sha"] == dev_sha
    assert heartbeat["idle"] is True
    datetime.fromisoformat(heartbeat["timestamp"])
    assert eval_env.head(eval_wt) == dev_sha
    assert (eval_wt / "base.txt").read_text() == "workbench edit\n"
    assert daemon.last_known_good_shas(config.last_known_good_file) == [e0]
    assert read_heartbeat(config.heartbeat_path) == heartbeat
    assert proxy.calls == 1
    assert "advanced" in [r.get("event") for r in records]
    assert_poll_commands_safe(recorder)


# --- S3: the heartbeat always carries per-worktree observation ----------------


def test_up_to_date_heartbeat_carries_each_worktree_head(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    d, _records, _recorder, _proxy = make_daemon(eval_env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_UP_TO_DATE
    assert heartbeat["worktrees"]
    (entry,) = heartbeat["worktrees"]
    assert entry["path"] == str(eval_env.evals[0])
    assert entry["head"] == eval_env.head(eval_env.evals[0])
    assert entry["at_dev"] is True


def test_skew_heartbeat_carries_each_worktree_actual_head(tmp_path: Path) -> None:
    """S3: STATE_WORKTREE_SKEW must still report every worktree's observed HEAD."""
    env = make_detached_env(tmp_path, n=2)
    env.diverge_eval("eval-only\n")  # evals[0] diverges; evals[1] stays at base
    before = [env.head(worktree) for worktree in env.evals]
    d, records, _recorder, _proxy = make_daemon(env, tmp_path, idle=True)

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_WORKTREE_SKEW
    assert "worktree_skew" in alert_kinds(records)
    by_path = {entry["path"]: entry for entry in heartbeat["worktrees"]}
    assert set(by_path) == {str(worktree) for worktree in env.evals}
    dev_sha = env.head(env.dev)
    for worktree, head in zip(env.evals, before):
        assert by_path[str(worktree)]["head"] == head
        assert by_path[str(worktree)]["at_dev"] is (head == dev_sha)
    # The top-level eval SHA is one of the observed heads, never a guess.
    assert heartbeat["eval_sha"] in before


# --- S4: a decision-input failure alerts and refuses the advance --------------


@dataclass
class LsTreeFailingGit:
    """A git runner whose `ls-tree` fails, so the manifest/decision cannot build."""

    calls: list[tuple[Path, list[str]]] = field(default_factory=list)

    def __call__(self, repo: Path, args) -> images.CommandResult:
        self.calls.append((Path(repo), list(args)))
        if list(args)[:1] == ["ls-tree"]:
            return images.CommandResult(1, "", "fatal: bad object")
        return manifest.default_git_runner(repo, args)

    def subcommands(self) -> list[str]:
        return [args[0] for _repo, args in self.calls]


def test_decision_failure_alerts_and_refuses_the_advance(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    old = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")
    records: list[dict] = []
    runner = LsTreeFailingGit()
    d = daemon.Daemon(
        make_config(eval_env, tmp_path),
        git_runner=runner,
        idle_proxy=FakeIdle(True),
        clock=FakeClock(),
        log=records.append,
        image_digests=lambda: dict(DIGESTS),
    )

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_DECISION_UNKNOWN
    assert eval_env.head(eval_env.evals[0]) == old
    assert "decision_failed" in alert_kinds(records)
    assert "merge" not in runner.subcommands()
    # The advance was refused before the good SHA was recorded.
    assert daemon.last_known_good_shas(
        make_config(eval_env, tmp_path).last_known_good_file
    ) == []


# --- SP4: no silent default stack identity -----------------------------------


def test_config_leaves_compose_project_unset_when_absent(tmp_path: Path) -> None:
    env = {
        "EVAL_ADVANCE_DEV_WORKTREE": str(tmp_path / "dev"),
        "EVAL_ADVANCE_EVAL_WORKTREES": str(tmp_path / "e1"),
        "EVAL_ADVANCE_APP_STATE_URL": "http://agent:8000",
        "EVAL_ADVANCE_HEARTBEAT": str(tmp_path / "heartbeat.json"),
    }

    config = daemon.load_config_from_env(env)

    # No baked-in "polymerhus": an unconfigured stack identity is explicit.
    assert config.compose_project is None


def test_default_image_digests_without_identity_fails_loud() -> None:
    config = daemon.DaemonConfig(
        dev_worktree=Path("/dev"),
        eval_worktrees=(Path("/e1"),),
        app_state_url="http://agent:8000",
        heartbeat_path=Path("/hb.json"),
    )

    provider = daemon.default_image_digests(config)

    with pytest.raises(images.ImageDigestError, match="COMPOSE_PROJECT"):
        provider()


def test_missing_stack_identity_alerts_and_does_not_advance(
    eval_env: EvalEnv, tmp_path: Path
) -> None:
    old = eval_env.head(eval_env.evals[0])
    eval_env.advance_dev("v1\n")
    config = make_config(
        eval_env, tmp_path, compose_project=None, image_containers=None
    )
    records: list[dict] = []
    d = daemon.Daemon(
        config,
        git_runner=RecordingGit(),
        idle_proxy=FakeIdle(True),
        clock=FakeClock(),
        log=records.append,
    )

    heartbeat = d.poll_once()

    assert heartbeat["state"] == daemon.STATE_IMAGE_DIGESTS_UNKNOWN
    assert "image_digests_unknown" in alert_kinds(records)
    assert eval_env.head(eval_env.evals[0]) == old


# --- SP5: the last-known-good history is bounded -----------------------------


def test_last_known_good_history_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "last-known-good.json"
    shas = [f"{index:040x}" for index in range(daemon.MAX_LAST_KNOWN_GOOD + 10)]

    for index, sha in enumerate(shas):
        daemon.record_last_known_good(path, sha, f"t{index}")

    history = daemon.load_last_known_good(path)
    assert len(history) == daemon.MAX_LAST_KNOWN_GOOD
    assert [record["sha"] for record in history] == shas[-daemon.MAX_LAST_KNOWN_GOOD:]
    # The file is a bounded window, not an ever-growing list.
    assert daemon.last_known_good_shas(path)[0] == shas[10]
