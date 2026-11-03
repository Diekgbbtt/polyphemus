import asyncio, subprocess
from fastmcp import Client
from tests.conftest import wait_for

MCP_URL = "http://localhost:8000/mcp"

async def _call(command, session_id):
    async with Client(MCP_URL) as c:
        res = await c.call_tool("execute_command", {"command": command, "session_id": session_id})
        return res.data

def test_execute_command_roundtrip_isolation_and_tools():
    subprocess.run(["docker", "compose", "up", "-d", "kali"], check=True)
    wait_for(lambda: asyncio.run(_call("echo hi", "smoke")), timeout=480)
    out = asyncio.run(_call("echo hello", "run1-pod1"))
    assert out["returncode"] == 0 and out["stdout"].strip() == "hello"
    asyncio.run(_call("echo data > f.txt", "run1-pod1"))
    assert asyncio.run(_call("cat f.txt", "run1-pod2"))["returncode"] != 0
    tools = asyncio.run(_call("command -v puredns massdns kr graphql-cop whois", "toolcheck"))
    assert tools["returncode"] == 0, tools["stdout"] + tools["stderr"]
