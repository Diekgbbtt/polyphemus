"""Observability e2e - the system OBSERVES and DIAGNOSES a degraded backend.

Induces a real fault in a DISPOSABLE compose project (stop neo4j), asserts
/health reports degraded and surfaces WHY, then tears the project down.

Why opt-in and disposable (#33)
-------------------------------
This test shells the compose CLI. Left unpinned it resolved the operator's LIVE
`polymerhus` project - `docker-compose.yml` pins `name: polymerhus`, which wins
over a worktree's directory-derived name - so a run from a worktree recreated
the live containers under a partial config: it composed only `docker-compose.yml`,
dropped `docker-compose.dev.yml`, and, with no gitignored `.env` in the worktree,
booted an agent that fail-fast exited. It also ran on a bare `pytest tests/`
(the documented unit command) and, with `--build` and no subprocess bound, could
stall the whole suite.

The test now:
- is gated behind `PH_E2E_LIVE=1` (module-level skip), so a bare unit run never
  collects it;
- pins compose to the repo root resolved from THIS file, with BOTH overlays and
  `--project-directory`, so CWD and a partial config cannot change what runs;
- targets a throwaway project (`polymerhus-e2e-health`, `PH_E2E_HEALTH_PROJECT`),
  so it can never recreate or degrade the operator's `polymerhus` stack;
- bounds every shell-out and carries a pytest-timeout backstop, so a wedged run
  fails instead of hanging.

Precondition: the operator's stack must be DOWN. The base compose fixes the
network subnet (172.28.0.0/16) and publishes the host ports (8080, 5432, 7687,
7474, 8000, 9621); a throwaway project cannot coexist with the live stack. When
the live stack is up, the bring-up fails fast on the port or subnet conflict
rather than mutating it.

Run (against a disposable stack; operator stack down):

    PH_E2E_LIVE=1 .venv/bin/python -m pytest tests/e2e/test_health_degraded.py -q
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pytest

from tests.conftest import wait_for

REPO_ROOT = Path(__file__).resolve().parents[2]

COMPOSE = [
    "docker",
    "compose",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.dev.yml",
    "--project-directory",
    str(REPO_ROOT),
]

PROJECT = os.environ.get("PH_E2E_HEALTH_PROJECT", "polymerhus-e2e-health")
HEALTH = os.environ.get("PH_E2E_HEALTH_URL", "http://localhost:8080/health")

UP_TIMEOUT_S = int(os.environ.get("PH_E2E_HEALTH_UP_TIMEOUT_S", "900"))
CMD_TIMEOUT_S = int(os.environ.get("PH_E2E_HEALTH_CMD_TIMEOUT_S", "120"))
TEST_TIMEOUT_S = UP_TIMEOUT_S + 300

pytestmark = [
    pytest.mark.e2e_live,
    pytest.mark.timeout(TEST_TIMEOUT_S),
]

if os.environ.get("PH_E2E_LIVE") != "1":
    pytest.skip(
        "live e2e; set PH_E2E_LIVE=1 to degrade a disposable docker-compose stack",
        allow_module_level=True,
    )


def _compose(*args: str, timeout: int = CMD_TIMEOUT_S) -> None:
    subprocess.run(
        [*COMPOSE, "-p", PROJECT, *args],
        cwd=REPO_ROOT,
        check=True,
        timeout=timeout,
    )


def _health():
    return httpx.get(HEALTH, timeout=3).json()


def test_health_reports_and_diagnoses_degraded_backend():
    _compose("up", "-d", "--build", timeout=UP_TIMEOUT_S)
    wait_for(lambda: _health() if _health()["status"] == "ok" else None, timeout=600)
    _compose("stop", "neo4j")
    try:
        body = wait_for(lambda: _health() if _health()["status"] == "degraded" else None,
                        timeout=60)
        assert body["checks"]["neo4j"] is False           # the fault is observed
        assert body["checks"]["postgres"] is True          # siblings unaffected
        assert body["errors"].get("neo4j"), "degraded backend must surface WHY"  # diagnosable
    finally:
        # Tear the throwaway project down completely (containers + project-scoped
        # volumes); never touch the operator's `polymerhus` project.
        subprocess.run(
            [*COMPOSE, "-p", PROJECT, "down", "-v", "--remove-orphans"],
            cwd=REPO_ROOT,
            timeout=CMD_TIMEOUT_S,
        )
