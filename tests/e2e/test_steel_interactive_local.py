"""Live guard: the pinned CLI's interactive daemon starts against the local
runtime (#395).

E2E tier. The Steel CLI 0.4.4 daemon read the self-hosted API's
`timeout: 0` as an already-expired session, closed its Unix socket on the
first loop iteration, and every `browser start` answered
`Connection reset by peer`. The pin moved to 0.5.0-preview.6, the first
release containing upstream PR #95, which maps `0` to "no expiry".

This test drives the real pinned binary through the daemon: `browser start`
must succeed, and `navigate` must round-trip over the same daemon socket.
It is deliberately NOT gated on `skipif`: a live-tier run without the
endpoint FAILS with a clear message, so a missing deployment can never
masquerade as green coverage.

Run on a host that has the repo stack (kali runs the pinned CLI and reaches
the Steel runtime), for example:

    STEEL_BROWSER_API_URL=http://192.33.91.87:3000/v1 \
    .venv/bin/python -m pytest tests/e2e/test_steel_interactive_local.py -q -s

To drive the CLI somewhere else, set `STEEL_CLI` to a command prefix that
runs the pinned binary (it is split like a shell command):

    STEEL_CLI="docker compose -f eval/docker-compose.eval.yml -p ph-dd131acc exec -T kali steel" \
    STEEL_BROWSER_API_URL=http://192.33.91.87:3000/v1 \
    .venv/bin/python -m pytest tests/e2e/test_steel_interactive_local.py -q -s
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import uuid
from pathlib import Path

import pytest

ENDPOINT_ENV = "STEEL_BROWSER_API_URL"
CLI_ENV = "STEEL_CLI"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLI = (
    "docker compose -f docker-compose.yml -f docker-compose.dev.yml "
    "exec -T kali steel"
)
SESSION_TIMEOUT_MS = 300_000


def _cli() -> list[str]:
    return shlex.split(os.environ.get(CLI_ENV, "") or DEFAULT_CLI)


def _run(args: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        _cli() + args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_pinned_cli_daemon_starts_against_the_local_runtime():
    endpoint = os.environ.get(ENDPOINT_ENV, "").strip()
    if not endpoint:
        pytest.fail(
            f"{ENDPOINT_ENV} is required for the interactive local guard. "
            "Set it to the deployed runtime (the CLI form, "
            "http://<host>:<port>/v1). This live test never skips: a missing "
            "endpoint is a coverage failure."
        )

    name = f"polymerhus-e2e-395-{uuid.uuid4().hex[:8]}"
    options = [
        "--session", name,
        "--local",
        "--api-url", endpoint,
        "--json",
    ]

    start = _run(
        ["browser", "start", *options, "--session-timeout", str(SESSION_TIMEOUT_MS)]
    )
    try:
        assert start.returncode == 0, (
            f"browser start failed (returncode {start.returncode}): "
            f"stdout={start.stdout!r} stderr={start.stderr!r}"
        )
        payload = json.loads(start.stdout)
        assert payload.get("success") is True, payload
        assert payload["data"]["remainingMs"] > 0, payload

        # The daemon socket must still serve after start; 0.4.4 closed it on
        # its first loop iteration, so this command is the failure detector.
        navigate = _run(["browser", "navigate", *options, "about:blank"])
        assert navigate.returncode == 0, (
            f"navigate failed (returncode {navigate.returncode}): "
            f"stdout={navigate.stdout!r} stderr={navigate.stderr!r}"
        )
        assert json.loads(navigate.stdout).get("success") is True, navigate.stdout
    finally:
        _run(["browser", "stop", *options])
