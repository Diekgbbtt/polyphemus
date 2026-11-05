"""The browser tool binding for one hunt (#359, W8).

One hunt holds ONE browser MCP session for its whole turn loop.
The browser MCP keys the lease by the MCP session id, so the three tools
must share it: a session per call would mount a new lease on every call
and lose the one the previous call created.

The binding fails open when the browser service is absent or unreachable:
a hunt without a browser is a degraded capability, not a crashed hunt.
The close in the ``finally`` sends the MCP DELETE, which releases any live
lease through the server's close hook. A crashed process falls back to the
lease TTL.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Callable, Sequence
import logging

BROWSER_TOOL_NAMES = frozenset({"browser_start", "browser_exec", "browser_end"})
# A command is bounded by the CLI timeout, and an end can spend that bound on
# the capture plus the stop. Keep the stream read above both.
DEFAULT_READ_TIMEOUT_S = 600.0

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_browser_tools(
    url: str,
    *,
    read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
    client_factory: Callable | None = None,
    loader: Callable | None = None,
) -> AsyncIterator[Sequence]:
    """Yield the three browser tools over one session, or an empty list.

    ``client_factory`` and ``loader`` are test seams. The production defaults
    are imported lazily so this module stays dependency-free at import.
    """
    target = (url or "").strip()
    if not target:
        yield []
        return
    if read_timeout_s <= 0:
        raise ValueError("the browser MCP read timeout must be positive")

    if client_factory is None or loader is None:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools

        client_factory = client_factory or (
            lambda: MultiServerMCPClient(
                {
                    "browser": {
                        "url": target,
                        "transport": "streamable_http",
                        "sse_read_timeout": read_timeout_s,
                    }
                }
            )
        )
        loader = loader or load_mcp_tools

    client = client_factory()
    session = client.session("browser")
    try:
        handle = await session.__aenter__()
    except Exception:  # noqa: BLE001 - a missing browser must not stop a hunt
        logger.warning(
            "browser tools are unavailable at %s; the hunt runs without them",
            target,
            exc_info=True,
        )
        yield []
        return

    try:
        try:
            tools = await loader(handle)
        except Exception:  # noqa: BLE001 - a load failure is the same degrade
            logger.warning(
                "browser tools failed to load from %s; the hunt runs without them",
                target,
                exc_info=True,
            )
            tools = []
        yield [tool for tool in tools if tool.name in BROWSER_TOOL_NAMES]
    finally:
        try:
            await session.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 - the TTL is the release backstop
            logger.warning(
                "browser MCP session close failed; the lease TTL remains",
                exc_info=True,
            )
