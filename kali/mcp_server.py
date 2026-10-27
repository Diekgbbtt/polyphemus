"""FastMCP execution server for the reused Kali image.

Backward-compatible ``execute_command`` (stdout/stderr/returncode/duration_ms)
plus the pinned ``steel_exec`` browser surface (version re-check, wait
ordering, session-name uniqueness, and the mandatory variadic ``--`` boundary,
D19), plus the #196 HTTP-history surface: ``search_http_history``,
``get_http_artifact``, ``replay_http_request`` and ``proxy_status``.

Capture is fail-open: if the namespace lease, proxy or store is unavailable the
command still runs and the result carries a ``capture_warning``. Model-facing
views are sanitized; raw bodies never cross this boundary.
"""
import functools, json, os, re, shlex, subprocess, tempfile, time

import anyio
from fastmcp import FastMCP

try:
    from kali.steel_contract import (
        BrowserCommand,
        ContractError,
        classify_result,
        sanitize_shell_command,
        sanitize_steel_command,
    )
    from kali.steel_guard import (
        guard_env,
        known_session_names,
        read_events,
        record_live_sessions,
    )
except ImportError:  # the deployed flat layout beside mcp_server.py
    from steel_contract import (  # type: ignore[no-redef]
        BrowserCommand,
        ContractError,
        classify_result,
        sanitize_shell_command,
        sanitize_steel_command,
    )
    from steel_guard import (  # type: ignore[no-redef]
        guard_env,
        known_session_names,
        read_events,
        record_live_sessions,
    )

os.environ["PATH"] = ":".join([
    "/opt/localbin", "/root/go/bin", "/opt/venv/bin", "/usr/local/go/bin", os.environ.get("PATH", ""),
])

mcp = FastMCP("kali-exec")


async def _offload(fn, /, *args, **kwargs):
    """Run a blocking implementation in a worker thread.

    Every tool below is ``async def`` for one reason: FastMCP's
    ``FunctionTool.run`` invokes a SYNC tool body directly on the event loop
    (via ``TypeAdapter.validate_python``), so one long ``execute_command``
    (a hanging curl, a slow target) stalls the ENTIRE MCP server for its
    duration and every other session's request queues behind it. An async
    body is awaited instead, so ``anyio.to_thread.run_sync`` moves the
    blocking work off the loop and concurrent requests keep flowing.
    """
    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_STEEL_TOKEN = re.compile(r"\bsteel\b")
# First release containing upstream PR #95 (self-hosted `timeout: 0` means no
# expiry): #395. 0.4.4, the latest stable tag, still carries the defect.
_STEEL_VERSION_PIN = "0.5.0-preview.6"
# Runtime selection belongs to the `steel` wrapper (#395, D359-13). The
# gateway keeps the grammar and lifecycle guards and passes the command text
# through byte-for-byte; it never inserts `--local` or rewrites the URL.
_STEEL_WAIT = re.compile(r"(?<!\S)--timeout[= ]+(\d+)")
_CATALOGUE_TIMEOUT_S = 30
_VERSION_TIMEOUT_S = 15
_SCRIPT_RUNNERS = {"sh": "sh", "py": "python3"}

_SERVICE = None


def _build_service():
    from kali.http_history.dns import DnsForwarder
    from kali.http_history.config import load_config
    from kali.http_history.namespaces import NamespaceLeaseManager, SubprocessBackend
    from kali.http_history.registry import SourceRegistry
    from kali.http_history.service import HttpHistoryService

    config = load_config()
    registry = None
    lease_manager = None
    if config.enabled:
        registry = SourceRegistry(config.registry_path)
        # Leased namespaces cannot reach Docker's resolver (`127.0.0.11` is the
        # CONTAINER's loopback); the forwarder serves it on each lease gateway,
        # so a `curl` replay and any system-resolver client resolve exactly what
        # the container resolves. Started lazily per lease, stopped on release.
        lease_manager = NamespaceLeaseManager(
            registry=registry,
            pool_size=config.pool_size,
            ttl_s=config.ttl_s,
            acquire_timeout_s=config.acquire_timeout_s,
            backend=SubprocessBackend(
                proxy_port=config.proxy_port, dns_forwarder=DnsForwarder()
            ),
        )
    return HttpHistoryService(
        config=config, registry=registry, lease_manager=lease_manager
    )


def _get_service():
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _build_service()
    return _SERVICE


def _sanitize_output(text: str) -> str:
    return _ANSI.sub("", text or "")


def _new_trace(workdir: str) -> str:
    descriptor, path = tempfile.mkstemp(
        prefix="steel-trace-", suffix=".jsonl", dir=workdir
    )
    os.close(descriptor)
    return path


