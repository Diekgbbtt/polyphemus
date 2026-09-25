import json

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from polymerhus.app.config import config


def _as_mapping(result: object) -> dict:
    """Best-effort extraction of a dict tool payload from the MCP result.

    The langchain adapter hands back a ToolMessage whose structured content may
    ride `.artifact` (a dict) or `.content` (JSON text or a dict). A shape we
    cannot read yields `{}`, which the caller's `RuntimeCapabilities` degrades to
    "incompatible" - never a silent assumption of capability.
    """
    artifact = getattr(result, "artifact", None)
    if isinstance(artifact, dict):
        # The langchain-mcp adapter wraps a structured tool result under
        # `structured_content` (observed live against the Kali MCP surface).
        inner = artifact.get("structured_content")
        return inner if isinstance(inner, dict) else artifact
    content = getattr(result, "content", result)
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return result if isinstance(result, dict) else {}


async def proxy_status() -> dict:
    """Read Kali's runtime-capability surface through the MCP `proxy_status` tool.

    #238 A9: the controller negotiates against this BEFORE measuring and before
    any target-facing dispatch. The caller treats an unreadable or incompatible
    surface as a conservative refusal.
    """
    client = MultiServerMCPClient(
        {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}}
    )
    tools = await client.get_tools()
    status_tool = next(t for t in tools if t.name == "proxy_status")
    result = await status_tool.ainvoke(
        {"type": "tool_call", "name": "proxy_status", "id": "capabilities", "args": {}}
    )
    return _as_mapping(result)


async def check() -> bool:
    """Reachability probe for `/health`.

    Runs `load_mcp_tools` and the `execute_command` invocation inside ONE
    `client.session()` rather than two separate `MultiServerMCPClient` calls
    (the prior `get_tools()` + `exec_tool.ainvoke()` shape) - each of those
    opens its own MCP session independently, so a single health check was
    doubling the per-poll session churn against kali (two full
    init/GET/exec/DELETE cycles instead of one) for no extra signal.
    """
    client = MultiServerMCPClient(
        {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}}
    )
    async with client.session("kali") as session:
        tools = await load_mcp_tools(session)
        exec_tool = next(t for t in tools if t.name == "execute_command")
        result = await exec_tool.ainvoke({"command": "echo ok", "session_id": "health"})
    return "ok" in str(result)
