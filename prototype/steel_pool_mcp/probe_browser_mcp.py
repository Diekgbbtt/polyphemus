#!/usr/bin/env python3
"""Live end-to-end probe of the browser MCP server.

It starts the real process against one labelled v0.5.5 worker, connects over
streamable HTTP, and proves the three-tool contract:

* exactly ``browser_start``, ``browser_exec``, ``browser_end``;
* start, navigate, read, and end on the leased worker;
* the worker URL never appears in a tool result;
* a client close without ``browser_end`` releases through the DELETE hook.

Usage:

    STEEL_POOL_DOCKER_SOCKET=~/.docker/run/docker.sock \
    STEEL_CLI=/path/to/steel-0.5.0-preview.6 \
    STEEL_GUARD=$PWD/kali/steel_guard.py \
    STEEL_SESSION_STORE=/tmp/steel-browser-mcp-probe \
    python3 prototype/steel_pool_mcp/probe_browser_mcp.py

The worker must carry the pool label and publish its API on a loopback port.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("STEEL_MCP_PORT", "8003"))
URL = f"http://127.0.0.1:{PORT}/mcp"
WORKER_PORT = int(os.environ.get("STEEL_PROBE_WORKER_PORT", "3110"))
STORE = Path(
    os.environ.get(
        "STEEL_SESSION_STORE",
        f"/tmp/steel-browser-mcp-probe-{uuid.uuid4().hex[:8]}",
    )
)
TRACE = os.environ.get(
    "KALI_STEEL_TRACE", f"/tmp/steel-browser-mcp-probe-{uuid.uuid4().hex}.jsonl"
)


def _fail(message: str, **details: object) -> None:
    print(json.dumps({"ok": False, "error": message, **details}, indent=2))
    raise SystemExit(1)


def _worker_sessions(*, live_only: bool = True) -> list:
    """List the worker's sessions, optionally only those holding a browser.

    The v0.5.5 API keeps one active session and lists its past sessions. Only
    a ``live`` row holds a browser: ``idle`` is the placeholder the API
    installs after an end, and ``released``/``failed`` are finished.
    """
    connection = http.client.HTTPConnection("localhost", WORKER_PORT, timeout=5)
    try:
        connection.request(
            "GET",
            "/v1/sessions",
            headers={"Host": f"localhost:{WORKER_PORT}"},
        )
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    if response.status != 200:
        raise RuntimeError(f"the session list returned {response.status}")
    payload = json.loads(body)
    if isinstance(payload, dict):
        payload = payload.get("sessions") or payload.get("data") or []
    sessions = payload if isinstance(payload, list) else []
    if live_only:
        sessions = [
            session for session in sessions if session.get("status") == "live"
        ]
    return sessions


def _wait_for_port(timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    _fail("the browser MCP process did not listen", port=PORT)


def _server_env(binary: str, guard: str) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "STEEL_MCP_PORT": str(PORT),
            "STEEL_POOL_DOCKER_SOCKET": os.environ.get(
                "STEEL_POOL_DOCKER_SOCKET",
                str(Path.home() / ".docker" / "run" / "docker.sock"),
            ),
            "STEEL_POOL_LABEL": os.environ.get(
                "STEEL_POOL_LABEL", "polymerhus.steel-pool=true"
            ),
            "STEEL_POOL_SIZE": os.environ.get("STEEL_POOL_SIZE", "1"),
            "STEEL_POOL_WAIT_S": os.environ.get("STEEL_POOL_WAIT_S", "10"),
            "STEEL_POOL_HEALTH_S": os.environ.get("STEEL_POOL_HEALTH_S", "2"),
            "STEEL_HEARTBEAT_S": os.environ.get("STEEL_HEARTBEAT_S", "120"),
            "STEEL_LEASE_TTL_S": os.environ.get("STEEL_LEASE_TTL_S", "600"),
            "STEEL_CLI_TIMEOUT_S": os.environ.get("STEEL_CLI_TIMEOUT_S", "120"),
            "STEEL_SESSION_STORE": str(STORE),
            "STEEL_CLI": binary,
            "STEEL_GUARD": guard,
            "STEEL_TELEMETRY_DISABLED": "1",
            "STEEL_REAL_BINARY_REAL": binary,
            "KALI_STEEL_TRACE": TRACE,
        }
    )
    return env


def _wait_settled(timeout_s: float = 20.0) -> None:
    """Wait until the worker holds no live session and has an idle placeholder."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rows = _worker_sessions(live_only=False)
        live = [row for row in rows if row.get("status") == "live"]
        idle = [row for row in rows if row.get("status") == "idle"]
        if not live and idle:
            return
        time.sleep(0.05)


def _summary(result) -> dict:
    return result.data if hasattr(result, "data") else result


