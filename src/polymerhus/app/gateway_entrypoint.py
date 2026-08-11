"""Gateway container entrypoint (#104, T1 - the foundation for #100).

Boots TWO co-located ASGI processes inside the single agent container (ADR
D1, "co-located proxy subprocess"): the existing agent uvicorn
(`polymerhus.app.main:app`, port 8080) and a litellm proxy
(`litellm.proxy.proxy_server:app`) on an internal port (4000). The ordering
is the ADR D10 ordering:

    1. start the litellm proxy ASGI on port 4000
    2. poll `GET /health/liveliness` until ready (bounded retries)
    3. run `python -m polymerhus.app.llm.sync` (T2, #105)
    4. branch on the sync's exit code (D9 cold-stop contract):
         - 0 (success)            -> proceed
         - 2 (soft source fail)   -> log LOUDLY, proceed on stale records
         - 1 (hard collapse)       -> halt, agent must NOT start
         - anything else           -> treated as hard (the safe failure)
    5. start the agent ASGI on port 8080
    6. SIGTERM/SIGINT propagate to BOTH children; the proxy drains, the agent exits

This module is the ONLY place the two processes' lifecycles meet (D1 forward
constraint): the proxy's failure must not take down the agent, and vice versa.
The entrypoint owns ordering and signal propagation, nothing more.

CODING_STANDARD §6 (no I/O at import): importing this module performs no
subprocess spawn and no HTTP call - every collaboration happens inside a
function body with a real default. The unit tier drives the branch logic,
the bounded health poll, and SIGTERM propagation entirely with mocks; the
real ASGI processes live in the integration/e2e tier.
"""

import importlib.util
import logging
import os
import signal
import subprocess
import sys
import time
from typing import Callable, Sequence

import httpx

logger = logging.getLogger(__name__)

# --- The ADR D9 sync exit-code contract (the handoff to T2, #105) ------------
# T2 emits exactly these three codes. The entrypoint branches on them.
#   0 = sync succeeded (or no-op).
#   1 = HARD collapse / zero records -> cold stop, agent must not start (D9).
#   2 = SOFT source failure -> log loud, proceed on stale records (D9).
# These are constants (not magic numbers) because T2 reaching across to match
# them is the load-bearing handoff between this foundation ticket and the sync.
SYNC_OK = 0
SYNC_HARD = 1
SYNC_SOFT = 2

# --- Process topology (ADR D1) -----------------------------------------------
# The proxy listens on an INTERNAL port; the agent keeps 8080 (unchanged).
# 4000 is the target T4 (#107) will point `build_chat_model` at via
# `LLM_GATEWAY_URL` once the routing layer lands.
PROXY_PORT = 4000
AGENT_PORT = 8080

# --- Health surface (ADR D10, acceptance criteria) ---------------------------
# `/health/liveliness` is litellm's real readiness endpoint - NOT `liveness`.
# Spelling it `liveness` here passes unit tests and fails the real proxy poll.
PROXY_HEALTH_PATH = "/health/liveliness"
PROXY_HEALTH_URL = f"http://127.0.0.1:{PROXY_PORT}{PROXY_HEALTH_PATH}"

# --- Bounded poll defaults ---------------------------------------------------
# Tuned for a proxy that must open a postgres connection at boot. The bound is
# finite so a dead proxy never hangs the container; the interval is short so a
# healthy proxy is up within seconds.
DEFAULT_HEALTH_MAX_ATTEMPTS = 60
DEFAULT_HEALTH_INTERVAL_S = 1.0
DEFAULT_HEALTH_TIMEOUT_S = 2.0

# --- Bootstrap sync CLI (T2, #105) -------------------------------------------
# Until T2 lands, the sync CLI does not exist; the entrypoint proceeds when the
# module is absent (D10: "until then the entrypoint proceeds"). When T2 lands it
# emits 0/1/2 per the contract above; the entrypoint branches on the exit code.
SYNC_MODULE = "polymerhus.app.llm.sync"


class GatewayStartupError(RuntimeError):
    """Raised when the gateway proxy fails to become healthy within the bound.

    Carrying a dedicated type (rather than a bare RuntimeError) lets the unit
    tier assert on the failure mode and lets an outer supervisor distinguish a
    gateway-boot failure from a sync collapse."""


