"""daemon.py - the advancement-plane daemon and its operator CLI.

The daemon is the mechanical half of D34: it compares the `dev` and `eval`
HEADs, fast-forwards every eval worktree to `dev` only inside an all-idle
window (the app-state proxy, D26), stashes leaked tracked edits and pops them
across the move (D25), records the last-known-good `eval` SHA before moving
(D38), writes a heartbeat every poll, and alerts on a non-fast-forward (R13).
It computes the #266 stack manifest and decision input after a successful
advance and emits it for the orchestrator (D42); it never decides an alignment
action.

The three-way separation is structural, not conventional. The polling path
issues only `rev-parse`, `status`, `merge-base --is-ancestor`, `stash push`,
`merge --ff-only`, and `stash pop`; it never fetches, commits, merges (except
`--ff-only`), checks out another branch, resets, or rewinds. `rewind` is a
separate operator-only function that the `Daemon` object holds no reference to,
and it refuses a SHA outside the recorded last-known-good history.

Config comes from the environment (see `eval/advance/systemd/`), so the systemd
unit and a manual run share one surface. Every collaborator - git, the idle
proxy, the clock, the alert sink, the image-digest provider, the log - is
injected; importing this module performs no I/O.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from advance import app_state, decision as decision_input, manifest
from advance.images import CommandResult

# --- states ------------------------------------------------------------------

STATE_UP_TO_DATE = "up_to_date"
STATE_ADVANCED = "advanced"
STATE_BUSY = "busy"
STATE_NON_FAST_FORWARD = "non_fast_forward"
STATE_WORKTREE_SKEW = "worktree_skew"
STATE_IDLE_UNKNOWN = "idle_unknown"
STATE_POP_CONFLICT = "pop_conflict"
STATE_ERROR = "error"


class ConfigError(RuntimeError):
    """A required advancement-daemon setting is absent."""


class GitError(RuntimeError):
    """A git command the daemon depends on failed."""


class RewindRefused(RuntimeError):
    """Rewind was requested without confirmation or outside the recorded history."""


GitRunner = Callable[[Path, Sequence[str]], CommandResult]
Clock = Callable[[], datetime]
LogFn = Callable[[dict], None]
ImageDigests = Callable[[], Mapping[str, str]]
_LAST_KNOWN_GOOD_FILENAME = "last-known-good.json"


@dataclass(frozen=True)
class DaemonConfig:
    """The daemon's whole configuration surface (env-mapped in the unit file)."""

    dev_worktree: Path
    eval_worktrees: tuple[Path, ...]
    app_state_url: str
    heartbeat_path: Path
    poll_interval: float = 30.0
    dsn: str | None = None
    alert_command: str | None = None
    dev_ahead_message: str = "dev is ahead while all instances are idle"
    last_known_good_path: Path | None = None

    @property
    def last_known_good_file(self) -> Path:
        """The recorded-good history: an explicit path, else beside the heartbeat."""
        if self.last_known_good_path is not None:
            return self.last_known_good_path
        return self.heartbeat_path.parent / _LAST_KNOWN_GOOD_FILENAME


# --- structured log and alert sink -------------------------------------------


def default_log(record: dict) -> None:
    """Emit one structured JSON line; alert records are logged at ERROR."""
    level = logging.ERROR if "alert" in record else logging.INFO
    logging.getLogger("eval.advance").log(level, json.dumps(record, default=str))


def default_shell_runner(args: Sequence[str]) -> CommandResult:
    proc = subprocess.run(args, capture_output=True, text=True)
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


@dataclass
class AlertSink:
    """The configurable alert surface: a structured log line plus an optional hook.

    The log line is always emitted. When `command` is set it is run as
    `sh -c <command> eval-advance <kind> <message>` (the kind and message land
    in `$1`/`$2`). No threshold or notification policy is invented here; the
    only repeating message is the configurable "dev ahead while idle" one.
    """

    command: str | None = None
    run: Callable[[Sequence[str]], CommandResult] = default_shell_runner
    log: LogFn = default_log

    def emit(self, kind: str, message: str = "", **fields: object) -> None:
        record = {"alert": kind, "message": message or kind, **fields}
        self.log(record)
        if not self.command:
            return
        result = self.run(["sh", "-c", self.command, "eval-advance", kind, message or kind])
        if result.returncode != 0:
            self.log(
                {
                    "alert": "alert_command_failed",
                    "message": f"alert hook exited {result.returncode}",
                    "exit_code": result.returncode,
                    "stderr": result.stderr.strip(),
                }
            )


