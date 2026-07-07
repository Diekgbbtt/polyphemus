"""Steel agentic-crawl tool provider.

Correct architecture (operator correction, SP4). The seven `steel_*` MCP tools
(`steel_crawl_start`/`navigate`/`frontier`/`eval`/`click`/`crawl_finish`/`await_auth`)
are provided by a Steel MCP tool provider instantiated **in-process** - they are
NOT reached over a remote MCP HTTP host. steel.dev is the authenticated CLOUD
BROWSER; the provider opens a steel.dev session and drives it with Playwright
connected over CDP:

    wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<session id>

exactly as in Redamon's implementation. The only credential is the steel.dev
API key (`STEEL_API_KEY`); there is no `STEEL_MCP_URL`.

PROVIDER SEAM - what is stubbed and why
---------------------------------------
Redamon's concrete in-process steel MCP server - the module that defines the
seven `steel_*` tool functions on top of a steel.dev Playwright-over-CDP
session - is NOT vendored in any `redamon-*` image available in this
environment. In the built images `steel_crawl_start` et al. appear only as
*consumers* (`crawl_agentic.py` calls `mcp_manager.get_tools()`) and in the
`steel_crawl` skill prompt; the server itself lives in Redamon source that is
not present here. So it cannot be ported verbatim yet.

Rather than invent a fake steel.dev integration, this module pins the CORRECT
public contract and leaves a single, clearly-marked provider seam:

  * `steel_configured()` checks only the steel.dev credential.
  * `get_crawl_tools(*, client_factory=None)` returns the `steel_*` tools from
    the in-process provider, filtered to `CRAWL_TOOL_NAMES`. `client_factory`
    is injectable so tests exercise the whole contract without live Steel.
  * `_default_client_factory()` is the ONLY place the real provider must be
    wired. Until Redamon's steel server is vendored, it raises
    `SteelProviderUnavailable`, which the crawl pod's best-effort path turns
    into an empty manifest (reduced-coverage), never a crash.

Wiring the real provider is a localized follow-up: port Redamon's steel_*
server so `_default_client_factory()` returns an object exposing
`async get_tools() -> list[Tool]` (each tool `.name` in `CRAWL_TOOL_NAMES`,
each `.ainvoke(dict)`-able). Nothing else in the crawl stack changes.
"""
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
    """Raised when the steel crawl tools are requested but the steel.dev
    credential (`STEEL_API_KEY`) is not configured."""


class SteelProviderUnavailable(RuntimeError):
    """Raised when `STEEL_API_KEY` is set but the in-process Steel MCP tool
    provider has not been wired in this build.

    See the module docstring's PROVIDER SEAM note: Redamon's concrete
    `steel_*` server (Playwright-over-CDP to steel.dev) is not vendored in
    this environment yet. Callers (the crawl pod) treat this as reduced
    coverage, not a crash.
    """


def steel_configured() -> bool:
    """True when the steel.dev credential is present.

    No URL is involved: the provider is in-process and reaches steel.dev's
    cloud browser over CDP using the API key alone.
    """
    return bool(config.STEEL_API_KEY)


def _default_client_factory():
    """Build the in-process Steel MCP tool provider.

    The real provider opens a steel.dev cloud-browser session and connects
    Playwright over CDP
    (``wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<id>``), then
    exposes the seven `steel_*` tools over that session. That concrete
    provider is not vendored in this environment yet (see module docstring:
    PROVIDER SEAM) - so this raises rather than silently pretending to crawl.
    Tests inject `client_factory` and never reach this path.
    """
    raise SteelProviderUnavailable(
        "In-process Steel MCP tool provider is not wired: port Redamon's "
        "steel_* crawl server (Playwright-over-CDP to steel.dev) and return it "
        "from _default_client_factory. STEEL_API_KEY is set but there is no "
        "provider to build."
    )


async def get_crawl_tools(*, client_factory=None) -> list:
    """Return the `steel_*` crawl tools from the in-process provider.

    `client_factory` (default `_default_client_factory`) builds a provider
    object exposing `async get_tools() -> list`; the result is filtered to
    `CRAWL_TOOL_NAMES`. Raises `SteelNotConfigured` when the steel.dev
    credential is absent.
    """
    if not steel_configured():
        raise SteelNotConfigured(
            "STEEL_API_KEY (steel.dev credential) must be set to use the crawl tools"
        )
    factory = client_factory or _default_client_factory
    client = factory()
    tools = await client.get_tools()
    return [t for t in tools if getattr(t, "name", "") in CRAWL_TOOL_NAMES]
