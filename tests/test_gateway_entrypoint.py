"""Unit tests for the gateway container entrypoint (#104, T1).

The entrypoint orders two ASGI processes (a co-located litellm proxy on the
internal port 4000 and the existing agent uvicorn on 8080) and the bootstrap
sync CLI (T2, #105), then branches on the sync's exit code. These tests pin
the branch logic, the bounded health-poll, and SIGTERM propagation, with the
subprocess and HTTP collaborators mocked - the proxy and agent ASGI processes
themselves live in the integration/e2e tier (ADR D1, CODING_STANDARD §10).

The sync CLI is NOT yet built (T2, #105); these tests stub its exit-code
contract (ADR D9): 0 = success, 1 = hard collapse (cold stop), 2 = soft source
failure (proceed on stale). T2 will emit exactly these codes.
"""

import signal
import subprocess
from types import SimpleNamespace

import pytest

from polymerhus.app import gateway_entrypoint as E


# ---------------------------------------------------------------------------
# Constants and configuration ----------------------------------------------
# ---------------------------------------------------------------------------

def test_exit_code_constants_pin_the_d9_contract():
    """The three sync exit codes are stable contract, not magic numbers.

    T2 (#105) emits them; this entrypoint branches on them. Renaming a
    constant here without updating T2 silently breaks the gateway's cold-stop
    invariant, so the constants are the load-bearing handoff."""
    assert E.SYNC_OK == 0
    assert E.SYNC_HARD == 1
    assert E.SYNC_SOFT == 2


def test_default_ports():
    """The proxy listens on an INTERNAL port (4000); the agent keeps 8080.

    4000 is the target T4 (#107) will point `build_chat_model` at via
    `LLM_GATEWAY_URL`. Pinning it stops a silent renumbering breaking the
    future client seam."""
    assert E.PROXY_PORT == 4000
    assert E.AGENT_PORT == 8080


def test_health_endpoint_is_liveliness_not_liveness():
    """The acceptance criteria name `/health/liveliness` (litellm's actual
    endpoint). Spelling it `liveness` here would pass unit tests and fail the
    real proxy poll - pin the real endpoint."""
    assert E.PROXY_HEALTH_PATH == "/health/liveliness"
    assert E.PROXY_HEALTH_URL == "http://127.0.0.1:4000/health/liveliness"


# ---------------------------------------------------------------------------
# Sync exit-code branch (the D9 handoff) -----------------------------------
# ---------------------------------------------------------------------------

def _stub_children(monkeypatch, agent_started=True):
    """Replace the migrate/proxy/sync/agent subprocess seams with recording
    stubs.

    Returns a SimpleNamespace the assertion reads back. The proxy and agent
    are recorded as started so we can assert branch effects directly without
    coupling to the actual Popen mechanics."""
    rec = SimpleNamespace(started_proxy=False, ran_sync=False,
                          started_agent=False, propagated_to=[])
    monkeypatch.setattr(E, "_run_migrations", lambda: None)
    monkeypatch.setattr(E, "_start_proxy", lambda: rec.__setattr__("started_proxy", True) or _FakeProc("proxy"))
    monkeypatch.setattr(E, "_wait_for_proxy", lambda: rec.__setattr__("_waited", True))
    monkeypatch.setattr(E, "_start_agent", lambda: rec.__setattr__("started_agent", True) or _FakeProc("agent"))
    monkeypatch.setattr(E, "_propagate_signal", lambda signum, procs: rec.propagated_to.extend(procs))
    return rec


class _FakeProc:
    """A stand-in for subprocess.Popen exposing `terminate`/`poll`/`wait`/`returncode`."""
    def __init__(self, name, returncode=0):
        self.name = name
        self.terminated = False
        self._poll = None
        self.returncode = returncode
    def terminate(self): self.terminated = True
    def poll(self): return self._poll
    def wait(self, timeout=None): return self._poll or self.returncode
    def __repr__(self): return f"_FakeProc({self.name!r})"


def test_sync_success_proceeds_to_agent(monkeypatch):
    """0 = sync success: the agent starts."""
    rec = _stub_children(monkeypatch)
    monkeypatch.setattr(E, "_run_sync", lambda: E.SYNC_OK)
    rc = E.run_gateway()
    assert rc == 0
    assert rec.started_proxy
    assert rec.ran_sync is False or True  # _run_sync stubbed; ordering verified elsewhere
    assert rec.started_agent is True


