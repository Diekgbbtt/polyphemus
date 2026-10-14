"""App-side client for the kali HTTP-history tools (#196).

The tools invoke their seams SYNCHRONOUSLY (the analysis proposers run on the
sync agent stream), but the kali MCP client is async and a `ClientSession` is
bound to the event loop it was opened on.

The prior shape built a fresh `MultiServerMCPClient` and called `get_tools()` on
every invocation, which (per the adapter) opens a NEW MCP session per tool call.
That pays a full handshake per call, and - bridged through an unbounded
`run_coro_blocking` - a non-returning read blocked the proposer turn forever.

This module instead owns ONE background event loop for the process and keeps ONE
MCP session per analysis unit on it:

  * the unit's first HTTP call opens the session (that is the unit's singleton),
  * every later call of the unit reuses it (one handshake per unit, not per call),
  * the unit boundary closes it (`proposer_turn.proposer_batch`).

A dead session heals HERE, silently, in the client layer (FM-D): a transport
death (`ClosedResourceError`, a timeout, an `OSError`) tears the unit session
down and re-handshakes (bounded retries, exponential backoff), installing the
fresh session under the unit key - so one transport death costs exactly one
call, never the rest of the unit. Healing carries no tool result and no model
chatter; the failed call itself still degrades fail-open.

Every wait is bounded - session open, tool call, and session close - and the
client carries a streamable-HTTP read timeout, so no single failure can stall a
turn. Import performs no I/O (CODING_STANDARD section 6): the loop, the client
and the config all resolve on call.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from anyio import ClosedResourceError

# The streamable-HTTP read timeout handed to the MCP client - the same
# `sse_read_timeout` the recon exec seam sets (`recon.domain.pod`). Bounds ONE
# MCP read on the wire.
_MCP_READ_TIMEOUT_S = 120.0
# Bounds the whole session open (connect + initialize + tools/list).
_MCP_OPEN_TIMEOUT_S = 60.0
# Bounds one tool call end to end.
_MCP_CALL_TIMEOUT_S = 150.0
# Bounds the session close at the unit boundary.
_MCP_CLOSE_TIMEOUT_S = 15.0
# Healing (FM-D): re-handshake attempts after a transport death, and the
# backoff base between them (sleeps run base, 2*base, 4*base, ...).
_HEAL_ATTEMPTS = 3
_HEAL_BACKOFF_S = 1.0

_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_LOCK = threading.Lock()

_SESSION: "_UnitSession | None" = None
_SESSION_KEY: tuple[Any, ...] | None = None
_SESSION_LOCK = threading.Lock()


def structured_payload(result: Any) -> dict:
    """Pure: the tool result carries its dict bare, under `structured_content`,
    or as the JSON text of an MCP content block. Anything else is an error,
    never a silent success."""
    structured: Any = result
    if isinstance(structured, dict) and "structured_content" in structured:
        structured = structured["structured_content"]
    elif isinstance(structured, (list, tuple)):
        # The MCP adapter returns `[{"type": "text", "text": "<json>"}]` for a
        # tool whose FastMCP function returns a dict (verified against the live
        # kali server, 2026-09-16).
        structured = _first_json_dict(structured)
    else:
        structured = getattr(structured, "structured_content", None) or structured
    if isinstance(structured, dict):
        return structured
    return {"error": "unstructured_response", "detail": str(result)[:400]}


def _first_json_dict(blocks) -> dict | None:
    """The first content block whose `text` decodes to a JSON object."""
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                parsed = json.loads(str(block.get("text") or ""))
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _background_loop() -> asyncio.AbstractEventLoop:
    """The process-wide event loop the MCP sessions live on, started lazily on a
    daemon thread. A session must stay on ONE loop for its whole life, so the
    loop outlives every session (per-unit) rather than being rebuilt per call."""
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(
                target=loop.run_forever, name="kali-mcp-loop", daemon=True
            ).start()
            _LOOP = loop
        return _LOOP


class _UnitSession:
    """One MCP client session for ONE analysis unit, served from the background
    loop. The tools are loaded once (`load_mcp_tools`) and reused for every call
    of the unit; the session is torn down at the unit boundary."""

    def __init__(self, url: str):
        self._tools: dict[str, Any] = {}
        self._cm = None
        fut = asyncio.run_coroutine_threadsafe(self._open(url), _background_loop())
        fut.result(_MCP_OPEN_TIMEOUT_S)

    async def _open(self, url: str) -> None:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools

        client = MultiServerMCPClient(
            {"kali": {"url": url, "transport": "streamable_http",
                      "sse_read_timeout": _MCP_READ_TIMEOUT_S}}
        )
        self._cm = client.session("kali")
        session = await self._cm.__aenter__()
        tools = await load_mcp_tools(session)
        self._tools = {tool.name: tool for tool in tools}

    async def _call(self, name: str, args: dict) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"kali MCP exposes no tool {name!r}")
        return await tool.ainvoke(args)

    def call(self, name: str, args: dict) -> Any:
        fut = asyncio.run_coroutine_threadsafe(
            self._call(name, args), _background_loop()
        )
        return fut.result(_MCP_CALL_TIMEOUT_S)

    async def _close(self) -> None:
        cm, self._cm = self._cm, None
        if cm is not None:
            await cm.__aexit__(None, None, None)

    def close(self) -> None:
        try:
            fut = asyncio.run_coroutine_threadsafe(self._close(), _background_loop())
            fut.result(_MCP_CLOSE_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - close is best-effort
            pass


def _unit_key(project_id: str) -> tuple[Any, ...]:
    """The current analysis unit's identity: the project plus the innermost
    `proposer_batch` scope (the streamed chunk id). Outside an analysis scope the
    batch is None, so the key is the project alone."""
    try:
        from polymerhus.analysis.proposer_turn import current_batch

        batch = current_batch()
    except Exception:  # noqa: BLE001 - no analysis scope: key on the project only
        batch = None
    return (project_id, batch)


def _session(project_id: str) -> _UnitSession:
    """The current unit's MCP session, opening it on first use and replacing the
    prior unit's on a key change (the sequential analysis never holds two)."""
    global _SESSION, _SESSION_KEY
    from polymerhus.app.config import config

    key = _unit_key(project_id)
    with _SESSION_LOCK:
        if _SESSION is not None and _SESSION_KEY == key:
            return _SESSION
    # The analysis is sequential (one unit at a time), so opening outside the lock
    # is race-free in practice and keeps the lock off the slow network path.
    session = _UnitSession(config.KALI_MCP_URL)
    with _SESSION_LOCK:
        previous, _SESSION, _SESSION_KEY = _SESSION, session, key
    if previous is not None:
        previous.close()
    return session