def _compact_event(event: dict) -> dict:
    keys = (
        "verb",
        "session",
        "decision",
        "returncode",
        "duration_ms",
        "error",
        "warning",
        "catalogue",
    )
    return {key: event[key] for key in keys if event.get(key) is not None}


def _apply_steel_events(result: dict, events: list[dict]) -> dict:
    """Merge the binary guard's per-invocation events into a tool result.

    The guard is the only component that sees every real Steel invocation,
    including ones hidden behind nested shells, scripts, pipes, and output
    suppression. Its trace is therefore authoritative for browser-state
    failures. The legacy stdout/stderr/returncode fields stay unchanged.
    """
    if not events:
        return result
    out = dict(result)
    out["steel_events"] = [_compact_event(event) for event in events]
    error = next(
        (
            event["error"]
            for event in events
            if isinstance(event.get("error"), dict) and event["error"].get("code")
        ),
        None,
    )
    if error is not None:
        out["error"] = error
        if not out.get("stderr"):
            out["stderr"] = str(error.get("message") or "")
        if int(out.get("returncode") or 0) == 0:
            out["returncode"] = 2
    else:
        warning = next(
            (
                event["warning"]
                for event in events
                if isinstance(event.get("warning"), dict)
            ),
            None,
        )
        if warning is not None:
            out["warning"] = warning
    return out


def _error_payload(exc: Exception) -> dict:
    import sqlite3

    from kali.http_history.service import (
        BodyUnavailableError,
        CorruptRecordError,
        NotFoundError,
    )

    if isinstance(exc, NotFoundError):
        return {"error": "not_found", "detail": str(exc)}
    if isinstance(exc, BodyUnavailableError):
        return {"error": "body_unavailable", "detail": str(exc)}
    if isinstance(exc, CorruptRecordError):
        return {"error": "corrupt_artifact", "detail": str(exc)}
    if isinstance(exc, ValueError):
        # Caller-input errors: the filter vocabulary, the limit, the cursor,
        # the project guard, the refused include_body. The category tells the
        # model its input is malformed - fix it and retry (FM-C).
        return {"error": "invalid_filter", "detail": str(exc)}
    if isinstance(exc, sqlite3.Error):
        # The store itself was unreachable for THIS call (a lock, a disk, a
        # WAL state) - not evidence about the target. Retry later (FM-C).
        return {"error": "unavailable", "detail": f"{type(exc).__name__}: {exc}"}
    return {"error": "invalid_request", "detail": str(exc)}


async def execute_command(
    command: str,
    session_id: str,
    timeout_s: int = 300,
    project_id: str = "",
    run_id: str = "",
    spec_id: str = "",
    variant_ref: str = "",
    derived_from: str = "",
    replay_kind: str = "",
) -> dict:
    """Run a shell command in /work/{session_id}.

    Returns the legacy {stdout, stderr, returncode, duration_ms} plus exec_id,
    http_artifact_refs and capture_warning. Older callers that pass only
    (command, session_id) keep working unchanged.

    The Steel contract sanitizer runs before the downstream executor when the
    command contains a Steel invocation. An unknown or missing session is
    refused before any process starts. A completed Steel command is classified
    so a shell pipeline cannot turn a browser-state failure into a zero exit.
    """
    live: set[str] | None = None
    steel_commands = ()
    if "steel" in command:
        live = _live_session_names()
        sanitized = sanitize_shell_command(
            command, live_sessions=live,
            known_sessions=known_session_names())
        if isinstance(sanitized, ContractError):
            env = sanitized.envelope()
            env.update({"exec_id": "", "http_artifact_refs": [],
                        "capture_warning": None})
            return env
        steel_commands = sanitized
    try:
        result = await _offload(
            _get_service().execute,
            command,
            session_id,
            timeout_s,
            project_id=project_id,
            run_id=run_id,
            spec_id=spec_id,
            variant_ref=variant_ref,
            derived_from=derived_from,
            replay_kind=replay_kind,
        )
    except Exception as exc:  # noqa: BLE001 - never take the exec server down
        message = f"execute_command failed: {type(exc).__name__}: {exc}"
        return {
            "stdout": "",
            "stderr": message,
            "returncode": 1,
            "duration_ms": 0,
            "exec_id": "",
            "http_artifact_refs": [],
            "capture_warning": f"execution error: {type(exc).__name__}: {exc}",
            "error": {
                "code": "command_failed",
                "message": message,
                "retryable": True,
                "fatal": False,
                "recovery": {
                    "action": "inspect",
                    "reason": "the execution surface raised before returning a result",
                },
                "suggestion": None,
                "session": {"name": None, "live": None},
                "platform_state": None,
                "canonical_command": command,
            },
        }
    result["stdout"] = _sanitize_output(result["stdout"])
    result["stderr"] = _sanitize_output(result["stderr"])
    events = result.pop("steel_events", None) or []
    guard_error = any(
        isinstance(event.get("error"), dict) and event["error"].get("code")
        for event in events
    )
    if steel_commands and not guard_error:
        session = next((item.session for item in steel_commands if item.session), None)
        result = classify_result(command, result, session=session,
                                 live_sessions=live)
    return _apply_steel_events(result, events)