def _dump(stage: str) -> None:
    """Print the worker's session list at one step of the flow."""
    try:
        sessions = _worker_sessions(live_only=False)
    except Exception as exc:  # noqa: BLE001 - a dump must never mask the flow
        print(json.dumps({"stage": stage, "error": str(exc)}), flush=True)
        return
    rows = [
        {
            "id": str(session.get("id", ""))[:8],
            "status": session.get("status"),
            "createdAt": session.get("createdAt"),
        }
        for session in sessions
    ]
    print(json.dumps({"stage": stage, "sessions": rows}), flush=True)


async def _run_flow(binary: str, guard: str) -> dict:
    from fastmcp import Client

    report: dict[str, object] = {"ok": False, "store": str(STORE), "trace": TRACE}
    async with Client(URL) as client:
        tools = await client.list_tools()
        names = sorted(tool.name for tool in tools)
        report["tools"] = names
        if names != ["browser_end", "browser_exec", "browser_start"]:
            _fail("the tool surface is not the three-tool contract", tools=names)

        name = f"probe-mcp-{uuid.uuid4().hex[:8]}"
        started = await client.call_tool("browser_start", {"name": name})
        start_body = _summary(started)
        report["start"] = start_body
        if not start_body.get("success"):
            _fail("browser_start failed", result=start_body)
        if "http://" in json.dumps(start_body):
            _fail("browser_start leaked a URL", result=start_body)
        _dump("after_start")

        navigated = _summary(
            await client.call_tool(
                "browser_exec",
                {"command": "navigate http://localhost:3000/v1/health"},
            )
        )
        report["navigate"] = navigated
        if not navigated.get("success"):
            _fail("navigate failed", result=navigated)

        read = _summary(
            await client.call_tool("browser_exec", {"command": "get url"})
        )
        report["url"] = read
        if not read.get("success") or "3000" not in json.dumps(read):
            _fail("get url did not return the page", result=read)

        snapshot = _summary(
            await client.call_tool("browser_exec", {"command": "snapshot -i"})
        )
        report["snapshot_ok"] = bool(snapshot.get("success"))
        if not snapshot.get("success"):
            _fail("snapshot failed", result=snapshot)

        refused = _summary(
            await client.call_tool(
                "browser_exec", {"command": "stop --session other"}
            )
        )
        report["refused_stop"] = refused
        if refused.get("error", {}).get("code") != "invalid_command":
            _fail("a session verb was not refused", result=refused)

        ended = _summary(await client.call_tool("browser_end", {}))
        report["end"] = ended
        if not ended.get("success") or not ended.get("ended"):
            _fail("browser_end failed", result=ended)
        _dump("after_browser_end")

    # The v0.5.5 API keeps one `idle` placeholder session after a release, so
    # liveness means "no session in the live state", not "an empty list".
    live = _worker_sessions()
    report["live_after_end"] = live
    _dump("after_client_close")
    if live:
        _fail("the API session survived browser_end", sessions=live)

    # A client that disappears without browser_end must release through the
    # DELETE hook, not wait for the TTL.
    async with Client(URL) as client:
        name = f"probe-mcp-close-{uuid.uuid4().hex[:8]}"
        started = _summary(
            await client.call_tool("browser_start", {"name": name})
        )
        report["close_start"] = started
        if not started.get("success"):
            _fail("the close-hook start failed", result=started)
        _dump("after_close_start")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and _worker_sessions():
        await asyncio.sleep(0.5)
    _wait_settled()
    report["live_after_close"] = _worker_sessions()
    _dump("after_close_release")
    if report["live_after_close"]:
        _fail(
            "the DELETE hook did not release the session",
            sessions=report["live_after_close"],
        )

    record = STORE / f"{name}.json"
    report["record_saved"] = record.exists()
    if not record.exists():
        _fail("the close hook did not save the session record", record=str(record))
    report["record_mode"] = oct(record.stat().st_mode & 0o777)
    if record.stat().st_mode & 0o077:
        _fail("the session record is not owner-only", record=str(record))
    report["ok"] = True
    return report


def main() -> int:
    binary = os.environ.get("STEEL_CLI", "")
    guard = os.environ.get("STEEL_GUARD", str(ROOT / "kali" / "steel_guard.py"))
    if not binary or not os.access(binary, os.X_OK):
        _fail("STEEL_CLI must name an executable CLI", cli=binary)
    if not os.access(guard, os.X_OK):
        _fail("STEEL_GUARD must name an executable guard", guard=guard)

    STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = _server_env(binary, guard)
    report: dict[str, object] = {"ok": False, "store": str(STORE), "trace": TRACE}
    process = subprocess.Popen(
        [sys.executable, "-m", "kali.browser_mcp_server"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port()
        report = asyncio.run(_run_flow(binary, guard))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - report the failing step
        _fail(f"{type(exc).__name__}: {exc}")
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        stderr = process.stderr.read() if process.stderr else ""
        if stderr:
            report["server_stderr"] = stderr[-4000:]
        events = 0
        try:
            with open(TRACE, encoding="utf-8") as handle:
                events = sum(1 for line in handle if line.strip())
        except OSError:
            pass
        report["guard_events"] = events
        print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