def close_unit_session() -> None:
    """Close the current unit's MCP session. Called at the unit boundary
    (`proposer_turn.proposer_batch`); a no-op when nothing is open."""
    global _SESSION, _SESSION_KEY
    with _SESSION_LOCK:
        session, _SESSION, _SESSION_KEY = _SESSION, None, None
    if session is not None:
        session.close()


def _heal_unit_session(project_id: str) -> None:
    """Tear down the unit's dead MCP session and re-handshake, installing the
    fresh session under the unit key on success (FM-D).

    Up to `_HEAL_ATTEMPTS` handshakes with exponential backoff from
    `_HEAL_BACKOFF_S`; every attempt is bounded by `_MCP_OPEN_TIMEOUT_S`.
    Healing is silent client-layer work: it carries no tool result and no
    model chatter. Compare-and-swap under the session lock: a concurrent
    heal (or a fresh unit) that already installed a session wins, and the
    loser closes its surplus instead of leaking it. When every attempt fails
    nothing is cached, so the next call heals again."""
    global _SESSION, _SESSION_KEY
    from polymerhus.app.config import config

    key = _unit_key(project_id)
    with _SESSION_LOCK:
        if _SESSION is not None and _SESSION_KEY != key:
            return  # another unit owns the cache now; leave it alone
        dead = _SESSION if _SESSION_KEY == key else None
        _SESSION, _SESSION_KEY = None, None
    if dead is not None:
        dead.close()
    backoff = _HEAL_BACKOFF_S
    for _ in range(_HEAL_ATTEMPTS):
        try:
            fresh = _UnitSession(config.KALI_MCP_URL)
        except Exception:  # noqa: BLE001 - back off, retry the handshake
            time.sleep(backoff)
            backoff *= 2.0
            continue
        with _SESSION_LOCK:
            if _unit_key(project_id) != key or _SESSION is not None:
                fresh.close()
                return
            _SESSION, _SESSION_KEY = fresh, key
            return


def _call_tool(name: str, args: dict, project_id: str = "") -> dict:
    try:
        return structured_payload(_session(project_id).call(name, args))
    except (ClosedResourceError, TimeoutError, OSError) as exc:
        # Transport death: heal the unit session (silent, client-layer only)
        # so the NEXT call proceeds on a live session; this call still
        # degrades fail-open, never into the turn.
        _heal_unit_session(project_id)
        return {"error": "http_history_failed",
                "detail": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
        return {"error": "http_history_failed",
                "detail": f"{type(exc).__name__}: {exc}"}


def default_http_search_fn(project_id, filters, cursor, limit, text) -> dict:
    return _call_tool("search_http_history", {
        "project_id": project_id, "filters": filters or [], "cursor": cursor,
        "limit": limit, "text": text,
    }, project_id)


def default_http_get_fn(project_id, artifact_id, include_body=False) -> dict:
    return _call_tool("get_http_artifact", {
        "project_id": project_id, "artifact_id": artifact_id,
    }, project_id)


def default_replay_fn(project_id, artifact_id, overrides) -> dict:
    """The pod's replay seam: read the baseline status, or replay with the
    overrides and read the new artifact's status back."""
    if not overrides:
        view = _call_tool("get_http_artifact", {
            "project_id": project_id, "artifact_id": artifact_id}, project_id)
        return {"status": (view.get("response") or {}).get("status")}
    result = _call_tool("replay_http_request", {
        "project_id": project_id, "artifact_id": artifact_id, "overrides": overrides,
    }, project_id)
    if result.get("error"):
        return {"status": None, "error": result}
    view = _call_tool("get_http_artifact", {
        "project_id": project_id, "artifact_id": result.get("artifact_id")}, project_id)
    return {"status": (view.get("response") or {}).get("status"),
            "artifact_id": result.get("artifact_id")}
