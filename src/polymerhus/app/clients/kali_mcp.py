from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from polymerhus.app.config import config

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
