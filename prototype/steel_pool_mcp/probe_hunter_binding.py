#!/usr/bin/env python3
"""The hunter's real browser binding against a live MCP server (#359, W8).

This is the local gate for the agent-side wiring: `open_browser_tools` opens
ONE MCP session, loads exactly the three tools, and `invoke_tool` drives them.
The server runs on a local worker, so the whole path - MCP session, lease,
CLI, CDP, capture, stop, release - is real.

    STEEL_CLI=/path/to/steel STEEL_GUARD=$PWD/kali/steel_guard.py \
      python prototype/steel_pool_mcp/probe_hunter_binding.py
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("STEEL_MCP_PORT", "8024"))
URL = f"http://127.0.0.1:{PORT}/mcp"
WORKER_PORT = int(os.environ.get("STEEL_PROBE_WORKER_PORT", "3110"))
WORKER_PORTS = (3110, 3111)
STORE = Path(
    os.environ.get(
        "STEEL_SESSION_STORE",
        f"/tmp/steel-hunter-binding-{uuid.uuid4().hex[:8]}",
    )
)


def _fail(message: str, **details: object) -> None:
    print(json.dumps({"ok": False, "error": message, **details}, indent=2))
    raise SystemExit(1)


def _wait_port() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    _fail("the browser MCP process did not listen", port=PORT)


def _worker_sessions(port: int = WORKER_PORT) -> list:
    import http.client

    connection = http.client.HTTPConnection("localhost", port, timeout=5)
    try:
        connection.request(
            "GET", "/v1/sessions", headers={"Host": f"localhost:{port}"}
        )
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    payload = json.loads(body)
    rows = payload.get("sessions", []) if isinstance(payload, dict) else payload
    sessions = rows if isinstance(rows, list) else []
    return [row for row in sessions if row.get("status") == "live"]


def _live_across_workers() -> list[tuple[int, list]]:
    return [(port, _worker_sessions(port)) for port in WORKER_PORTS]


def _server_env(binary: str, guard: str) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "STEEL_MCP_PORT": str(PORT),
            "STEEL_POOL_DOCKER_SOCKET": os.environ.get(
                "STEEL_POOL_DOCKER_SOCKET",
                str(Path.home() / ".docker" / "run" / "docker.sock"),
            ),
            "STEEL_POOL_LABEL": "polymerhus.steel-pool=true",
            "STEEL_POOL_SIZE": "1",
            "STEEL_POOL_WAIT_S": "20",
            "STEEL_POOL_HEALTH_S": "2",
            "STEEL_HEARTBEAT_S": "120",
            "STEEL_LEASE_TTL_S": "600",
            "STEEL_CLI_TIMEOUT_S": "120",
            "STEEL_SESSION_STORE": str(STORE),
            "STEEL_CLI": binary,
            "STEEL_GUARD": guard,
            "STEEL_TELEMETRY_DISABLED": "1",
            "STEEL_REAL_BINARY_REAL": binary,
        }
    )
    return env


def _tool_payload(result: str) -> dict:
    """The MCP tool result is a content-block list; read its JSON text."""
    import ast

    try:
        blocks = ast.literal_eval(result)
        if isinstance(blocks, list) and blocks and isinstance(blocks[0], dict):
            text = blocks[0].get("text")
            if isinstance(text, str):
                return json.loads(text)
    except (ValueError, SyntaxError):
        pass
    try:
        return json.loads(result)
    except ValueError:
        return {"raw": result}


async def _run_flow() -> dict:
    from polymerhus.attack.hunting.browser_tools import open_browser_tools
    from polymerhus.attack.hunting.hunting_agent import invoke_tool

    async with open_browser_tools(URL) as tools:
        names = sorted(tool.name for tool in tools)
        if names != ["browser_end", "browser_exec", "browser_start"]:
            _fail("the binding did not load the three tools", tools=names)
        by_name = {tool.name: tool for tool in tools}

        started = _tool_payload(
            await invoke_tool(by_name, "browser_start", {"name": "hunter-binding"})
        )
        if not started.get("success") or not started.get("session"):
            _fail("browser_start did not mount a session", result=started)

        navigated = _tool_payload(
            await invoke_tool(
                by_name,
                "browser_exec",
                {"command": "navigate http://localhost:3000/v1/health"},
            )
        )
        if not navigated.get("success"):
            _fail("navigate failed", result=navigated)

        live = _live_across_workers()
        total = sum(len(rows) for _, rows in live)
        if total != 1:
            _fail("the lease does not hold exactly one live session", live=live)

        ended = _tool_payload(await invoke_tool(by_name, "browser_end", {}))
        if not ended.get("success") or not ended.get("ended"):
            _fail("browser_end did not end the session", result=ended)

    record = STORE / "hunter-binding.json"
    if not record.is_file():
        _fail("the end did not save the record", store=str(STORE))
    mode = oct(record.stat().st_mode & 0o777)
    if mode != "0o600":
        _fail("the record mode is not owner-only", mode=mode)
    return {"ok": True, "store": str(STORE), "record_mode": mode}


def main() -> int:
    binary = os.environ.get("STEEL_CLI")
    guard = os.environ.get("STEEL_GUARD", str(ROOT / "kali" / "steel_guard.py"))
    if not binary:
        _fail("STEEL_CLI is required")

    STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
    process = subprocess.Popen(
        [sys.executable, "-m", "kali.browser_mcp_server"],
        cwd=str(ROOT),
        env=_server_env(binary, guard),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_port()
        report = asyncio.run(_run_flow())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - report the failing step
        _fail(f"{type(exc).__name__}: {exc}")
    finally:
        process.terminate()
        try:
            _stdout, _stderr = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