def _proxy_command(config_path: str | None = None) -> list[str]:
    """The launcher invocation that brings up the litellm proxy.

    Uses the litellm CLI (`litellm --config <path> --host 127.0.0.1 --port 4000`)
    rather than `uvicorn litellm.proxy.proxy_server:app` directly. The CLI is
    litellm's documented entrypoint: it loads the YAML config correctly,
    applies `store_model_in_db` / `general_settings` / `litellm_settings`,
    and starts the ASGI under the hood. Invoking uvicorn directly with
    `--config` would pass the flag to uvicorn (a uvicorn config file),
    NOT litellm - a silent config-loading failure.

    The proxy is `litellm.proxy.proxy_server:app` (ADR D1) on the internal port
    4000, on the loopback interface only (127.0.0.1, NOT 0.0.0.0) - it is
    intra-container, NOT published to the host. The agent ASGI stays on
    0.0.0.0:8080 (published). The two processes keep INDEPENDENT reload
    policies (ADR D1): the proxy NEVER reloads (its command is fixed here,
    with no `--reload`); the agent keeps `--reload` in the dev overlay via
    `AGENT_UVICORN_ARGS` (see `_agent_command`)."""
    cmd: list[str] = ["litellm", "--config", config_path or "",
                      "--host", "127.0.0.1", "--port", str(PROXY_PORT)]
    if not config_path:
        # No path -> drop the empty `--config ""` (litellm reads
        # `LITELLM_CONFIG_PATH` env var instead; the Dockerfile sets it).
        cmd = ["litellm", "--host", "127.0.0.1", "--port", str(PROXY_PORT)]
    return cmd


def _agent_command() -> list[str]:
    """The uvicorn invocation that brings up the agent ASGI (unchanged from the
    pre-gateway CMD). Kept here so the entrypoint is the single source of the
    agent's process invocation, not the Dockerfile CMD.

    An optional `AGENT_UVICORN_ARGS` env var appends extra uvicorn flags (the
    dev overlay sets `--reload --reload-dir /srv/src` for live edits); absent
    in prod, the agent runs without `--reload`. The proxy NEVER reloads (ADR
    D1: independent reload policies) - its command is fixed in
    `_proxy_command`."""
    cmd: list[str] = ["uvicorn", "polymerhus.app.main:app",
                      "--host", "0.0.0.0", "--port", str(AGENT_PORT)]
    extra = os.environ.get("AGENT_UVICORN_ARGS")
    if extra:
        cmd.extend(extra.split())
    return cmd


def _start_proxy() -> subprocess.Popen:
    """Start the litellm proxy ASGI on port 4000 and return its handle.

    Resolves the config path from `CONFIG_FILE_PATH` if set (litellm's
    documented env var name; the docker image bakes the path, a host run may
    override). The path is forwarded to the `litellm` CLI via `--config`.
    The proxy is started non-blocking so the entrypoint can poll its health
    surface."""
    config_path = os.environ.get("CONFIG_FILE_PATH")
    return subprocess.Popen(_proxy_command(config_path))


def _start_agent() -> subprocess.Popen:
    """Start the agent ASGI on port 8080 and return its handle."""
    return subprocess.Popen(_agent_command())