async def search_http_history(
    project_id: str,
    filters: list | None = None,
    cursor: str | None = None,
    limit: int = 50,
    text: str | None = None,
) -> dict:
    """Search recorded HTTP transactions for one project (sanitized rows)."""
    try:
        return await _offload(
            _get_service().search,
            project_id, filters=filters, cursor=cursor, limit=limit, text=text
        )
    except Exception as exc:  # noqa: BLE001
        return _error_payload(exc)


async def get_http_artifact(
    project_id: str, artifact_id: str, include_body: bool = False
) -> dict:
    """Fetch one recorded artifact, sanitized. include_body is refused here."""
    try:
        return await _offload(
            _get_service().get, project_id, artifact_id, include_body=include_body
        )
    except Exception as exc:  # noqa: BLE001
        return _error_payload(exc)


async def replay_http_request(
    project_id: str,
    artifact_id: str,
    overrides: dict | None = None,
    capture_context: dict | None = None,
) -> dict:
    """Replay a recorded request with deterministic, closed-set overrides."""
    from kali.http_history.models import CaptureContext

    try:
        context = (
            CaptureContext(**capture_context) if isinstance(capture_context, dict) else None
        )
        return await _offload(
            _get_service().replay, project_id, artifact_id, overrides or {}, context
        )
    except Exception as exc:  # noqa: BLE001
        return _error_payload(exc)


async def proxy_status() -> dict:
    """Per-component health: MCP, proxy, routing, namespace pool and store."""
    try:
        return await _offload(_get_service().proxy_status)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "mcp": {"ok": True},
            "proxy": {"ok": False, "detail": f"status error: {exc}"},
            "routing": {"ok": False, "detail": f"status error: {exc}"},
            "namespaces": {"ok": False, "detail": f"status error: {exc}"},
            "store": {"ok": False, "detail": f"status error: {exc}"},
            "capture": {"enabled": False},
        }


def _workdir(session_id: str) -> str:
    # KALI_WORKDIR redirects only the root for host-side tests; in-container
    # default is /work, read at call time so import performs no I/O.
    workdir = os.path.join(os.environ.get("KALI_WORKDIR", "/work"), session_id)
    os.makedirs(workdir, exist_ok=True)
    return workdir

def _refused(kind: str, detail: str, *, recovery: dict | None = None) -> dict:
    # Typed refusal: stable refused:<kind> prefix, never raises, never executes.
    return {
        "stdout": "",
        "stderr": f"refused:{kind}: {detail}",
        "returncode": 2,
        "duration_ms": 0,
        "error": {
            "code": kind,
            "message": detail,
            "retryable": False,
            "fatal": False,
            "recovery": recovery,
            "suggestion": None,
            "session": {"name": None, "live": None},
            "platform_state": None,
            "canonical_command": None,
        },
    }

def _run(command: str, session_id: str, timeout_s: int) -> dict:
    # The one exec implementation both tools share: per-session workdir,
    # ANSI-stripped {stdout, stderr, returncode, duration_ms} envelope, plus
    # the binary guard's events when the guard is deployed.
    workdir = _workdir(session_id)
    trace_path = _new_trace(workdir)
    env = guard_env(trace_path=trace_path, timeout_s=timeout_s)
    start = time.time()
    try:
        proc = subprocess.run(command, shell=True, cwd=workdir,
                              capture_output=True, text=True, timeout=timeout_s,
                              env=env)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, (e.stdout or ""), f"timeout after {timeout_s}s"
    finally:
        events = read_events(trace_path)
    result = {"stdout": _ANSI.sub("", out), "stderr": _ANSI.sub("", err),
              "returncode": rc,
              "duration_ms": int((time.time() - start) * 1000)}
    return _apply_steel_events(result, events)

def _live_session_names() -> set[str] | None:
    # The session catalogue (re-probed live 2026-09-16): `steel browser
    # sessions --json` returns every live session this key owns as
    # {id, mode, name, status, viewerUrl}, and `data: []` once none is live -
    # one read answers the name question that used to cost a per-name `live`
    # probe, and it is visible across processes and workdirs (proven by
    # starting through this tool and listing from a separate shell). Fail-open:
    # an error or unparseable shape returns None ("cannot verify"), so a broken
    # catalogue never blocks a start. The check-then-start race is accepted and
    # documented, not solved.
    try:
        proc = subprocess.run(
            "steel browser sessions --json",
            shell=True, capture_output=True, text=True,
            timeout=_CATALOGUE_TIMEOUT_S, env=guard_env())
        data = json.loads(proc.stdout or "").get("data")
        if not isinstance(data, list):
            return None
        names = {s["name"] for s in data
                 if isinstance(s, dict) and isinstance(s.get("name"), str)}
        record_live_sessions(names)
        return names
    except Exception:
        return None


