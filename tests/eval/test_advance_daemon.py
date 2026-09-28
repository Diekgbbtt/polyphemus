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
    git(root, "worktree", "add", "-q", "-b", "eval", str(eval_wt), "dev")
    return EvalEnv(root=root, dev=dev, evals=(eval_wt,))


@dataclass
class RecordingGit:
    calls: list[tuple[Path, list[str]]] = field(default_factory=list)

    def __call__(self, repo: Path, args) -> images.CommandResult:
        self.calls.append((Path(repo), list(args)))
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
        image_digests=lambda: dict(DIGESTS),
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
    git(eval_env.root, "worktree", "add", "-q", "-b", "eval-2", str(second), "dev")
    env = EvalEnv(root=eval_env.root, dev=eval_env.dev, evals=eval_env.evals + (second,))
    dev_sha = env.advance_dev("v1\n")
    d, _records, _recorder, _proxy = make_daemon(env, tmp_path, idle=True)

    d.poll_once()

    assert env.head(second) == dev_sha
    assert env.head(env.evals[0]) == dev_sha


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


# --- heartbeat and last-known-good ------------------------------------------


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

    # A later no-op poll keeps the last advance timestamp.
    third = d.poll_once()
    assert third["state"] == daemon.STATE_UP_TO_DATE
    assert third["last_advance_at"] == second["last_advance_at"]


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
