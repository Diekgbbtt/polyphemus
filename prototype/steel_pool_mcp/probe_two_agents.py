#!/usr/bin/env python3
"""Two concurrent browser clients through one MCP server (#359, W8).

Prerequisites: two labelled v0.5.5 workers on 127.0.0.1:3110 and :3111, the
0.5.0-preview.6 CLI, and the guard. Start with:

    STEEL_CLI=/path/to/steel STEEL_GUARD=$PWD/kali/steel_guard.py \
      python prototype/steel_pool_mcp/probe_two_agents.py

The probe proves: each MCP session gets its own lease on its own worker, both
streams run concurrently, both ends save an owner-only record, and both
workers settle with no live session.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("STEEL_MCP_PORT", "8023"))
URL = f"http://127.0.0.1:{PORT}/mcp"
WORKER_PORTS = (3110, 3111)
STORE = Path(
    os.environ.get(
        "STEEL_SESSION_STORE",
        f"/tmp/steel-two-agents-{uuid.uuid4().hex[:8]}",
    )
)
TRACE = os.environ.get(
    "KALI_STEEL_TRACE", f"/tmp/steel-two-agents-{uuid.uuid4().hex}.jsonl"
)


def _fail(message: str, **details: object) -> None:
    print(json.dumps({"ok": False, "error": message, **details}, indent=2))
    raise SystemExit(1)


def _worker_sessions(port: int, *, live_only: bool = True) -> list:
    connection = http.client.HTTPConnection("localhost", port, timeout=5)
    try:
        connection.request(
            "GET", "/v1/sessions", headers={"Host": f"localhost:{port}"}
        )
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    if response.status != 200:
        raise RuntimeError(f"worker {port} session list returned {response.status}")
    payload = json.loads(body)
    rows = payload.get("sessions", []) if isinstance(payload, dict) else payload
    sessions = rows if isinstance(rows, list) else []
    if live_only:
        sessions = [row for row in sessions if row.get("status") == "live"]
    return sessions


def _wait_port() -> None:
    deadline = time.monotonic() + 30
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
            "STEEL_POOL_LABEL": "polymerhus.steel-pool=true",
            "STEEL_POOL_SIZE": str(len(WORKER_PORTS)),
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
            "KALI_STEEL_TRACE": TRACE,
        }
    )
    return env


def _summary(result) -> dict:
    return result.data if hasattr(result, "data") else result


async def _one_client(client, name: str, barrier: asyncio.Barrier) -> dict:
    tools = sorted(tool.name for tool in await client.list_tools())
    if tools != ["browser_end", "browser_exec", "browser_start"]:
        _fail("the tool surface is not the three-tool contract", tools=tools)

    started = _summary(await client.call_tool("browser_start", {"name": name}))
    if not started.get("success"):
        _fail(f"{name}: browser_start failed", result=started)

    await barrier.wait()
    live = await asyncio.gather(
        *[asyncio.to_thread(_worker_sessions, port) for port in WORKER_PORTS]
    )
    if sorted(len(rows) for rows in live) != [1, 1]:
        _fail(f"{name}: the two sessions did not land on distinct workers", live=live)

    navigated = _summary(
        await client.call_tool(
            "browser_exec",
            {"command": "navigate http://localhost:3000/v1/health"},
        )
    )
    if not navigated.get("success"):
        _fail(f"{name}: navigate failed", result=navigated)

    url = _summary(await client.call_tool("browser_exec", {"command": "get url"}))
    if "localhost:3000" not in json.dumps(url):
        _fail(f"{name}: get url returned the wrong page", result=url)

    ended = _summary(await client.call_tool("browser_end", {}))
    if not ended.get("success") or not ended.get("ended"):
        _fail(f"{name}: browser_end failed", result=ended)
    return {"name": name, "end": ended}


async def _run_flow() -> dict:
    from fastmcp import Client

    barrier = asyncio.Barrier(2)
    report: dict[str, object] = {"ok": False}
    async with Client(URL) as first, Client(URL) as second:
        clients = await asyncio.gather(
            _one_client(first, "two-a", barrier),
            _one_client(second, "two-b", barrier),
        )
    report["clients"] = clients

    for name in ("two-a", "two-b"):
        record = STORE / f"{name}.json"
        if not record.is_file():
            _fail(f"{name}: the record was not saved", store=str(STORE))
        mode = oct(record.stat().st_mode & 0o777)
        if mode != "0o600":
            _fail(f"{name}: the record mode is not owner-only", mode=mode)

    for port in WORKER_PORTS:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            rows = _worker_sessions(port, live_only=False)
            if not any(row.get("status") == "live" for row in rows) and any(
                row.get("status") == "idle" for row in rows
            ):
                break
            await asyncio.sleep(0.1)
        else:
            _fail(f"worker {port} did not settle", sessions=rows)

    report["ok"] = True
    report["store"] = str(STORE)
    report["records"] = sorted(path.name for path in STORE.glob("*.json"))
    return report


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
            stdout, stderr = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        if process.returncode not in (0, -15):
            report["server_stdout"] = stdout[-2000:]
            report["server_stderr"] = stderr[-4000:]

    report["trace"] = TRACE
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
