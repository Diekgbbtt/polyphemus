"""Deep e2e — the execution substrate runs a REAL recon tool and returns
structured output. Critical component: kali only (agent/neo4j/postgres omitted)."""
import asyncio, json, subprocess
from fastmcp import Client
from tests.conftest import wait_for

MCP_URL = "http://localhost:8000/mcp"

async def _exec(cmd, sid):
    async with Client(MCP_URL) as c:
        return (await c.call_tool("execute_command", {"command": cmd, "session_id": sid})).data

def test_jsluice_extracts_urls_from_js():
    subprocess.run(["docker", "compose", "up", "-d", "kali"], check=True)
    wait_for(lambda: asyncio.run(_exec("echo up", "warm")), timeout=480)
    # Write a JS file into the session workdir, then run jsluice on it — a real
    # ProjectDiscovery-adjacent tool doing real, deterministic, offline work.
    cmd = (r"""printf 'const api="/api/v1/users";\nfetch("https://ext.example.com/data");\n' """
           r"""> app.js && jsluice urls app.js""")
    out = asyncio.run(_exec(cmd, "e2e-jsluice"))
    assert out["returncode"] == 0, out["stderr"]
    urls = {json.loads(line)["url"] for line in out["stdout"].splitlines() if line.strip()}
    assert "/api/v1/users" in urls, urls
    assert "https://ext.example.com/data" in urls, urls
