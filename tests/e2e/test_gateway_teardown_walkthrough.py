"""E2: SIGTERM tears BOTH ASGI processes down - no orphans (#100, #104).

The ADR D1 forward constraint: the entrypoint propagates SIGTERM/SIGINT to
BOTH children (the litellm proxy and the agent uvicorn), waits up to 10 s for
them to drain, then exits 128+SIGTERM. No orphaned process may survive on
either port.

The test stops the agent service (`docker compose stop agent` - SIGTERM to
the entrypoint), asserts the Exited (143) state and the absence of surviving
litellm/uvicorn processes for the gateway ports, then brings the service back
up in a finalizer so the rest of the tier (and the operator's stack) is left
running.

Destructive by design: it runs LAST in the tier's orchestration. The
finalizer restores the running stack, so the module is safe to re-run.
"""

import subprocess
import time

import pytest

from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j
skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(skip is not None, reason=skip or "agent stack not up for the gateway live tier")

# The two ASGI children the entrypoint must tear down (ADR D1): the litellm
# proxy process and the agent uvicorn. pgrep matches the command line.
_CHILD_PATTERNS = ("litellm", "uvicorn")


def _host_processes_matching() -> list[str]:
    matches: list[str] = []
    for pattern in _CHILD_PATTERNS:
        result = subprocess.run(
            ["pgrep", "-f", pattern], capture_output=True, text=True, timeout=30)
        for pid in result.stdout.split():
            try:
                cmdline = subprocess.run(
                    ["ps", "-o", "command=", "-p", pid],
                    capture_output=True, text=True, timeout=30).stdout.strip()
            except Exception:  # noqa: BLE001 - a vanished pid is not a survivor
                continue
            if cmdline and ("4000" in cmdline or "8080" in cmdline):
                matches.append(f"{pid}: {cmdline}")
    return matches


def _restore_agent_stack():
    """Bring the agent service back up and wait for its proxy to answer."""
    result = gs._run(gs.COMPOSE + ["up", "-d", "agent"], timeout=600)
    assert result.returncode == 0, f"agent re-up failed:\n{result.stderr}"
    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            status, _ = gs.agent_http_get("/health/liveliness")
            if status == 200:
                return
        except Exception:  # noqa: BLE001 - still booting
            pass
        time.sleep(5)
    raise RuntimeError("the agent stack did not recover after the SIGTERM test")


def test_sigterm_tears_down_both_asgi_processes():
    try:
        result = gs._run(gs.COMPOSE + ["stop", "agent"], timeout=180)
        assert result.returncode == 0, f"docker compose stop failed:\n{result.stderr}"

        # The container must exit 128+SIGTERM (143) - the entrypoint's own
        # signal handler, not a hard kill.
        ps = gs.compose_ps()
        assert ps and ps[0].get("State") == "exited", (
            f"agent container state after stop: {ps}")
        # docker compose ps does not expose the exit code; read it from
        # `docker inspect` via the container id.
        container_id = ps[0].get("ID") or ps[0].get("Id")
        if container_id:
            inspect = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.ExitCode}}", container_id],
                capture_output=True, text=True, timeout=60)
            assert inspect.stdout.strip() == "143", (
                f"expected exit 143 (128+SIGTERM), got {inspect.stdout.strip()} "
                f"({inspect.stderr.strip()})")

        # No orphaned ASGI child may survive (checked 5 s after the stop so a
        # draining process has time to exit on its own).
        time.sleep(5)
        survivors = _host_processes_matching()
        assert not survivors, (
            "orphaned gateway/agent processes survived the SIGTERM:\n"
            + "\n".join(survivors))
    finally:
        _restore_agent_stack()