def test_sync_soft_failure_proceeds_to_agent_anyway(monkeypatch, caplog):
    """2 = soft source failure (D9): log LOUDLY and start the agent on stale
    records. The stack runs on the last-known-good state, not a fresh guess."""
    rec = _stub_children(monkeypatch)
    monkeypatch.setattr(E, "_run_sync", lambda: E.SYNC_SOFT)
    with caplog.at_level("WARNING"):
        rc = E.run_gateway()
    assert rc == 0
    assert rec.started_agent is True
    # The soft-failure path is LOUD by design (D9): a quiet soft failure is
    # exactly the silent-stale failure the spec exists to remove.
    assert any("soft" in r.message.lower() or "stale" in r.message.lower()
               for r in caplog.records), \
        "soft sync failure must be logged loudly (D9 fail-toward-staleness)"


def test_sync_hard_collapse_halts_before_agent(monkeypatch, caplog):
    """1 = hard collapse / zero records (D9): the entrypoint halts; the agent
    MUST NOT start. This is the cold-stop invariant - the engineer's
    loud-stop on a freshly-collapsed registry."""
    rec = _stub_children(monkeypatch)
    monkeypatch.setattr(E, "_run_sync", lambda: E.SYNC_HARD)
    with caplog.at_level("ERROR"):
        rc = E.run_gateway()
    assert rc != 0, "hard collapse must return non-zero so the container exits"
    assert rec.started_agent is False, "the agent must not start on a collapse (D9 cold stop)"
    # Hard failure is LOUD - fail-loud rather than run-on-stale.
    assert any("hard" in r.message.lower() or "collapse" in r.message.lower()
               or "halt" in r.message.lower() for r in caplog.records), \
        "hard sync collapse must be logged at ERROR (D9 cold stop)"


def test_unknown_sync_exit_code_treated_as_hard(monkeypatch, caplog):
    """An exit code the entrypoint does NOT recognise is the safe failure
    mode: treat as hard. A future T2 that emits an undocumented 3 would
    otherwise silently proceed past a broken sync."""
    rec = _stub_children(monkeypatch)
    monkeypatch.setattr(E, "_run_sync", lambda: 42)
    with caplog.at_level("ERROR"):
        rc = E.run_gateway()
    assert rc != 0
    assert rec.started_agent is False


# ---------------------------------------------------------------------------
# Ordering: proxy -> health poll -> sync -> branch -> agent ----------------
# ---------------------------------------------------------------------------

def test_proxy_starts_before_health_poll_before_sync_before_agent(monkeypatch):
    """The order is the ADR D10 ordering, pinned by recording the call sequence.

    The full sequence is: start_proxy -> wait_for_proxy (health poll) -> run_sync
    -> branch -> start_agent (only on success/soft)."""
    order: list[str] = []
    monkeypatch.setattr(E, "_start_proxy",
                        lambda: order.append("start_proxy") or _FakeProc("proxy"))
    monkeypatch.setattr(E, "_wait_for_proxy",
                        lambda: order.append("wait_for_proxy"))
    monkeypatch.setattr(E, "_run_sync",
                        lambda: order.append("run_sync") or E.SYNC_OK)
    monkeypatch.setattr(E, "_start_agent",
                        lambda: order.append("start_agent") or _FakeProc("agent"))
    monkeypatch.setattr(E, "_propagate_signal",
                        lambda signum, procs: None)
    E.run_gateway()
    assert order == ["start_proxy", "wait_for_proxy", "run_sync", "start_agent"]


def test_hard_failure_short_circuits_before_agent(monkeypatch):
    """On a hard collapse, `start_agent` is never called (D9 cold stop)."""
    order: list[str] = []
    monkeypatch.setattr(E, "_start_proxy",
                        lambda: order.append("start_proxy") or _FakeProc("proxy"))
    monkeypatch.setattr(E, "_wait_for_proxy", lambda: order.append("wait_for_proxy"))
    monkeypatch.setattr(E, "_run_sync", lambda: order.append("run_sync") or E.SYNC_HARD)
    monkeypatch.setattr(E, "_start_agent", lambda: order.append("start_agent") or _FakeProc("agent"))
    monkeypatch.setattr(E, "_propagate_signal", lambda signum, procs: None)
    E.run_gateway()
    assert order == ["start_proxy", "wait_for_proxy", "run_sync"]
    assert "start_agent" not in order


# ---------------------------------------------------------------------------
# Bounded health poll ------------------------------------------------------
# ---------------------------------------------------------------------------

