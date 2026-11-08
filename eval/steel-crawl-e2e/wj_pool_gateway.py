"""Mint the White Jotter decoupled auth context through the browser MCP (E2E setup).

The gateway's observable act is: mount the decoupled context reference, put
the authenticated session into the browser, prove the oracle, and end with
`persist_context=true`. This script performs that act; the phase runner then
mounts the same reference and proves the crawl restores it.

Run inside the kali container, where the pool MCP answers on
`127.0.0.1:8003/mcp`. The config file carries the ephemeral session name and
the decoupled context reference; it carries no credential.
"""
from __future__ import annotations

import asyncio
import json
import shlex

from fastmcp import Client

LOGIN = (
    "(async()=>{const r=await fetch(\"/api/login\",{method:\"POST\","
    "headers:{\"content-type\":\"application/json\"},"
    "body:JSON.stringify({username:\"admin\",password:\"123\"}),"
    "credentials:\"include\"});const t=await r.text();return "
    "JSON.stringify({status:r.status,body:t.slice(0,200)})})()"
)

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
            "browser_start",
            {
                "name": config["name"],
                "context_ref": config["context_ref"],
                "url": "http://t-1618c524.target/",
            },
        )
        print("START", json.dumps(started.data))
        login = await client.call_tool(
            "browser_exec", {"command": "eval " + shlex.quote(LOGIN)}
        )
        print("LOGIN", json.dumps(login.data)[:400])
        oracle = await client.call_tool(
            "browser_exec", {"command": "eval " + shlex.quote(ORACLE)}
        )
        print("ORACLE", json.dumps(oracle.data)[:500])
        ended = await client.call_tool(
            "browser_end", {"persist_context": True}
        )
        print("END", json.dumps(ended.data))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