# --- last-known-good ---------------------------------------------------------


def load_last_known_good(path: Path) -> list[dict]:
    """The recorded-good history (oldest first); absent or corrupt means empty."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    history = payload.get("history") if isinstance(payload, dict) else None
    return list(history) if isinstance(history, list) else []


def last_known_good_shas(path: Path) -> list[str]:
    return [record.get("sha") for record in load_last_known_good(path) if record.get("sha")]


def record_last_known_good(path: Path, sha: str, recorded_at: str) -> None:
    """Append `sha` to the good history atomically before the next move.

    Consecutive duplicates are collapsed, so replaying an advance does not grow
    the file. A write failure propagates: the caller must not move `eval`
    without a recorded fallback (D38).
    """
    history = load_last_known_good(path)
    if not history or history[-1].get("sha") != sha:
        history.append({"sha": sha, "recorded_at": recorded_at})
    _atomic_write_json(path, {"history": history})


# --- atomic file writes ------------------------------------------------------


def _atomic_write_json(path: Path, payload: object) -> None:
    """Write `payload` as JSON via a same-directory temp file and `os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_heartbeat(path: Path, record: Mapping[str, object]) -> None:
    """Atomically write one heartbeat record."""
    _atomic_write_json(path, dict(record))


# --- git helpers (read HEADs, check ancestry, stash/pop, ff) -----------------


def git_read_head(repo: Path, git_runner: GitRunner) -> str:
    result = git_runner(repo, ["rev-parse", "HEAD"])
    if result.returncode != 0:
        raise GitError(f"git rev-parse HEAD failed in {repo}: {result.stderr.strip()}")
    return result.stdout.strip()


def git_is_ancestor(
    repo: Path, ancestor: str, descendant: str, git_runner: GitRunner
) -> bool:
    """True when `ancestor` is reachable from `descendant` (a fast-forward is safe)."""
    result = git_runner(repo, ["merge-base", "--is-ancestor", ancestor, descendant])
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise GitError(
        f"git merge-base --is-ancestor failed in {repo}: {result.stderr.strip()}"
    )


def git_has_tracked_edits(repo: Path, git_runner: GitRunner) -> bool:
    """True when tracked files are modified/staged; untracked files do not count."""
    result = git_runner(repo, ["status", "--porcelain", "--untracked-files=no"])
    if result.returncode != 0:
        raise GitError(f"git status failed in {repo}: {result.stderr.strip()}")
    return bool(result.stdout.strip())


def git_stash_push(repo: Path, message: str, git_runner: GitRunner) -> None:
    result = git_runner(repo, ["stash", "push", "-m", message])
    if result.returncode != 0:
        raise GitError(f"git stash push failed in {repo}: {result.stderr.strip()}")


def git_stash_pop(repo: Path, git_runner: GitRunner) -> CommandResult:
    return git_runner(repo, ["stash", "pop"])


def git_ff_only(repo: Path, target: str, git_runner: GitRunner) -> CommandResult:
    return git_runner(repo, ["merge", "--ff-only", target])


# --- the daemon --------------------------------------------------------------


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


class Daemon:
    """The polling advance daemon. Construct, then call `poll_once` per tick."""

    def __init__(
        self,
        config: DaemonConfig,
        *,
        git_runner: GitRunner = manifest.default_git_runner,
        idle_proxy: object | None = None,
        clock: Clock = _default_clock,
        log: LogFn = default_log,
        alert_command: str | None = None,
        alert_runner: Callable[[Sequence[str]], CommandResult] = default_shell_runner,
        image_digests: ImageDigests | None = None,
    ) -> None:
        self.config = config
        self._git = git_runner
        self._clock = clock
        self._log = log
        self._idle_proxy = idle_proxy or app_state.IdleProxy(
            config.app_state_url, dsn=config.dsn, log=log
        )
        self._alerts = AlertSink(
            command=alert_command if alert_command is not None else config.alert_command,
            run=alert_runner,
            log=log,
        )
        self._image_digests = image_digests or dict

    # public ---------------------------------------------------------------

    def poll_once(self) -> dict:
        """One poll: observe, gate, advance if allowed, write the heartbeat."""
        now = self._clock().isoformat()
        previous = self._read_previous_heartbeat()
        last_advance_at = previous.get("last_advance_at")
        last_error: str | None = None
        decision: dict | None = None
        dev_sha = ""
        eval_sha = ""
        idle: bool | None = None
        state = STATE_UP_TO_DATE

        try:
            dev_sha = git_read_head(self.config.dev_worktree, self._git)
            heads = [git_read_head(w, self._git) for w in self.config.eval_worktrees]
            eval_sha = heads[0]
        except GitError as exc:
            return self._finish(
                now, "", "", None, STATE_ERROR, str(exc), last_advance_at, None
            )

        if len(set(heads)) > 1:
            # D36: environment-wide, no per-instance skew. Never guess which
            # worktree is authoritative.
            self._alerts.emit(
                "worktree_skew",
                "eval worktrees are not at the same commit",
                eval_heads=heads,
            )
            return self._finish(
                now, dev_sha, eval_sha, None, STATE_WORKTREE_SKEW, None,
                last_advance_at, None,
            )

        idle = self._idle()
        if dev_sha == eval_sha:
            self._log({"event": STATE_UP_TO_DATE, "eval_sha": eval_sha})
            return self._finish(
                now, dev_sha, eval_sha, idle, STATE_UP_TO_DATE, None,
                last_advance_at, None,
            )

        if not self._is_ancestor(eval_sha, dev_sha):
            self._alerts.emit(
                "non_fast_forward",
                "eval is not an ancestor of dev; refusing to move (no reset)",
                dev_sha=dev_sha,
                eval_sha=eval_sha,
            )
            return self._finish(
                now, dev_sha, eval_sha, idle, STATE_NON_FAST_FORWARD,
                "eval is not an ancestor of dev", last_advance_at, None,
            )

        if idle is None:
            self._alerts.emit(
                "idle_unknown",
                "idle state is unavailable; refusing to advance",
                dev_sha=dev_sha,
                eval_sha=eval_sha,
            )
            return self._finish(
                now, dev_sha, eval_sha, None, STATE_IDLE_UNKNOWN,
                "idle state unavailable", last_advance_at, None,
            )

        if not idle:
            self._log(
                {"event": STATE_BUSY, "dev_sha": dev_sha, "eval_sha": eval_sha}
            )
            return self._finish(
                now, dev_sha, eval_sha, False, STATE_BUSY, None, last_advance_at, None
            )

        self._alerts.emit(
            "dev_ahead_idle",
            self.config.dev_ahead_message,
            dev_sha=dev_sha,
            eval_sha=eval_sha,
        )
        state, last_error, decision, last_advance_at = self._advance(
            now, eval_sha, dev_sha, last_advance_at
        )
        # An advance moved every worktree to dev; a partial move is reported as
        # an error with the original head, so the heartbeat never claims a
        # commit that was not reached.
        current_eval = dev_sha if state in (STATE_ADVANCED, STATE_POP_CONFLICT) else eval_sha
        return self._finish(
            now, dev_sha, current_eval, True, state, last_error, last_advance_at, decision
        )

    def run_forever(self) -> None:
        """Poll until interrupted; a failing poll never kills the loop."""
        while True:
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 - the loop must survive a tick
                self._log({"event": "poll_failed", "error": str(exc)})
            time.sleep(self.config.poll_interval)

    # internal -------------------------------------------------------------

    def _idle(self) -> bool | None:
        try:
            return bool(self._idle_proxy.fetch().idle)
        except app_state.AppStateUnavailable as exc:
            self._log({"event": "idle_unavailable", "error": str(exc)})
            return None

    def _is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """An ancestry-check failure is an error, not a fast-forward."""
        try:
            return git_is_ancestor(
                self.config.eval_worktrees[0], ancestor, descendant, self._git
            )
        except GitError as exc:
            self._alerts.emit("ancestry_check_failed", str(exc), ancestor=ancestor)
            return False

    def _advance(
        self, now: str, eval_sha: str, dev_sha: str, last_advance_at: str | None
    ) -> tuple[str, str | None, dict | None, str | None]:
        try:
            record_last_known_good(self.config.last_known_good_file, eval_sha, now)
        except OSError as exc:
            self._alerts.emit("last_known_good_failed", str(exc), eval_sha=eval_sha)
            return STATE_ERROR, f"last-known-good write failed: {exc}", None, last_advance_at

        stashed: list[Path] = []
        try:
            for worktree in self.config.eval_worktrees:
                if git_has_tracked_edits(worktree, self._git):
                    git_stash_push(worktree, f"eval-advance {now}", self._git)
                    stashed.append(worktree)
            for worktree in self.config.eval_worktrees:
                result = git_ff_only(worktree, dev_sha, self._git)
                if result.returncode != 0:
                    raise GitError(
                        f"git merge --ff-only failed in {worktree}: {result.stderr.strip()}"
                    )
        except GitError as exc:
            for worktree in reversed(stashed):
                self._pop(worktree, alert=False)
            self._alerts.emit("advance_failed", str(exc), eval_sha=eval_sha, dev_sha=dev_sha)
            return STATE_ERROR, str(exc), None, last_advance_at

        conflict = False
        for worktree in reversed(stashed):
            if not self._pop(worktree, alert=True):
                conflict = True

        decision = self._decision(eval_sha, dev_sha)
        last_advance_at = now
        if conflict:
            return STATE_POP_CONFLICT, "stash pop conflict", decision, last_advance_at
        self._log(
            {
                "event": STATE_ADVANCED,
                "dev_sha": dev_sha,
                "eval_sha": eval_sha,
                "decision": decision,
            }
        )
        return STATE_ADVANCED, None, decision, last_advance_at

    def _pop(self, worktree: Path, *, alert: bool) -> bool:
        result = git_stash_pop(worktree, self._git)
        if result.returncode == 0:
            return True
        if alert:
            self._alerts.emit(
                "pop_conflict",
                f"stash pop conflicted in {worktree}; stash retained, no auto-resolve",
                worktree=str(worktree),
                stderr=result.stderr.strip(),
            )
        return False

    def _decision(self, eval_sha: str, dev_sha: str) -> dict | None:
        try:
            digests = self._image_digests()
            repo = self.config.eval_worktrees[0]
            before = manifest.build_manifest(repo, eval_sha, digests, git_runner=self._git)
            after = manifest.build_manifest(repo, dev_sha, digests, git_runner=self._git)
            built = decision_input.build_decision_input(
                dev_sha, eval_sha, True, manifest_dev=after, manifest_eval=before
            )
            return json.loads(json.dumps(asdict(built)))
        except Exception as exc:  # noqa: BLE001 - a diff failure must not undo the move
            self._log({"event": "decision_failed", "error": str(exc)})
            return None

    def _read_previous_heartbeat(self) -> dict:
        path = self.config.heartbeat_path
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _finish(
        self,
        timestamp: str,
        dev_sha: str,
        eval_sha: str,
        idle: bool | None,
        state: str,
        last_error: str | None,
        last_advance_at: str | None,
        decision: dict | None,
    ) -> dict:
        record = {
            "timestamp": timestamp,
            "dev_sha": dev_sha,
            "eval_sha": eval_sha,
            "idle": idle,
            "state": state,
            "last_error": last_error,
            "last_advance_at": last_advance_at,
            "decision": decision,
        }
        write_heartbeat(self.config.heartbeat_path, record)
        return record


# --- operator rewind (never reachable from the polling path) -----------------


def rewind(
    config: DaemonConfig,
    sha: str,
    *,
    confirm: bool,
    git_runner: GitRunner = manifest.default_git_runner,
    log: LogFn = default_log,
    clock: Clock = _default_clock,
) -> dict:
    """Operator-only rollback to a recorded last-known-good SHA.

    Requires an explicit confirmation flag and a SHA present in the recorded
    history; anything else is refused. Logs loudly and moves every eval
    worktree back with `reset --hard` (a rewind cannot be a fast-forward).
    The `Daemon` object holds no reference to this function, so the polling
    loop is structurally incapable of calling it.
    """
    if not confirm:
        raise RewindRefused(
            f"rewind to {sha} refused: pass the explicit confirmation flag"
        )
    if sha not in last_known_good_shas(config.last_known_good_file):
        raise RewindRefused(
            f"rewind to {sha} refused: not in the recorded last-known-good history"
        )
    for worktree in config.eval_worktrees:
        result = git_runner(worktree, ["reset", "--hard", sha])
        if result.returncode != 0:
            raise GitError(f"git reset --hard failed in {worktree}: {result.stderr.strip()}")
    record = {"event": "rewound", "rewound_to": sha, "at": clock().isoformat()}
    log(record)
    logging.getLogger("eval.advance").error(
        "OPERATOR REWIND: eval moved back to %s", sha
    )
    return {"rewound_to": sha, "event": "rewound"}


# --- config from the environment ---------------------------------------------


def load_config_from_env(env: Mapping[str, str] | None = None) -> DaemonConfig:
    """Build the config from `EVAL_ADVANCE_*` environment variables.

    The systemd unit sources these from `EnvironmentFile=`, so a manual run
    and the unit share one documented surface.
    """
    env = os.environ if env is None else env
    required = {
        "EVAL_ADVANCE_DEV_WORKTREE": env.get("EVAL_ADVANCE_DEV_WORKTREE"),
        "EVAL_ADVANCE_EVAL_WORKTREES": env.get("EVAL_ADVANCE_EVAL_WORKTREES"),
        "EVAL_ADVANCE_APP_STATE_URL": env.get("EVAL_ADVANCE_APP_STATE_URL"),
        "EVAL_ADVANCE_HEARTBEAT": env.get("EVAL_ADVANCE_HEARTBEAT"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ConfigError(
            "missing required advancement-daemon environment: " + ", ".join(missing)
        )
    worktrees = tuple(
        Path(part)
        for part in (required["EVAL_ADVANCE_EVAL_WORKTREES"] or "").split(os.pathsep)
        if part
    )
    if not worktrees:
        raise ConfigError("EVAL_ADVANCE_EVAL_WORKTREES is empty")
    interval_raw = env.get("EVAL_ADVANCE_POLL_INTERVAL", "30")
    try:
        interval = float(interval_raw)
    except ValueError as exc:
        raise ConfigError(f"EVAL_ADVANCE_POLL_INTERVAL is not a number: {interval_raw!r}") from exc
    return DaemonConfig(
        dev_worktree=Path(required["EVAL_ADVANCE_DEV_WORKTREE"] or ""),
        eval_worktrees=worktrees,
        app_state_url=required["EVAL_ADVANCE_APP_STATE_URL"] or "",
        heartbeat_path=Path(required["EVAL_ADVANCE_HEARTBEAT"] or ""),
        poll_interval=interval,
        dsn=env.get("EVAL_ADVANCE_DSN") or None,
        alert_command=env.get("EVAL_ADVANCE_ALERT_COMMAND") or None,
        dev_ahead_message=env.get(
            "EVAL_ADVANCE_DEV_AHEAD_MESSAGE",
            "dev is ahead while all instances are idle",
        ),
        last_known_good_path=(
            Path(env["EVAL_ADVANCE_LAST_KNOWN_GOOD"])
            if env.get("EVAL_ADVANCE_LAST_KNOWN_GOOD")
            else None
        ),
    )


# --- CLI ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="advance.daemon",
        description="The eval advancement daemon (D34): fast-forward eval to dev when idle.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="poll forever (or once with --once)")
    run.add_argument(
        "--once", action="store_true", help="run a single poll and exit (cron/tests)"
    )

    rewind_cmd = sub.add_parser(
        "rewind", help="operator-only rollback to a recorded last-known-good SHA"
    )
    rewind_cmd.add_argument("sha", help="the recorded eval SHA to move back to")
    rewind_cmd.add_argument(
        "--confirm",
        action="store_true",
        help="required explicit confirmation; without it the rewind is refused",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_config_from_env()
    except ConfigError as exc:
        print(f"advance.daemon: {exc}", file=sys.stderr)
        return 2

    if args.command == "rewind":
        try:
            rewind(config, args.sha, confirm=args.confirm)
        except (RewindRefused, GitError) as exc:
            print(f"advance.daemon: {exc}", file=sys.stderr)
            return 2
        return 0

    daemon = Daemon(config)
    if args.once:
        daemon.poll_once()
        return 0
    daemon.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