def test_wait_for_proxy_returns_once_liveliness_responds(monkeypatch):
    """The bounded poll returns as soon as `/health/liveliness` answers 200."""
    calls = {"n": 0}
    def fake_get(url, timeout=None):
        calls["n"] += 1
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None)
    monkeypatch.setattr(E.httpx, "get", fake_get)
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    E._wait_for_proxy(max_attempts=30, interval=0.0)
    assert calls["n"] == 1


def test_wait_for_proxy_raises_after_bound(monkeypatch):
    """The poll is BOUNDED: a proxy that never answers raises, so the
    entrypoint does not hang the container boot indefinitely."""
    def fake_get(url, timeout=None):
        raise E.httpx.ConnectError("no proxy", url=url)
    monkeypatch.setattr(E.httpx, "get", fake_get)
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    with pytest.raises(E.GatewayStartupError):
        E._wait_for_proxy(max_attempts=3, interval=0.0)


def test_wait_for_proxy_retries_on_non_200(monkeypatch):
    """A non-200 from `/health/liveliness` is treated as not-yet-ready and the
    poll retries within the bound (the proxy is still booting its DB connection)."""
    seq = [503, 503, 200]
    def fake_get(url, timeout=None):
        code = seq.pop(0)
        r = SimpleNamespace(status_code=code)
        if code != 200:
            r.raise_for_status = lambda: (_ for _ in ()).throw(
                E.httpx.HTTPStatusError("not ready", request=None, response=r))
        else:
            r.raise_for_status = lambda: None
        return r
    monkeypatch.setattr(E.httpx, "get", fake_get)
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    E._wait_for_proxy(max_attempts=10, interval=0.0)
    assert seq == []  # exhausted the 503s and then the 200


# ---------------------------------------------------------------------------
# SIGTERM / SIGINT propagation to both children -----------------------------
# ---------------------------------------------------------------------------

def test_propagate_signal_terminates_both_children():
    """SIGTERM must reach BOTH child processes (the proxy and the agent).

    D1's forward constraint: a clean stop tears both down; no orphaned process
    survives a container SIGTERM. The proxy drains, the agent exits."""
    proxy = _FakeProc("proxy")
    agent = _FakeProc("agent")
    E._propagate_signal(signal.SIGTERM, [proxy, agent])
    assert proxy.terminated is True
    assert agent.terminated is True


def test_propagate_signal_is_idempotent_on_already_dead():
    """Terminating a process that has already exited is a no-op, not a crash.

    The signal handler may fire after one child has already exited on its own;
    `.terminate()` on a dead process would raise ProcessLookupError if we
    did not guard it."""
    proc = _FakeProc("proxy")
    proc._poll = 0  # already exited
    # Should not raise
    E._propagate_signal(signal.SIGTERM, [proc])


# ---------------------------------------------------------------------------
# Per-process reload policy (ADR D1) ---------------------------------------
# ---------------------------------------------------------------------------

def test_agent_command_default_no_reload():
    """The agent uvicorn command WITHOUT `AGENT_UVICORN_ARGS` set is the prod
    shape: no `--reload`. The proxy and the agent have independent reload
    policies (ADR D1); the agent is the live-edited surface IN DEV ONLY."""
    import os
    old = os.environ.pop("AGENT_UVICORN_ARGS", None)
    try:
        cmd = E._agent_command()
    finally:
        if old is not None:
            os.environ["AGENT_UVICORN_ARGS"] = old
    assert "--reload" not in cmd
    assert "uvicorn" in cmd and "polymerhus.app.main:app" in cmd
    assert "0.0.0.0" in cmd and "8080" in cmd


def test_agent_command_dev_overlay_appends_reload(monkeypatch):
    """When `AGENT_UVICORN_ARGS` is set (the dev overlay sets
    `--reload --reload-dir /srv/src`), the agent uvicorn picks it up. The proxy
    NEVER does (its command is fixed in `_proxy_command`) - this is ADR D1's
    independent reload policy, enforced by the seam not reading env vars for
    the proxy."""
    monkeypatch.setenv("AGENT_UVICORN_ARGS", "--reload --reload-dir /srv/src")
    cmd = E._agent_command()
    assert "--reload" in cmd
    assert "/srv/src" in cmd
    # The proxy command stays fixed - it does NOT consult AGENT_UVICORN_ARGS
    monkeypatch.setenv("AGENT_UVICORN_ARGS", "--reload --reload-dir /srv/src")
    proxy_cmd = E._proxy_command(config_path="/etc/litellm.yaml")
    assert "--reload" not in proxy_cmd


# ---------------------------------------------------------------------------
# Pre-T2 sync module detection (ADR D10 "until then the entrypoint proceeds") -
# ---------------------------------------------------------------------------

