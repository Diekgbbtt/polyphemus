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
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
import asyncio
import json
import logging

BROWSER_TOOL_NAMES = frozenset({"browser_start", "browser_exec", "browser_end"})
# The crawl consumes these two fields; the model must not see the worker's
# container address or its raw CDP port. The generic binding strips both.
_CDP_FIELDS = frozenset({"cdp_url", "cdp_host"})
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_S = 1.0
# A command is bounded by the CLI timeout, and an end can spend that bound on
# the capture plus the stop. Keep the stream read above both.
DEFAULT_READ_TIMEOUT_S = 600.0

logger = logging.getLogger(__name__)


def strip_cdp_fields(value):
    """Remove the CDP endpoint from a model-facing browser result.

    The crawl's own client keeps the endpoint; the generic tool surface must
    not expose the worker container address or its raw Chrome port. String
    payloads are decoded and re-encoded so a JSON tool envelope is filtered
    too.
    """
    if isinstance(value, Mapping):
        return {
            key: strip_cdp_fields(item)
            for key, item in value.items()
            if key not in _CDP_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [strip_cdp_fields(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return value
        if isinstance(parsed, (Mapping, list)):
            return json.dumps(strip_cdp_fields(parsed), ensure_ascii=False)
        return value
    return value


def _strip_start_tool(tool):
    """Wrap `browser_start` so its result omits the CDP endpoint."""
    if getattr(tool, "name", "") != "browser_start":
        return tool
    coroutine = getattr(tool, "coroutine", None)
    func = getattr(tool, "func", None)
    if coroutine is None and func is None:
        return tool

    async def call(*args, **kwargs):
        if coroutine is not None:
            result = await coroutine(*args, **kwargs)
        else:
            result = func(*args, **kwargs)
        return strip_cdp_fields(result)

    if hasattr(tool, "model_copy"):
        return tool.model_copy(update={"coroutine": call, "func": None})
    return tool


@asynccontextmanager
async def open_browser_tools(
    url: str,
    *,
    read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
    client_factory: Callable | None = None,
    loader: Callable | None = None,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
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
    if retry_attempts < 1:
        raise ValueError("the browser MCP retry count must be at least one")
    if retry_delay_s < 0:
        raise ValueError("the browser MCP retry delay must not be negative")

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
    session = None
    handle = None
    last_error: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        # `MultiServerMCPClient.session` returns a one-shot async context
        # manager. A failed attempt consumes it, so every retry needs a fresh
        # one; re-entering the failed object raises on the real adapter.
        session = client.session("browser")
        try:
            handle = await session.__aenter__()
            break
        except Exception as exc:  # noqa: BLE001 - a missing browser degrades
            last_error = exc
            session = None
            if attempt < retry_attempts:
                await asyncio.sleep(retry_delay_s * attempt)
    if handle is None or session is None:
        logger.warning(
            "browser tools are unavailable at %s after %d attempt(s); the "
            "caller runs without them: %s",
            target,
            retry_attempts,
            last_error,
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
        yield [
            _strip_start_tool(tool)
            for tool in tools
            if tool.name in BROWSER_TOOL_NAMES
        ]
    finally:
        try:
            await session.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 - the TTL is the release backstop
            logger.warning(
                "browser MCP session close failed; the lease TTL remains",
                exc_info=True,
            )