def _steel_version_ok() -> bool:
    # Cheap re-check of the pinned CLI before running: `steel --version`
    # must name the pin. Fail-closed on a proven mismatch; fail-open when
    # the probe itself errors, so a missing binary surfaces as the run's
    # own shell error instead of a version verdict.
    try:
        proc = subprocess.run("steel --version", shell=True, capture_output=True,
                              text=True, timeout=_VERSION_TIMEOUT_S,
                              env=guard_env())
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0 or not out.strip():
            return True
        return _STEEL_VERSION_PIN in out
    except Exception:
        return True


def _steel_waits_s(command: str) -> list[float]:
    # Steel op waits ride `--timeout` in milliseconds (spike: 10000 lands the
    # ~11s timeout path). `--session-timeout` is a session lifetime, not a
    # wait, and the lookbehind keeps it out of the ordering check.
    return [int(v) / 1000 for v in _STEEL_WAIT.findall(command)]

def _run_script(script: str, script_lang: str, session_id: str, timeout_s: int) -> dict:
    # Verbatim write (no templating) to a unique session-workdir file, then run
    # through the shared runner so the envelope stays identical.
    workdir = _workdir(session_id)
    with tempfile.NamedTemporaryFile(mode="w", suffix=f".{script_lang}", prefix="steel_exec_",
                                     dir=workdir, delete=False, encoding="utf-8") as f:
        f.write(script)
    return _run(f"{_SCRIPT_RUNNERS[script_lang]} {shlex.quote(f.name)}", session_id, timeout_s)

def _steel_exec_sync(command: str = "", script: str = "", script_lang: str = "sh",
                     session_id: str = "steel", timeout_s: int = 600) -> dict:
    if bool(command) == bool(script):
        return _refused("ambiguous-input", "pass exactly one of command or script")
    if command:
        if not _STEEL_TOKEN.search(command):
            return _refused("not-steel-command", "command carries no steel token")
        if not _steel_version_ok():
            return _refused("steel-version-mismatch",
                            f"need steel {_STEEL_VERSION_PIN}")
        waits = _steel_waits_s(command)
        if waits and max(waits) >= timeout_s:
            return _refused("timeout-ordering",
                            f"longest steel wait {max(waits)}s needs tool timeout_s above it, got {timeout_s}")
        live = _live_session_names()
        parsed = sanitize_steel_command(
            command, live_sessions=live,
            known_sessions=known_session_names())
        if isinstance(parsed, ContractError):
            return parsed.envelope()
        result = _run(command, session_id, timeout_s)
        return classify_result(command, result, session=parsed.session,
                               live_sessions=live)
    if script_lang not in _SCRIPT_RUNNERS:
        return _refused("unsupported-script-lang", f"want one of {sorted(_SCRIPT_RUNNERS)}")
    if not _steel_version_ok():
        return _refused("steel-version-mismatch",
                        f"need steel {_STEEL_VERSION_PIN}")
    return _run_script(script, script_lang, session_id, timeout_s)


@mcp.tool()
async def steel_exec(command: str = "", script: str = "", script_lang: str = "sh",
                     session_id: str = "steel", timeout_s: int = 600) -> dict:
    """Run a Steel CLI command or automation script in /work/{session_id}.

    The result keeps the legacy {stdout, stderr, returncode, duration_ms}
    envelope and adds a canonical ``error`` object with a recovery directive
    when the command is contextually invalid or a browser-state failure is
    recognized. Exactly one of command/script is accepted.

    Guards, in order: pinned Steel version re-check; longest Steel --timeout
    below timeout_s; the modular contract sanitizer validates the browser
    session before execution; a stale CDP target, missing session, stuck page,
    or unavailable runtime is classified with recovery. The sanitizer does not
    re-implement the CLI grammar and does not rewrite clear CLI errors.

    Scripts carry timeout ordering, unique names, and the boundary by skill
    construction and are never scanned; commands are scanned because they can
    be composed from model-authored shell text.
    """
    return await _offload(_steel_exec_sync, command=command, script=script,
                          script_lang=script_lang, session_id=session_id,
                          timeout_s=timeout_s)


for _fn in (
    execute_command,
    search_http_history,
    get_http_artifact,
    replay_http_request,
    proxy_status,
):
    mcp.tool()(_fn)


if __name__ == "__main__":
    # The eval harness runs a second, isolated server on 8001. The default
    # stays 8000, so the image entrypoint and every existing deployment are
    # unchanged.
    port = int(os.environ.get("KALI_MCP_PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")
