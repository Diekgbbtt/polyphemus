"""Prototype MCP client for the Steel pool.

One client process holds one MCP session for the whole browser task.
That session is the lease owner key. The client calls start, commands, and end
through the MCP tools. It never sees a worker URL.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from fastmcp import Client

URL = os.environ.get("STEEL_MCP_URL", "http://steel-mcp:8003/mcp")
CLIENT_ID = os.environ.get("CLIENT_ID", "agent")
OWNER = os.environ.get("OWNER", "proto")
HOLD_S = float(os.environ.get("HOLD_S", "0"))
OUTLIER = os.environ.get("OUTLIER", "0") == "1"
WAIT_ONLY = os.environ.get("WAIT_ONLY", "0") == "1"
RELEASE_OWNER = os.environ.get("RELEASE_OWNER", "0") == "1"
CRAWLER = os.environ.get("CRAWLER", "0") == "1"
STATUS_ONLY = os.environ.get("STATUS_ONLY", "0") == "1"


def emit(step: str, data: Any) -> None:
    print(
        json.dumps(
            {
                "ts": round(time.time(), 3),
                "client": CLIENT_ID,
                "step": step,
                "data": data,
            },
            default=str,
            sort_keys=True,
        ),
        flush=True,
    )


async def call(
    client: Client, name: str, args: dict, *, progress: bool = False
) -> Any:
    async def on_progress(value: float, total: float | None, message: str | None) -> None:
        emit(
            f"progress:{name}",
            {"value": value, "total": total, "message": message},
        )

    if progress:
        result = await client.call_tool(name, args, progress_handler=on_progress)
    else:
        result = await client.call_tool(name, args)
    data = result.data if result.data is not None else result.content
    emit(name, data)
    return data


async def run_once() -> bool:
    async with Client(URL, timeout=90) as client:
        tools = await client.list_tools()
        emit("tools", [tool.name for tool in tools])

        if RELEASE_OWNER:
            await call(client, "release_owner", {"owner": OWNER})
            await call(client, "pool_status", {})
            return True

        if STATUS_ONLY:
            await call(client, "pool_status", {})
            return True

        start = await call(
            client,
            "browser_start",
            {
                "name": f"proto-{CLIENT_ID}",
                "url": "https://example.com",
                "owner": OWNER,
            },
        )
        if start.get("status") == "wait":
            emit("pool_wait", start)
            return True

        if OUTLIER:
            emit("outlier_hold", {"seconds": HOLD_S})
            await asyncio.sleep(HOLD_S)
            emit("outlier_exit", {"without_end": True})
            return True

        if WAIT_ONLY:
            await call(client, "browser_end", {})
            return True

        if CRAWLER:
            for url in (
                "https://example.org",
                "https://example.net",
                "https://example.edu",
            ):
                await call(client, "browser_navigate", {"url": url})
                await call(client, "browser_eval", {"script": "location.href"})
                await call(client, "browser_get", {"what": "title"})
        else:
            await call(
                client,
                "browser_navigate",
                {"url": "https://example.org"},
                progress=True,
            )
            await call(client, "browser_eval", {"script": "location.href"})
            await call(client, "browser_get", {"what": "title"})
            await call(client, "browser_tabs", {})

        if HOLD_S:
            emit("hold", {"seconds": HOLD_S})
            await asyncio.sleep(HOLD_S)

        await call(client, "browser_end", {})
        await call(client, "pool_status", {})
        return True


async def main() -> None:
    for attempt in range(1, 16):
        try:
            ok = await run_once()
            if ok:
                return
        except Exception as exc:  # noqa: BLE001 - the prototype logs and retries
            emit(
                "error",
                {
                    "attempt": attempt,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            await asyncio.sleep(2)
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
