from langchain_mcp_adapters.client import MultiServerMCPClient
from polymerhus.app.config import config

async def check() -> bool:
    client = MultiServerMCPClient(
        {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}}
    )
    tools = await client.get_tools()
    exec_tool = next(t for t in tools if t.name == "execute_command")
    result = await exec_tool.ainvoke({"command": "echo ok", "session_id": "health"})
    return "ok" in str(result)
