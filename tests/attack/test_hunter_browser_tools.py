"""Unit tier: the per-hunt browser binding and the tool invoker (#359, W8).

The live edge is a fake MCP client. These tests pin the two properties the
binding owns: one session per hunt (so the three tools share one lease), and a
fail-open degrade when the browser service is absent.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from polymerhus.attack.hunting.browser_tools import (
    BROWSER_TOOL_NAMES,
    open_browser_tools,
)
from polymerhus.attack.hunting.hunting_agent import invoke_tool


class _Session:
    def __init__(self, *, enter_error=None, exit_error=None):
        self.enter_error = enter_error
        self.exit_error = exit_error
        self.closed = False

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self

    async def __aexit__(self, *exc_info):
        self.closed = True
        if self.exit_error is not None:
            raise self.exit_error
        return False


class _Client:
    def __init__(self, session: _Session):
        self._session = session

    def session(self, name: str):
        assert name == "browser"
        return self._session


def _tools(*names: str):
    return [SimpleNamespace(name=name) for name in names]


def _collect(url: str, *, session: _Session, loader, **kwargs):
    async def run():
        async with open_browser_tools(
            url,
            client_factory=lambda: _Client(session),
            loader=loader,
            **kwargs,
        ) as tools:
            return list(tools)

    return asyncio.run(run())


def test_empty_url_yields_no_tools_and_builds_no_client():
    def refuse():
        raise AssertionError("an empty URL must not build a client")

    async def run():
        async with open_browser_tools(
            "", client_factory=refuse, loader=refuse
        ) as tools:
            return list(tools)

    assert asyncio.run(run()) == []


def test_unreachable_browser_fails_open():
    session = _Session(enter_error=ConnectionError("no route"))

    async def loader(_handle):
        raise AssertionError("the loader must not run without a session")

    assert _collect(
        "http://kali:8003/mcp",
        session=session,
        loader=loader,
        retry_attempts=1,
    ) == []


def test_a_transient_browser_open_is_retried():
    class _FlakySession(_Session):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def __aenter__(self):
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("starting")
            return self

    session = _FlakySession()

    async def loader(_handle):
        return _tools("browser_exec")

    tools = _collect(
        "http://kali:8003/mcp",
        session=session,
        loader=loader,
        retry_attempts=2,
        retry_delay_s=0.0,
    )

    assert [tool.name for tool in tools] == ["browser_exec"]
    assert session.attempts == 2
    assert session.closed is True


def test_only_the_three_browser_tools_are_exposed():
    session = _Session()

    async def loader(_handle):
        return _tools("browser_start", "browser_exec", "browser_end", "other")

    tools = _collect("http://kali:8003/mcp", session=session, loader=loader)

    assert [tool.name for tool in tools] == [
        "browser_start",
        "browser_exec",
        "browser_end",
    ]
    assert BROWSER_TOOL_NAMES == {
        "browser_start",
        "browser_exec",
        "browser_end",
    }
    assert session.closed is True


def test_a_hunt_error_still_closes_the_session():
    session = _Session()

    async def loader(_handle):
        return _tools("browser_exec")

    async def run():
        async with open_browser_tools(
            "http://kali:8003/mcp",
            client_factory=lambda: _Client(session),
            loader=loader,
        ):
            raise RuntimeError("hunt failed")

    with pytest.raises(RuntimeError, match="hunt failed"):
        asyncio.run(run())
    assert session.closed is True


def test_a_load_failure_fails_open_and_closes():
    session = _Session()

    async def loader(_handle):
        raise RuntimeError("bad handshake")

    assert _collect("http://kali:8003/mcp", session=session, loader=loader) == []
    assert session.closed is True


def test_a_close_failure_does_not_mask_the_tools():
    session = _Session(exit_error=RuntimeError("close failed"))

    async def loader(_handle):
        return _tools("browser_end")

    tools = _collect("http://kali:8003/mcp", session=session, loader=loader)

    assert [tool.name for tool in tools] == ["browser_end"]


def test_the_model_facing_start_tool_strips_the_cdp_endpoint():
    from langchain_core.tools import StructuredTool

    seen: dict = {}

    async def start(name: str) -> dict:
        return {
            "success": True,
            "session": {"name": name, "session_id": "steel-1"},
            "cdp_url": "ws://172.20.0.5:3000/",
            "cdp_host": "localhost:3000",
        }

    tool = StructuredTool.from_function(
        coroutine=start, name="browser_start", description="mount"
    )

    async def loader(_handle):
        return [tool]

    async def run():
        async with open_browser_tools(
            "http://kali:8003/mcp",
            client_factory=lambda: _Client(_Session()),
            loader=loader,
        ) as tools:
            exposed = tools[0]
            result = await exposed.ainvoke({"name": "steel-proj"})
            return exposed, result

    exposed, result = asyncio.run(run())

    assert exposed.name == "browser_start"
    assert result["session"]["session_id"] == "steel-1"
    assert "cdp_url" not in result
    assert "cdp_host" not in result
    seen.update(result)


def test_the_strip_handles_a_json_string_envelope():
    from polymerhus.attack.hunting.browser_tools import strip_cdp_fields

    payload = '{"success": true, "cdp_url": "ws://x/", "cdp_host": "localhost:3000"}'

    stripped = strip_cdp_fields(payload)

    assert "cdp_url" not in stripped
    assert "cdp_host" not in stripped
    assert '"success": true' in stripped


def test_a_non_positive_read_timeout_is_rejected():
    session = _Session()

    async def loader(_handle):
        return _tools("browser_exec")

    with pytest.raises(ValueError, match="read timeout"):
        _collect(
            "http://kali:8003/mcp",
            session=session,
            loader=loader,
            read_timeout_s=0,
        )


class _AsyncTool:
    """A real LangChain tool with an async-only body, like an MCP tool."""

    name = "browser_exec"

    def __init__(self):
        self.calls = []
        from langchain_core.tools import StructuredTool

        async def run(command: str) -> dict:
            self.calls.append({"command": command})
            return {"success": True, "data": "ok"}

        self._tool = StructuredTool.from_function(
            coroutine=run,
            name="browser_exec",
            description="run one browser command",
        )

    @property
    def coroutine(self):
        return self._tool.coroutine

    async def ainvoke(self, args):
        return await self._tool.ainvoke(args)


class _SyncTool:
    name = "exec"

    def __init__(self):
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return "ok"


class _RaisingTool:
    name = "notes"

    async def ainvoke(self, args):
        raise RuntimeError("boom")


def test_invoke_tool_awaits_an_async_only_tool():
    tool = _AsyncTool()

    result = asyncio.run(invoke_tool({"browser_exec": tool}, "browser_exec", {"command": "snapshot -i"}))

    assert "success" in result
    assert tool.calls == [{"command": "snapshot -i"}]


def test_invoke_tool_falls_back_to_a_sync_tool():
    tool = _SyncTool()

    assert asyncio.run(invoke_tool({"exec": tool}, "exec", {"command": "id"})) == "ok"
    assert tool.calls == [{"command": "id"}]


def test_invoke_tool_degrades_unknown_and_malformed_calls():
    assert "unknown_tool" in asyncio.run(invoke_tool({}, "browser_exec", {}))
    assert "invalid_args" in asyncio.run(
        invoke_tool({"browser_exec": _AsyncTool()}, "browser_exec", [])
    )


def test_invoke_tool_degrades_a_raising_tool():
    result = asyncio.run(invoke_tool({"notes": _RaisingTool()}, "notes", {}))

    assert "tool_failed" in result
