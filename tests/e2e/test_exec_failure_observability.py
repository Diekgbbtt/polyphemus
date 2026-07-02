"""Observability e2e — execute_command surfaces failures observably (the recon
triage paths: non-zero exit + stderr, missing binary, and timeout->124), which
were previously untested. Critical component: kali only."""
import asyncio, subprocess
from fastmcp import Client
from tests.conftest import wait_for

MCP_URL = "http://localhost:8000/mcp"

async def _exec(cmd, sid, timeout_s=300):
    async with Client(MCP_URL) as c:
        return (await c.call_tool(
            "execute_command",
            {"command": cmd, "session_id": sid, "timeout_s": timeout_s})).data

def test_exec_surfaces_failures_observably():
    subprocess.run(["docker", "compose", "up", "-d", "kali"], check=True)
    wait_for(lambda: asyncio.run(_exec("echo up", "warm")), timeout=480)

    # non-zero exit carries a diagnosable stderr and a duration metric
    fail = asyncio.run(_exec("ls /nonexistent-path-xyz", "e2e-fail"))
    assert fail["returncode"] != 0
    assert fail["stderr"].strip() != ""
    assert isinstance(fail["duration_ms"], int)

    # missing binary is a non-zero, not a crash
    missing = asyncio.run(_exec("this-binary-does-not-exist-xyz", "e2e-missing"))
    assert missing["returncode"] != 0

    # timeout maps to the documented sentinel 124
    to = asyncio.run(_exec("sleep 5", "e2e-timeout", timeout_s=1))
    assert to["returncode"] == 124
