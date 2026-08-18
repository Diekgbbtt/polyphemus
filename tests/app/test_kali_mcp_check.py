"""Unit-tier regression for the /health session-churn bug (2026-07-29 diagnosis).

`kali_mcp.check()` used to call `client.get_tools()` (its own session) and then
`exec_tool.ainvoke(...)` (a SECOND independent session) - two full MCP
init/GET-stream/exec/DELETE cycles against kali for a single health poll. That
doubled the churn a `/health` poller produces for no extra signal, and each
cycle's GET-stream bounce is what surfaced as "GET stream disconnected,
reconnecting" once the app's own logging was fixed to reach stdout.

Real network I/O to kali is asserted in `tests/test_agent_health.py` (live
tier). What is provable here, without a running kali, is the SHAPE of the
fix: `check()` must open exactly one `MultiServerMCPClient.session()` and do
both the tool lookup and the invocation inside it.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from polymerhus.app.clients import kali_mcp


class _FakeExecTool:
    name = "execute_command"

    async def ainvoke(self, args):
        assert args == {"command": "echo ok", "session_id": "health"}
        return "ok"


def test_check_opens_exactly_one_session(monkeypatch):
    session_opens = []

    @asynccontextmanager
    async def fake_session(self, server_name, *, auto_initialize=True):
        session_opens.append(server_name)
        yield object()

    async def fake_load_mcp_tools(session):
        return [_FakeExecTool()]

    monkeypatch.setattr(
        "polymerhus.app.clients.kali_mcp.MultiServerMCPClient.session", fake_session
    )
    monkeypatch.setattr(
        "polymerhus.app.clients.kali_mcp.load_mcp_tools", fake_load_mcp_tools
    )

    assert asyncio.run(kali_mcp.check()) is True
    assert session_opens == ["kali"], (
        f"expected exactly one MCP session, got {session_opens!r} - "
        "check() must not open a separate session for tool lookup vs invocation"
    )
