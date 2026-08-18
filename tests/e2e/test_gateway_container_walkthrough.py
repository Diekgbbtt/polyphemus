"""E1 + E3: the gateway container's boot and cold-stop contracts (#100, #104).

E1 - boot ordering (ADR D10): the entrypoint starts the litellm proxy, polls
`/health/liveliness` until healthy, runs the bootstrap sync, and ONLY THEN
starts the agent uvicorn. Asserted against the RUNNING stack's log lines
(order: proxy-health -> sync -> agent) plus the three live surfaces: the
proxy answers on 127.0.0.1:4000 inside the container, /model/info is
populated (the sync ran), and the agent answers on 8080 from the host.

E3 - D9 cold stop: the entrypoint run in a throwaway container with
`LITELLM_MASTER_KEY` unset boots the proxy, the sync exits HARD (1), the
entrypoint logs "halting before the agent starts" and exits 1 - the agent
uvicorn NEVER starts (no "Uvicorn running on 0.0.0.0:8080" in the run's
output) and the proxy is torn down with the container (no orphan).

E1 needs the stack up (it asserts the state the operator's `docker compose
up -d agent` produced); E3 is self-contained (`docker compose run --rm`).
"""

import time

import pytest

from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j
skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(skip is not None, reason=skip or "agent stack not up for the gateway live tier")


# ---------------------------------------------------------------------------
# E1 - the D10 boot ordering ------------------------------------------------
# ---------------------------------------------------------------------------

def _log_marker_index(logs: str, marker: str) -> int | None:
    for i, line in enumerate(logs.splitlines()):
        if marker in line:
            return i
    return None


def test_e1_boot_orders_proxy_then_sync_then_agent():
    logs = gs.gateway_logs()
    proxy_healthy = _log_marker_index(logs, "gateway proxy healthy after")
    sync_ran = _log_marker_index(logs, "sync complete:")
    agent_started = _log_marker_index(logs, "Uvicorn running on http://0.0.0.0:8080")

    assert proxy_healthy is not None, (
        "the boot log must show the proxy health poll succeeding")
    assert sync_ran is not None, (
        "the boot log must show the bootstrap sync completing")
    assert agent_started is not None, (
        "the boot log must show the agent uvicorn starting")
    assert proxy_healthy < sync_ran < agent_started, (
        "D10 ordering violated: proxy-health at %s, sync at %s, agent at %s "
        "(the agent must start only after the proxy is healthy AND the sync "
        "has run)" % (proxy_healthy, sync_ran, agent_started))


def test_e1_proxy_health_surface_answers_inside():
    status, _ = gs.agent_http_get("/health/liveliness")
    assert status == 200, (
        "the proxy must answer /health/liveliness with 200 inside the container")


def test_e1_model_info_is_populated_by_the_bootstrap_sync():
    registered = gs.model_info()
    assert registered, "the bootstrap sync must have populated /model/info"
    names = {e.get("model_name") for e in registered
             if isinstance(e, dict) and e.get("model_name")}
    assert "__sync_snapshot__" in names, (
        "the bootstrap sync must have written the __sync_snapshot__ record")
    assert any(n != "__sync_snapshot__" for n in names), (
        "the registered set must carry at least one real model")


def test_e1_agent_answers_from_the_host():
    import httpx

    try:
        response = httpx.get("http://127.0.0.1:8080/health", timeout=10)
    except httpx.ConnectError:
        response = None
    assert response is not None, (
        "the agent must answer on the published port 8080 from the host")
    assert response.status_code < 500, (
        "the agent answered HTTP %s - a 5xx on the published port is a "
        "degraded boot" % response.status_code)


# ---------------------------------------------------------------------------
# E3 - the D9 cold stop (throwaway container, LITELLM_MASTER_KEY unset) ------
# ---------------------------------------------------------------------------

def test_e3_hard_sync_collapse_cold_stops_before_agent():
    """Entrypoint with LITELLM_MASTER_KEY unset: proxy boots, sync exits HARD
    (1), the entrypoint logs "halting before the agent starts" and returns 1;
    the agent uvicorn NEVER starts (no "Uvicorn running on 0.0.0.0:8080" in
    the run's output).

    E3 proves ONLY the D9 cold-stop contract (sync hard-collapse -> halt
    before the agent). It does NOT test schema migrations, so the throwaway
    `docker compose run --rm agent` container sets `LITELLM_SKIP_MIGRATIONS`
    to skip `prisma migrate deploy` against the SHARED persistent gateway
    database - whose schema is already applied between tests. Re-running the
    migration there would be pure waste (the prisma CLI cold-starts 110-165 s
    even as a no-op) and it is what previously blew the 240 s test window
    (ADR D10/D1; see gateway_entrypoint.LITELLM_SKIP_MIGRATIONS)."""
    result = gs._run(
        gs.COMPOSE + ["run", "--rm", "-e", "LITELLM_SKIP_MIGRATIONS=1",
                      "agent", "sh", "-c",
                      "env -u LITELLM_MASTER_KEY python -m "
                      "polymerhus.app.gateway_entrypoint; echo EXIT=$?"],
        timeout=240,
    )
    output = result.stdout + result.stderr
    assert "halting before the agent starts" in output, (
        "the entrypoint must log the D9 cold stop reason:\n" + output[-2000:])
    assert "EXIT=1" in output, (
        "the entrypoint must exit 1 after a hard sync collapse:\n"
        + output[-2000:])
    assert "Uvicorn running on http://0.0.0.0:8080" not in output, (
        "the agent must NOT start after a hard collapse:\n" + output[-2000:])
