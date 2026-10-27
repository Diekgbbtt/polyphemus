#!/usr/bin/env python3
"""The Steel binary guard: one enforcement and telemetry point.

The MCP sanitizer validates the command string, but a shell can execute the
same binary through a nested shell, ``env``, ``command``, ``xargs``, a script,
or an absolute path. Parsing the string at the MCP layer cannot see those
invocations. This guard runs as ``STEEL_REAL_BINARY`` behind the deployed
``steel`` wrapper, so every real CLI invocation passes through it regardless
of how the shell composed it.

The guard:

* validates the invocation with the same ``steel_contract`` policy;
* runs the real binary and records the true exit code and output tails;
* appends one JSON event per invocation to ``KALI_STEEL_TRACE``;
* classifies the real result with the same classifier;
* refuses before the real binary when the session is missing, unknown, or a
  ``start`` collides with a live session.

The trace is the reliable channel that stdout suppression, ``|| true``, pipes,
and multi-command shells cannot hide. The MCP layer reads it and turns the
event into the additive error envelope.

No I/O happens at import. The guard is a bounded subprocess wrapper, not a
daemon.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
import time
from typing import Iterable

try:
    from kali.steel_contract import (
        BrowserCommand,
        ContractError,
        classify_result,
        sanitize_steel_command,
    )
    from kali.process_group import run_in_process_group
except ImportError:  # flat deployment beside mcp_server.py
    from steel_contract import (  # type: ignore[no-redef]
        BrowserCommand,
        ContractError,
        classify_result,
        sanitize_steel_command,
    )
    from process_group import run_in_process_group  # type: ignore[no-redef]

DEFAULT_REAL_BINARY = "/opt/localbin/steel-real"
GUARD_ENV = "KALI_STEEL_GUARD"
REAL_ENV = "STEEL_REAL_BINARY_REAL"
TRACE_ENV = "KALI_STEEL_TRACE"
TIMEOUT_ENV = "KALI_STEEL_TIMEOUT_S"
REGISTRY_ENV = "KALI_STEEL_SESSION_REGISTRY"
REGISTRY_TTL_ENV = "KALI_STEEL_SESSION_TTL_S"
DEFAULT_REGISTRY = "/tmp/kali-steel-sessions.json"
DEFAULT_REGISTRY_TTL_S = 86400
CATALOGUE_TIMEOUT_S = 30
_OUTPUT_TAIL = 4000


def resolve_guard_path() -> str | None:
    """Return the guard path when the deployed guard exists.

    The first candidate is the explicit environment override, so a deployment
    can place the guard outside the read-only image. The remaining candidates
    cover the image build and the live eval layout.
    """
    candidates = (
        os.environ.get(GUARD_ENV),
        "/opt/kali/steel_guard.py",
        "/tmp/polymerhus-e2e/kali/steel_guard.py",
        os.path.join(os.path.dirname(__file__), "steel_guard.py"),
    )
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def guard_env(
    base: dict | None = None,
    *,
    trace_path: str | None = None,
    timeout_s: int | None = None,
) -> dict:
    """Build the child environment for a guarded Steel invocation.

    ``STEEL_REAL_BINARY`` is read by the ``steel`` wrapper. The guard reads the
    real binary from ``STEEL_REAL_BINARY_REAL`` and therefore does not recurse.
    """
    env = dict(os.environ if base is None else base)
    guard = resolve_guard_path()
    if guard:
        env["STEEL_REAL_BINARY"] = guard
        env.setdefault(REAL_ENV, DEFAULT_REAL_BINARY)
    if trace_path:
        env[TRACE_ENV] = trace_path
    if timeout_s is not None:
        env[TIMEOUT_ENV] = str(max(1, int(timeout_s) - 1))
    return env


def read_events(trace_path: str | None) -> list[dict]:
    """Read and remove the JSONL trace. Unreadable lines are skipped."""
    if not trace_path:
        return []
    events: list[dict] = []
    try:
        with open(trace_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
    except OSError:
        return []
    finally:
        try:
            os.unlink(trace_path)
        except OSError:
            pass
    return events


def _registry_path() -> str:
    return os.environ.get(REGISTRY_ENV, DEFAULT_REGISTRY)


def _registry_ttl_s() -> int:
    try:
        return max(1, int(os.environ.get(REGISTRY_TTL_ENV, DEFAULT_REGISTRY_TTL_S)))
    except ValueError:
        return DEFAULT_REGISTRY_TTL_S


def _read_registry() -> dict[str, float]:
    path = _registry_path()
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    now = time.time()
    ttl = _registry_ttl_s()
    return {
        str(name): float(seen)
        for name, seen in value.items()
        if isinstance(seen, (int, float)) and now - float(seen) <= ttl
    }


def _write_registry(registry: dict[str, float]) -> None:
    path = _registry_path()
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".steel-sessions-", suffix=".json", dir=directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(registry, handle, ensure_ascii=False, sort_keys=True)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    except OSError:
        # The registry is an identity aid, never a command dependency.
        pass


def record_live_sessions(names: Iterable[str]) -> None:
    """Remember that these names were live, so a later disappearance is not a
    typo. The file is shared by the MCP process and the binary guard."""
    registry = _read_registry()
    now = time.time()
    for name in names:
        if name:
            registry[str(name)] = now
    _write_registry(registry)


def known_session_names() -> set[str]:
    return set(_read_registry())


def session_was_known(name: str) -> bool:
    return name in _read_registry()


def _write_event(trace_path: str | None, event: dict) -> None:
    if not trace_path:
        return
    line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
    try:
        descriptor = os.open(
            trace_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            os.write(descriptor, line.encode("utf-8"))
        finally:
            os.close(descriptor)
    except OSError:
        # Telemetry is fail-open. The guard's stdout/stderr still carry the
        # decision, so a broken trace file never changes command semantics.
        pass


def _tail(text: str, limit: int = _OUTPUT_TAIL) -> str:
    return (text or "")[-limit:]


def _verb_of(argv: Iterable[str]) -> str:
    tokens = list(argv)
    for index, token in enumerate(tokens):
        if os.path.basename(token) == "browser" and index + 1 < len(tokens):
            return tokens[index + 1]
    return ""


def _session_of(parsed: BrowserCommand | ContractError | None) -> str | None:
    return parsed.session if parsed is not None else None


def _deny(
    error: ContractError,
    *,
    argv: list[str],
    trace_path: str | None,
    catalogue: str,
) -> int:
    envelope = error.envelope()
    event = {
        "ts": time.time(),
        "pid": os.getpid(),
        "argv": argv,
        "verb": _verb_of(argv),
        "session": error.session,
        "decision": "deny",
        "returncode": 2,
        "duration_ms": 0,
        "error": envelope["error"],
        "catalogue": catalogue,
    }
    _write_event(trace_path, event)
    sys.stderr.write(json.dumps({"error": envelope["error"]}, ensure_ascii=False))
    sys.stderr.write("\n")
    return 2


def _query_live_sessions(argv: list[str], real_binary: str) -> set[str] | None:
    """Ask the real CLI for the live catalogue.

    ``None`` means "cannot verify". The policy then behaves exactly like the
    MCP sanitizer: it never blocks a valid command because the catalogue is
    temporarily unavailable.
    """
    mode = ["--local"] if ("--local" in argv or os.environ.get("STEEL_BROWSER_API_URL")) else []
    try:
        outcome = run_in_process_group(
            [real_binary, *mode, "browser", "sessions", "--json"],
            shell=False,
            timeout_s=CATALOGUE_TIMEOUT_S,
            text=True,
        )
        data = json.loads(outcome.stdout or "").get("data")
        if not isinstance(data, list):
            return None
        names = {
            str(item["name"])
            for item in data
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        record_live_sessions(names)
        return names
    except Exception:
        return None


def _run_real(
    argv: list[str], real_binary: str, timeout_s: int | None
) -> tuple[str, str, int, int]:
    outcome = run_in_process_group(
        [real_binary, *argv],
        shell=False,
        timeout_s=timeout_s,
        text=True,
    )
    return outcome.stdout, outcome.stderr, outcome.returncode, outcome.duration_ms


def run_guarded(
    argv: list[str],
    *,
    real_binary: str = DEFAULT_REAL_BINARY,
    live_sessions: set[str] | None = None,
    known_sessions: set[str] | None = None,
    trace_path: str | None = None,
    timeout_s: int | None = None,
    catalogue: str = "live",
) -> int:
    """Validate, run, classify, and trace one invocation.

    ``live_sessions`` is injected by the tests and by ``main`` after the
    catalogue query. A caller that passes ``None`` keeps the sanitizer's
    fail-open behaviour for an unverifiable catalogue. ``known_sessions``
    distinguishes a typo from a session that was live and disappeared.
    """
    command = shlex.join(["steel", *argv])
    parsed = sanitize_steel_command(
        command, live_sessions=live_sessions, known_sessions=known_sessions
    )
    if isinstance(parsed, ContractError):
        return _deny(parsed, argv=argv, trace_path=trace_path, catalogue=catalogue)

    stdout, stderr, returncode, duration_ms = _run_real(argv, real_binary, timeout_s)
    result = {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
        "duration_ms": duration_ms,
    }
    classified = classify_result(
        command,
        result,
        session=parsed.session,
        live_sessions=live_sessions,
    )
    event = {
        "ts": time.time(),
        "pid": os.getpid(),
        "argv": argv,
        "verb": parsed.verb,
        "session": parsed.session,
        "decision": "allow",
        "returncode": returncode,
        "duration_ms": duration_ms,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "error": classified.get("error"),
        "warning": classified.get("warning"),
        "catalogue": catalogue if live_sessions is not None else "unavailable",
    }
    _write_event(trace_path, event)
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    return returncode


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    trace_path = os.environ.get(TRACE_ENV)
    real_binary = os.environ.get(REAL_ENV, DEFAULT_REAL_BINARY)
    try:
        timeout_value = os.environ.get(TIMEOUT_ENV)
        timeout_s = int(timeout_value) if timeout_value else None
    except ValueError:
        timeout_s = None

    try:
        command = shlex.join(["steel", *args])
        preliminary = sanitize_steel_command(command, live_sessions=None)
        if isinstance(preliminary, ContractError):
            return _deny(
                preliminary, argv=args, trace_path=trace_path, catalogue="not-queried"
            )
        needs_catalogue = (
            isinstance(preliminary, BrowserCommand)
            and preliminary.verb not in ("", "sessions", "live")
            and not preliminary.verb.startswith("-")
        )
        live_sessions: set[str] | None = None
        catalogue = "not-required"
        if needs_catalogue:
            live_sessions = _query_live_sessions(args, real_binary)
            catalogue = "live" if live_sessions is not None else "unavailable"
        return run_guarded(
            args,
            real_binary=real_binary,
            live_sessions=live_sessions,
            known_sessions=known_session_names(),
            trace_path=trace_path,
            timeout_s=timeout_s,
            catalogue=catalogue,
        )
    except Exception as exc:  # noqa: BLE001 - a guard bug must be visible, not silent
        error = {
            "code": "guard_error",
            "message": f"the Steel guard failed: {type(exc).__name__}: {exc}",
            "retryable": False,
            "fatal": True,
            "recovery": {
                "action": "inspect",
                "reason": "the guard failed before the real CLI ran",
            },
            "suggestion": None,
            "session": {"name": None, "live": None},
            "platform_state": None,
            "canonical_command": None,
        }
        _write_event(
            trace_path,
            {
                "ts": time.time(),
                "pid": os.getpid(),
                "argv": args,
                "verb": _verb_of(args),
                "session": None,
                "decision": "error",
                "returncode": 2,
                "duration_ms": 0,
                "error": error,
                "catalogue": "error",
            },
        )
        sys.stderr.write(json.dumps({"error": error}, ensure_ascii=False) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
