"""Sibling-agent stack helpers for the hunting e2e tier (candidates-rewrite).

The hunt-orchestrator walkthroughs must be exercised at production runtime
state - the same stack the agent uses (postgres pgvector/pg16, neo4j
5.26-community, the polymerhus-agent image). This module shells the compose
CLI from the host like ``tests/e2e/gateway_stack.py`` does for the gateway,
but for the hunting module: the neo4j+postgres sibling containers and the
agent container. Tests run in two modes:

- In-network (``docker compose -f docker-compose.yml -f docker-compose.dev.yml
  run --rm tests pytest ...``): the tests service resolves ``bolt://neo4j:7687``
  and ``postgresql://polymerhus:polymerhus@postgres:5432/polymerhus`` via
  service DNS, exactly as the agent does. No host fallback needed.
- From the host (``pytest tests/e2e/...``): the helper tries ``docker compose
  up -d neo4j postgres``, waits via ``tests.conftest.wait_for`` and
  ``neo4j_target()``, and skips gracefully with a clear message when the
  daemon is unreachable.

The pattern mirrors ``docker-compose.yml`` / ``docker-compose.dev.yml``:
services ``agent`` (image ``polymerhus-agent:latest``, build context ``.``),
``postgres`` (pgvector/pg16), ``neo4j`` (5.26-community), plus the ``tests``
service (image ``polymerhus-agent:latest``, profiles [test], volumes ``.:/srv``,
env ``NEO4J_URI bolt://neo4j:7687`` etc). The repo's ``tests/conftest.py``
``neo4j_target()`` and ``wait_for`` are reused - no second source of truth.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]


def _run(cmd: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout)


def docker_daemon_reachable() -> bool:
    """True when the Docker daemon answers ``docker images``."""
    try:
        result = _run(["docker", "images", "--format", "{{.Repository}}"], timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def docker_compose_available() -> bool:
    """True when the compose CLI is present and the daemon is reachable."""
    if not docker_daemon_reachable():
        return False
    try:
        result = _run(COMPOSE + ["version"], timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def compose_up_neo4j_postgres(timeout: int = 90) -> bool:
    """Bring up neo4j and postgres via compose, return True when healthy."""
    if not docker_compose_available():
        return False
    try:
        _run(COMPOSE + ["up", "-d", "neo4j", "postgres"], timeout=60)
    except Exception:
        return False
    return True


def neo4j_reachable_via_target() -> bool:
    """True when ``neo4j_target()`` verifies connectivity (host or in-network)."""
    try:
        from tests.conftest import neo4j_target, wait_for
        from neo4j import GraphDatabase

        def _driver():
            uri, auth = neo4j_target()
            d = GraphDatabase.driver(uri, auth=auth)
            d.verify_connectivity()
            return d

        wait_for(_driver, timeout=60)
        return True
    except Exception:
        return False


def postgres_reachable() -> bool:
    """True when POSTGRES_DSN connects (host or in-network)."""
    try:
        from tests.conftest import pg_live_dsn
        return pg_live_dsn() is not None
    except Exception:
        return False


def hunting_stack_skip_reason() -> str | None:
    """Reason the hunting e2e tier must skip, or None to run."""
    if not docker_daemon_reachable():
        return (
            "sibling container not reachable - hunting e2e blocked "
            "(Docker daemon not running: Cannot connect to the Docker daemon)"
        )
    if not neo4j_reachable_via_target():
        return (
            "sibling container not reachable - hunting e2e blocked "
            "(neo4j not reachable via neo4j_target())"
        )
    return None


def hunting_pg_skip_reason() -> str | None:
    """Reason the PG-dependent walkthrough must skip, or None to run."""
    if not docker_daemon_reachable():
        return (
            "sibling container not reachable - hunting e2e blocked "
            "(Docker daemon not running - PG walkthrough needs live postgres)"
        )
    if not postgres_reachable():
        return (
            "sibling container not reachable - hunting e2e blocked "
            "(postgres not reachable - hunting_runs walkthrough needs live PG)"
        )
    return None


def ensure_hunting_stack(timeout: int = 90) -> str | None:
    """Ensure neo4j+postgres are up; return skip reason or None."""
    # In-network the tests service already depends on healthy neo4j+postgres,
    # so this is a no-op that returns None quickly.
    if os.environ.get("NEO4J_URI", "").startswith("bolt://neo4j:"):
        # In-network: check direct reachability without trying compose up
        if neo4j_reachable_via_target():
            return None
    # Host path: try compose up then wait
    if not docker_daemon_reachable():
        return hunting_stack_skip_reason()
    compose_up_neo4j_postgres(timeout=timeout)
    if neo4j_reachable_via_target():
        return None
    return hunting_stack_skip_reason()


def is_in_compose_network() -> bool:
    """True when running inside the compose tests service network."""
    return os.environ.get("NEO4J_URI", "") == "bolt://neo4j:7687"
