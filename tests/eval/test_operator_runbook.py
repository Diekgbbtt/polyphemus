"""The operator ground-truth runbook and its container healthcheck.

Two failure modes this pins down, both operator-facing:

- The README's preflight must be runnable from the repository root without
  `cd`-ing the operator's shell into `eval/` and leaving it there (a later
  command in the same runbook block would then resolve against the wrong
  directory). The documented command itself is executed here, and the shell's
  working directory is checked *after* it runs.
- Docker must not report the operator API healthy while its sources are
  unavailable. The endpoint answers 200 with `{"status": "degraded"}` when the
  benchmark checkout cannot be read, so the healthcheck has to parse the body
  and require `status == "ok"` - not merely a 2xx.

The healthcheck is exercised by running the exact `python -c` script the overlay
configures (extracted from the YAML), with only the HTTP call stubbed, because
the test sandbox cannot open a socket.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
OPERATOR_OVERLAY = REPO_ROOT / "eval" / "docker-compose.dashboard.operator.yml"

# The four files the documented startup command must select, in order.
FOUR_COMPOSE_FILES = (
    "-f docker-compose.yml",
    "-f docker-compose.dev.yml",
    "-f eval/docker-compose.dashboard.real.yml",
    "-f eval/docker-compose.dashboard.operator.yml",
)
STARTUP = "up -d --no-deps eval-operator-api eval-dashboard"


# --- markdown / overlay runbook helpers ----------------------------------------


def _joined_shell_command(lines: list[str], needle: str) -> str:
    """The shell command around `needle`, joining its backslash continuations.

    Works for a fenced runbook block and for the overlay's `#` comment header:
    a leading `#` is stripped so both spell the same command.
    """
    index = next(i for i, line in enumerate(lines) if needle in line)
    start = index
    while start > 0 and lines[start - 1].rstrip().endswith("\\"):
        start -= 1
    parts: list[str] = []
    cursor = start
    while cursor < len(lines):
        raw = lines[cursor].strip()
        text = raw[1:].strip() if raw.startswith("#") else raw
        parts.append(text.rstrip("\\").strip())
        if not raw.endswith("\\"):
            break
        cursor += 1
    return " ".join(part for part in parts if part)


def test_readme_operator_startup_selects_only_the_two_services() -> None:
    command = _joined_shell_command(README.read_text(encoding="utf-8").splitlines(), STARTUP)

    for fragment in FOUR_COMPOSE_FILES:
        assert fragment in command, command
    assert "docker compose" in command
    assert STARTUP in command
    # Nothing else may be named: no bare `up -d`, no whole-stack start.
    assert command.count("-f ") == 4, command


def test_operator_overlay_header_documents_the_same_startup_command() -> None:
    command = _joined_shell_command(
        OPERATOR_OVERLAY.read_text(encoding="utf-8").splitlines(), STARTUP
    )

    for fragment in FOUR_COMPOSE_FILES:
        assert fragment in command, command
    assert STARTUP in command


# --- the README preflight keeps the starting directory --------------------------


def test_readme_preflight_runs_from_the_repository_root(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "WebExploitBench"
    checkout.mkdir()
    block = _joined_shell_command(
        README.read_text(encoding="utf-8").splitlines(),
        "python -m operator_api.preflight",
    )
    # The documented invocation resolves the package from the repo root...
    assert "PYTHONPATH=eval" in block, block
    assert block.count("cd ") == 0, block
    command = re.sub(
        r"EVAL_WEB_DIR_HOST_PATH=\S+",
        f"EVAL_WEB_DIR_HOST_PATH={shlex.quote(str(checkout))}",
        block,
    )

    env = dict(os.environ)
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    env.pop("EVAL_WEB_DIR_HOST_PATH", None)
    # Run the documented command, then print the working directory: a `cd` in
    # the command would leave the runbook shell somewhere else.
    result = subprocess.run(
        ["sh", "-c", f"set -e\n{command}\npwd\n"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == str(REPO_ROOT), result.stdout


# --- the container healthcheck --------------------------------------------------


def _operator_healthcheck_command() -> str:
    """The exact `CMD-SHELL` command the overlay configures for the API."""
    overlay = yaml.safe_load(OPERATOR_OVERLAY.read_text(encoding="utf-8"))
    test = overlay["services"]["eval-operator-api"]["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL"
    return test[1]


def _operator_healthcheck_argv() -> list[str]:
    return shlex.split(_operator_healthcheck_command())


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, *args: object) -> bytes:
        return self._payload


def test_operator_healthcheck_shell_invocation_passes_the_script(tmp_path: Path) -> None:
    """Docker runs the healthcheck as `/bin/sh -c "<command>"`; the shell must
    hand `python` exactly the `-c` script the behaviour tests execute."""
    stub = tmp_path / "python"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_FILE"\n', encoding="utf-8")
    stub.chmod(0o755)
    args_file = tmp_path / "args.txt"
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    env["ARGS_FILE"] = str(args_file)

    completed = subprocess.run(
        ["sh", "-c", _operator_healthcheck_command()],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    argv = args_file.read_text(encoding="utf-8").splitlines()
    assert argv == ["-c", _operator_healthcheck_argv()[2]]


def _run_operator_healthcheck(open_url) -> int:
    """Run the configured healthcheck script with only `urlopen` stubbed."""
    argv = _operator_healthcheck_argv()
    assert argv[:2] == ["python", "-c"], argv
    script = argv[2]
    original = urllib.request.urlopen
    urllib.request.urlopen = open_url
    try:
        exec(compile(script, "<operator-healthcheck>", "exec"), {"__name__": "__main__"})
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    except BaseException:  # noqa: BLE001 - an uncaught error is a non-zero exit
        return 1
    finally:
        urllib.request.urlopen = original
    return 0


def test_operator_healthcheck_accepts_only_the_ok_status() -> None:
    assert _run_operator_healthcheck(lambda *a, **k: _FakeResponse(b'{"status": "ok"}')) == 0


def test_operator_healthcheck_fails_when_degraded() -> None:
    rc = _run_operator_healthcheck(
        lambda *a, **k: _FakeResponse(b'{"status": "degraded"}')
    )

    assert rc != 0


def test_operator_healthcheck_fails_on_an_invalid_json_body() -> None:
    rc = _run_operator_healthcheck(lambda *a, **k: _FakeResponse(b"<html>oops</html>"))

    assert rc != 0


def test_operator_healthcheck_fails_on_a_connection_error() -> None:
    def refused(*args: object, **kwargs: object):
        raise urllib.error.URLError("connection refused")

    assert _run_operator_healthcheck(refused) != 0


def test_operator_healthcheck_fails_on_a_non_2xx() -> None:
    def http_error(*args: object, **kwargs: object):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:8091/health", 503, "unavailable", None, None
        )

    assert _run_operator_healthcheck(http_error) != 0