def _wait_for_proxy(max_attempts: int = DEFAULT_HEALTH_MAX_ATTEMPTS,
                    interval: float = DEFAULT_HEALTH_INTERVAL_S,
                    timeout: float = DEFAULT_HEALTH_TIMEOUT_S,
                    url: str = PROXY_HEALTH_URL) -> None:
    """Poll `GET /health/liveliness` until the proxy is ready (bounded).

    Bound is finite so a dead proxy never hangs the container boot. Each poll
    uses a short connect timeout so a not-yet-listening proxy fails fast
    instead of spending the whole budget on a dead SYN. Raises
    `GatewayStartupError` on exhaustion - the entrypoint must not proceed past
    a proxy that never came up."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = httpx.get(url, timeout=timeout)
            r.raise_for_status()
            logger.info("gateway proxy healthy after %d attempt(s)", attempt)
            return
        except Exception as exc:  # ConnectError, HTTPStatusError, TimeoutException
            last_error = exc
            time.sleep(interval)
    raise GatewayStartupError(
        f"gateway proxy did not become healthy at {url} within {max_attempts} "
        f"attempts ({interval}s apart): {last_error}"
    ) from last_error


def _run_sync() -> int:
    """Run the bootstrap sync CLI once and return its exit code (ADR D9).

    The sync CLI is T2 (#105) - NOT yet built. Until it lands, the module
    `polymerhus.app.llm.sync` does NOT exist; we detect this PRE-spawn via
    `importlib.util.find_spec` and treat the pre-T2 state as `SYNC_OK` so a
    container boot today is identical to a boot with a successful sync (ADR
    D10: "until then the entrypoint proceeds"). This matters because a bare
    `python -m polymerhus.app.llm.sync` on a missing module would exit non-zero
    with "No module named..." - which the branch logic would then classify as
    SYNC_HARD (cold stop) and halt the agent. The find_spec check is the only
    place the "sync not yet built" knowledge lives.

    Once T2 lands, the CLI emits 0 / 1 / 2 per the contract; this function
    returns the exit code verbatim. stdout/stderr are surfaced on failure so
    the cold-stop log carries the cause, not just the exit code."""
    if importlib.util.find_spec(SYNC_MODULE) is None:
        logger.warning(
            "sync module %s not yet available; proceeding (pre-T2, ADR D10)",
            SYNC_MODULE)
        return SYNC_OK
    cmd = ["python", "-m", SYNC_MODULE]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stderr:
        logger.info("sync stderr:\n%s", result.stderr.strip())
    if result.stdout and result.returncode != 0:
        logger.info("sync stdout:\n%s", result.stdout.strip())
    return result.returncode


def _propagate_signal(signum: int, procs: Sequence[subprocess.Popen]) -> None:
    """Propagate a signal to each child process; idempotent on the already-dead.

    `.terminate()` on an exited process raises ProcessLookupError; the entrypoint
    must not crash mid-shutdown because one child died first. A clean stop
    teases BOTH processes down (ADR D1 forward constraint: no orphan)."""
    for p in procs:
        if p.poll() is not None:
            continue
        try:
            p.terminate()
        except ProcessLookupError:
            pass


def run_gateway(*,
                start_proxy: Callable[[], subprocess.Popen] | None = None,
                wait_for_proxy: Callable[..., None] | None = None,
                run_sync: Callable[[], int] | None = None,
                start_agent: Callable[[], subprocess.Popen] | None = None,
                propagate_signal: Callable[[int, Sequence[subprocess.Popen]], None] | None = None) -> int:
    """Bring up the gateway + agent per ADR D10's ordering.

    The five collaborators default to the real subprocess/HTTP seams but are
    injectable so the unit tier drives the branch logic and the signal
    propagation without spawning a single real process. Collaborators are
    resolved LAZILY at call time (not bound as default arguments, which would
    freeze a reference to the original and defeat a test's monkeypatch) - this
    is the codebase's own pattern (`curate` resolves `neo4j_client.merge`
    inside the function body, CODING_STANDARD §6).

    Returns the container's exit code: 0 on a clean run, non-zero on a hard
    sync collapse (the cold stop)."""
    if start_proxy is None: start_proxy = _start_proxy
    if wait_for_proxy is None: wait_for_proxy = _wait_for_proxy
    if run_sync is None: run_sync = _run_sync
    if start_agent is None: start_agent = _start_agent
    if propagate_signal is None: propagate_signal = _propagate_signal
    proxy = start_proxy()
    children: list[subprocess.Popen] = [proxy]

    def _on_signal(signum, _frame):
        logger.info("received signal %s; propagating to %d child process(es)",
                    signum, len(children))
        propagate_signal(signum, children)
        # Give the children a moment to drain, then exit. A hard kill here
        # would defeat the "proxy drains, agent exits" contract.
        for p in children:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        wait_for_proxy()
        exit_code = run_sync()
        if exit_code == SYNC_OK:
            pass  # proceed to agent
        elif exit_code == SYNC_SOFT:
            logger.warning(
                "sync returned SOFT (source failure, exit %d): proceeding on "
                "stale records (ADR D9 fail-toward-staleness); the agent will "
                "start with the last-known-good gateway state", exit_code)
        elif exit_code == SYNC_HARD:
            logger.error(
                "sync returned HARD (collapse, exit %d): halting before the "
                "agent starts (ADR D9 cold stop); the agent must not run on a "
                "freshly-collapsed registry", exit_code)
            return 1
        else:
            logger.error(
                "sync returned UNKNOWN exit code %d: treating as HARD (halt) "
                "- an undocumented exit code is the safe-failure mode, not a "
                "silent proceed", exit_code)
            return 1
        agent = start_agent()
        children.append(agent)
        agent.wait()
        # If the agent exits on its own, propagate that exit code upward.
        return agent.returncode if agent.returncode is not None else 0
    finally:
        # On any exit path (clean agent exit, an exception, the SystemExit from
        # the signal handler), tear the proxy down too. The proxy is a child of
        # the entrypoint; an orphan survives if we don't.
        for p in children:
            if p.poll() is None:
                try:
                    p.terminate()
                except ProcessLookupError:
                    pass


def main() -> int:
    """Container entrypoint: configure logging, then `run_gateway`."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run_gateway()


if __name__ == "__main__":
    raise SystemExit(main())
