"""Live e2e: the one `browser` tool over the in-stack Steel pool.

Production path only. The test drives the real `build_browser_tool` and the
real `McpBrowserClient` against the live pool MCP; a real Steel worker renders
the target. Nothing is mocked: no fake client, no fake worker, no recorded
envelope.

Topology: the test must reach the pool MCP (the compose-network address
`http://kali:8003/mcp`), and the WORKER must reach the target URL. The target
is deployment-specific, so it arrives as `BROWSER_E2E_TARGET_URL` (for the
eval stack, `http://t-1fc05262.target/`).

Gate: skip when either the MCP address or the target URL is absent. The
browser is a deployment capability, never a boot dependency, so the offline
tiers stay green on a clean clone. On the eval host the eval overlay supplies
the MCP address and the run supplies the target.

Run in-network (the tests service resolves `kali`):

    docker compose ... run --rm tests tests/e2e/test_browser_tool_live.py -q
"""
from __future__ import annotations

import os
import shlex
import uuid

import pytest

MCP_ENV = "KALI_BROWSER_MCP_URL"
TARGET_ENV = "BROWSER_E2E_TARGET_URL"

pytestmark = pytest.mark.skipif(
    not os.environ.get(MCP_ENV, "").strip()
    or not os.environ.get(TARGET_ENV, "").strip(),
    reason=(
        f"live pool browser e2e needs {MCP_ENV} and {TARGET_ENV} "
        "(the pool MCP address and a target the worker can reach)"
    ),
)


def _tool(project_id: str, instance_id: str):
    from polymerhus.app.llm.browser_tools import build_browser_tool

    return build_browser_tool(
        project_id=project_id,
        role="hunter",
        instance_id=instance_id,
        mcp_url=os.environ[MCP_ENV],
    )


def _invoke(tool, **arguments):
    import json

    return json.loads(tool.invoke(arguments))


def _js(tool, expression: str):
    """One `exec` carrying a JS expression, quoted for the CLI grammar."""
    return _invoke(
        tool, command="exec", input=f"eval {shlex.quote(expression)}"
    )


def test_a_live_session_renders_the_target_and_ends_without_a_context_write():
    target = os.environ[TARGET_ENV]
    tool = _tool(f"e2e-browser-{uuid.uuid4().hex[:8]}", "live-anonymous")
    try:
        start = _invoke(tool, command="start", url=target)
        assert start["success"] is True, start
        assert start["context_ref"] is None, start
        assert start["session"]["session_id"], start

        title = _js(tool, "document.title")
        assert title["success"] is True, title
        assert title["data"].strip(), title

        end = _invoke(tool, command="end")
        assert end["success"] is True, end
        assert end["ended"] is True, end
        assert end["stopped"] is True, end
        # The contract: a default end NEVER writes the decoupled auth context.
        assert end["context_saved"] is False, end
    finally:
        tool.close()


def test_an_explicit_persist_restores_the_context_on_the_next_session():
    target = os.environ[TARGET_ENV]
    project_id = "e2e-browser-context"
    account = "live-probe"
    marker = f"e2e_{uuid.uuid4().hex[:8]}"
    expected_ref = f"steel-auth-{project_id}-{account}"
    tool = _tool(project_id, "live-context")
    try:
        start = _invoke(tool, command="start", url=target, account=account)
        assert start["success"] is True, start
        assert start["context_ref"] == expected_ref, start

        set_cookie = _js(
            tool, f'document.cookie="{marker}=yes;path=/"'
        )
        assert set_cookie["success"] is True, set_cookie

        end = _invoke(tool, command="end", persist_context=True)
        assert end["success"] is True, end
        assert end["context_saved"] is True, end
        assert end["context_ref"] == expected_ref, end

        resumed = _invoke(tool, command="start", url=target, account=account)
        assert resumed["success"] is True, resumed
        assert resumed["context_ref"] == expected_ref, resumed
        assert resumed["restored"]["cookies"] >= 1, resumed

        cookie = _js(tool, "document.cookie")
        assert cookie["success"] is True, cookie
        assert marker in cookie["data"], cookie

        # The default end is a no-op on the context: the restored state is
        # not re-written unless the agent asks for it.
        ended = _invoke(tool, command="end")
        assert ended["success"] is True, ended
        assert ended["context_saved"] is False, ended
    finally:
        tool.close()