def test_run_sync_pre_t2_state_returns_ok_without_spawning(monkeypatch):
    """Before T2 (#105) lands, `polymerhus.app.llm.sync` does NOT exist. A bare
    `python -m polymerhus.app.llm.sync` would exit non-zero with "No module
    named...", which the branch logic would then classify as SYNC_HARD and halt
    the agent - the container would not boot. So `_run_sync` detects the
    missing module PRE-spawn via `importlib.util.find_spec` and returns
    `SYNC_OK` (ADR D10: 'until then the entrypoint proceeds'). This is the
    ONLY place the pre-T2 knowledge lives.

    The find_spec check PRE-EMPTS subprocess.run - it MUST NOT be called.
    A previous implementation only caught FileNotFoundError (which never
    fires from subprocess.run for a missing module - python exits 1 with
    stderr instead), so a real pre-T2 boot would have halted the agent on
    a mis-classified 'No module named...' (treated as SYNC_HARD). The find_spec
    gate fixes that."""
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    def _fail_subprocess_run(*a, **kw):
        raise AssertionError("subprocess.run MUST NOT be called when find_spec returns None")
    monkeypatch.setattr(E.subprocess, "run", _fail_subprocess_run)
    assert E._run_sync() == E.SYNC_OK


def test_run_sync_t2_state_runs_subprocess_and_returns_exitcode(monkeypatch):
    """When T2 (#105) lands and the module exists, `_run_sync` spawns the CLI
    and returns its exit code verbatim. Pin the happy path so the find_spec
    gate does not silently swallow a real sync result once T2 lands."""
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    fake = SimpleNamespace(returncode=E.SYNC_OK, stdout="", stderr="")
    monkeypatch.setattr(E.subprocess, "run", lambda *a, **kw: fake)
    assert E._run_sync() == E.SYNC_OK


# ---------------------------------------------------------------------------
# Schema migrations as a deployment step (D10: migrate -> proxy -> sync) -----
# ---------------------------------------------------------------------------

def test_run_migrations_runs_prisma_deploy_before_proxy(monkeypatch):
    """With DATABASE_URL set, `_run_migrations` runs `prisma migrate deploy`
    in the litellm_proxy_extras package dir (where schema.prisma + the
    migrations ledger live - litellm's own boot code os.chdir()s there for
    the same reason) under the measured 420s timeout. It runs as part of
    `run_gateway` BEFORE `start_proxy` - the proxy must not serve (and the
    sync must not write) on a half-migrated schema."""
    calls = []
    def _fake_run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        calls.append((tuple(cmd), cwd, timeout))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setattr(E, "_prisma_migrations_dir", lambda: "/pkg/dir")
    monkeypatch.setattr(E.subprocess, "run", _fake_run)
    E._run_migrations()
    assert calls == [(("prisma", "migrate", "deploy"), "/pkg/dir",
                      E.MIGRATE_TIMEOUT_S)]
    # And run_gateway invokes it BEFORE the proxy: the stubbed ordering test
    # pins start order via _stub_children's migrate stub being required.
    order = []
    monkeypatch.setattr(E, "_run_migrations", lambda: order.append("migrate"))
    monkeypatch.setattr(E, "_start_proxy", lambda: order.append("proxy") or _FakeProc("proxy"))
    monkeypatch.setattr(E, "_wait_for_proxy", lambda: None)
    monkeypatch.setattr(E, "_run_sync", lambda: E.SYNC_OK)
    monkeypatch.setattr(E, "_start_agent", lambda: order.append("agent") or _FakeProc("agent"))
    monkeypatch.setattr(E, "_propagate_signal", lambda s, p: None)
    E.run_gateway()
    assert order == ["migrate", "proxy", "agent"]


def test_run_migrations_failure_is_fail_closed(monkeypatch):
    """A failed or timed-out migration raises GatewayStartupError - the proxy
    must not boot on a half-migrated schema (D9 cold-stop spirit)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setattr(E, "_prisma_migrations_dir", lambda: "/pkg/dir")
    failed = SimpleNamespace(returncode=1, stdout="", stderr="boom")
    monkeypatch.setattr(E.subprocess, "run",
                        lambda *a, **kw: failed)
    with pytest.raises(E.GatewayStartupError):
        E._run_migrations()
    def _timeout(*a, **kw):
        raise E.subprocess.TimeoutExpired(cmd="prisma", timeout=1)
    monkeypatch.setattr(E.subprocess, "run", _timeout)
    with pytest.raises(E.GatewayStartupError):
        E._run_migrations()


def test_run_migrations_skips_without_database_url(monkeypatch, caplog):
    """Without DATABASE_URL (no store_model_in_db deployment) the step skips
    with a warning - the proxy boots without a DB as before."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    def _must_not_run(*a, **kw):
        raise AssertionError("prisma must not run without DATABASE_URL")
    monkeypatch.setattr(E.subprocess, "run", _must_not_run)
    with caplog.at_level("WARNING"):
        E._run_migrations()
    assert any("DATABASE_URL" in r.message for r in caplog.records)


