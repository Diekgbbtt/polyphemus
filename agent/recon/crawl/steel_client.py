from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.recon import config

CRAWL_TOOL_NAMES = frozenset({
    "steel_crawl_start",
    "steel_navigate",
    "steel_frontier",
    "steel_eval",
    "steel_click",
    "steel_crawl_finish",
    "steel_await_auth",
})


class SteelNotConfigured(RuntimeError):
    """Raised when Steel MCP client tools are requested but STEEL_MCP_URL /
    STEEL_API_KEY are not both configured."""


def steel_configured() -> bool:
    return bool(config.STEEL_MCP_URL) and bool(config.STEEL_API_KEY)


def _default_client_factory():
    return MultiServerMCPClient(
        {
            "steel": {
                "url": config.STEEL_MCP_URL,
                "transport": "streamable_http",
                "headers": {"Authorization": f"Bearer {config.STEEL_API_KEY}"},
            }
        }
    )


async def get_crawl_tools(*, client_factory=None) -> list:
    if not steel_configured():
        raise SteelNotConfigured(
            "STEEL_MCP_URL and STEEL_API_KEY must both be set to use the crawl tools"
        )
    factory = client_factory or _default_client_factory
    client = factory()
    tools = await client.get_tools()
    return [t for t in tools if getattr(t, "name", "") in CRAWL_TOOL_NAMES]
