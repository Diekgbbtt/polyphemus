"""Mint the White Jotter pool state through the browser MCP (E2E setup).

The gateway's observable act is: mount the stable key, put the authenticated
cookie into the browser, prove the oracle, and end (capture + save). This
script performs that act; the phase runner then mounts the same key and proves
the crawl restores it.
"""
from __future__ import annotations

import asyncio
import json
import shlex

from fastmcp import Client

ORACLE = (
    "(async()=>{const r=await fetch(\"/api/authentication\","
    "{redirect:\"follow\",credentials:\"include\",cache:\"no-store\"});"
    "const t=await r.text();return JSON.stringify({status:r.status,"
    "redirected:r.redirected,url:r.url,body:t.slice(0,200)})})()"
)


async def main() -> int:
    config = json.loads(open("/tmp/wj-gateway.json", encoding="utf-8").read())
    async with Client("http://127.0.0.1:8003/mcp") as client:
        started = await client.call_tool(
            "browser_start", {"name": config["name"]}
        )
        print("START", json.dumps(started.data))
        navigated = await client.call_tool(
            "browser_exec",
            {"command": "navigate http://t-1618c524.target/"},
        )
        print("NAV", json.dumps(navigated.data)[:300])
        cookie = await client.call_tool(
            "browser_exec",
            {
                "command": f"cookies set JSESSIONID {config['cookie']} --path /"
            },
        )
        print("COOKIE", json.dumps(cookie.data)[:300])
        oracle = await client.call_tool(
            "browser_exec", {"command": "eval " + shlex.quote(ORACLE)}
        )
        print("ORACLE", json.dumps(oracle.data)[:500])
        ended = await client.call_tool("browser_end", {})
        print("END", json.dumps(ended.data))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