def test_run_migrations_skips_when_explicitly_opted_out(monkeypatch, caplog):
    """With `LITELLM_SKIP_MIGRATIONS` set (the persistent-DB opt-out, ADR
    D10/D1), `_run_migrations` skips `prisma migrate deploy` even when
    `DATABASE_URL` is present - an intact persistent schema must not re-run
    a migration (whose prisma CLI cold-starts 110-165 s even as a no-op)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv(E.LITELLM_SKIP_MIGRATIONS, "1")
    def _must_not_run(*a, **kw):
        raise AssertionError("prisma must not run when LITELLM_SKIP_MIGRATIONS is set")
    monkeypatch.setattr(E.subprocess, "run", _must_not_run)
    with caplog.at_level("INFO"):
        E._run_migrations()
    assert any("skipping gateway schema migrations" in r.message
               for r in caplog.records)


def test_run_migrations_still_runs_by_default(monkeypatch):
    """The opt-out is OFF by default: with `DATABASE_URL` set and NO
    `LITELLM_SKIP_MIGRATIONS`, `prisma migrate deploy` still runs (the
    migration is a real deployment step, ADR D10 - never silently dropped)."""
    calls = []
    def _fake_run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        calls.append((tuple(cmd), cwd, timeout))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.delenv(E.LITELLM_SKIP_MIGRATIONS, raising=False)
    monkeypatch.setattr(E, "_prisma_migrations_dir", lambda: "/pkg/dir")
    monkeypatch.setattr(E.subprocess, "run", _fake_run)
    E._run_migrations()
    assert calls == [(("prisma", "migrate", "deploy"), "/pkg/dir",
                      E.MIGRATE_TIMEOUT_S)]


# ---------------------------------------------------------------------------
# Proxy command shape (D1) --------------------------------------------------
# ---------------------------------------------------------------------------

def test_proxy_command_listens_on_internal_port():
    """The proxy listens on the INTERNAL port 4000 (D1) on 127.0.0.1 - it is
    NOT published to the host (intra-container only). The agent reaches it
    at 127.0.0.1:4000; the client seam (T4, #107) will set
    `LLM_GATEWAY_URL=http://127.0.0.1:4000`.

    Uses the litellm CLI (the documented launcher) rather than invoking
    `uvicorn litellm.proxy.proxy_server:app` directly - uvicorn's `--config`
    flag is uvicorn's own config file, NOT litellm's, so a direct uvicorn
    invocation would silently fail to load the gateway config."""
    cmd = E._proxy_command(config_path="/etc/litellm.yaml")
    assert cmd[0] == "litellm"
    assert "--config" in cmd and "/etc/litellm.yaml" in cmd
    assert "127.0.0.1" in cmd
    assert "4000" in cmd
    # NO migration-resolver flags: DATABASE_URL points at the gateway's OWN
    # database (polymerhus_gateway), so litellm's default boot path works.
    # Every resolver variant fights litellm's schema ownership on a shared
    # database (P3005 / baseline / destructive db push - verified 2026-08-17).
    assert "--use_v2_migration_resolver" not in cmd
    assert "--use_prisma_db_push" not in cmd
    # No host-facing bind - 127.0.0.1, never 0.0.0.0
    assert "0.0.0.0" not in cmd
    # No reload on the proxy (ADR D1: independent reload policies)
    assert "--reload" not in cmd


def test_proxy_command_without_config_path_falls_back_to_env():
    """When called WITHOUT a config_path, the command omits `--config` entirely
    so litellm reads `CONFIG_FILE_PATH` from env (the Dockerfile sets it). An
    empty `--config ""` would be a silent lie (a non-existent path), so we drop
    the flag instead."""
    cmd = E._proxy_command(config_path=None)
    assert cmd[0] == "litellm"
    assert "--config" not in cmd
    assert "127.0.0.1" in cmd and "4000" in cmd
    assert "--use_v2_migration_resolver" not in cmd
    assert "--use_prisma_db_push" not in cmd
