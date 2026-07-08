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

PROVIDER SEAM
------------
The concrete provider is `steel_provider.SteelCrawlProvider` - the async port of
Redamon's `mcp/servers/playwright_server.py` steel section (see that module's
docstring). This module pins the stable public contract:

  * `steel_configured()` checks only the steel.dev credential.
  * `get_crawl_tools(*, client_factory=None)` returns the `steel_*` tools from
    the in-process provider, filtered to `CRAWL_TOOL_NAMES`. `client_factory`
    is injectable so tests exercise the whole contract without live Steel.
  * `_default_client_factory()` builds the real provider. If its runtime deps
    (`playwright` + `steel-sdk`) are not importable in this build, it raises
    `SteelProviderUnavailable`, which the crawl pod's best-effort path turns
    into an empty manifest (reduced coverage), never a crash. `SteelNotConfigured`
    is raised earlier by `get_crawl_tools` when the credential itself is absent.
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
    """Raised when `STEEL_API_KEY` is set but the in-process Steel crawl-tool
    provider cannot be built in this environment - specifically, when its
    runtime dependencies (`playwright` and `steel-sdk`) are not importable.

    The provider drives a steel.dev cloud browser over CDP and needs both
    packages; the `redamon-agent` base image provides them. Callers (the crawl
    pod) treat this as reduced coverage, not a crash.
    """


def steel_configured() -> bool:
    """True when the steel.dev credential is present.

    No URL is involved: the provider is in-process and reaches steel.dev's
    cloud browser over CDP using the API key alone.
    """
    return bool(config.STEEL_API_KEY)


def _default_client_factory(auth_cookies=None):
    """Build the in-process Steel crawl-tool provider.

    Returns a `steel_provider.SteelCrawlProvider`, which opens a steel.dev
    cloud-browser session and connects Playwright over CDP
    (``wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<id>``) lazily,
    only when `steel_crawl_start` is invoked - so constructing the provider
    performs no network I/O.

    `auth_cookies` (a list of `{name, value, [domain], [path]}` dicts, from the
    project's `auth_context.cookies`) is forwarded to the provider, which seeds
    the browser context with them before the crawl (non-interactive auth).

    Raises `SteelProviderUnavailable` when the provider's runtime dependencies
    (`playwright` and `steel-sdk`) are not importable in this build, so the
    crawl pod degrades to reduced coverage instead of crashing. Tests inject
    `client_factory` and never reach this path.
    """
    import importlib.util  # noqa: PLC0415

    missing = [
        pkg for pkg in ("playwright", "steel")
        if importlib.util.find_spec(pkg) is None
    ]
    if missing:
        raise SteelProviderUnavailable(
            "Steel crawl-tool provider dependencies are not importable: "
            f"{', '.join(missing)}. The provider drives a steel.dev cloud "
            "browser over CDP and needs both `playwright` and `steel-sdk` "
            "(the redamon-agent base image provides them)."
        )

    from agent.recon.crawl.steel_provider import SteelCrawlProvider  # noqa: PLC0415

    return SteelCrawlProvider(auth_cookies=auth_cookies)


async def get_crawl_tools(*, client_factory=None, auth_cookies=None) -> list:
    """Return the `steel_*` crawl tools from the in-process provider.

    The default provider (`_default_client_factory`) exposes
    `async get_tools() -> list`; the result is filtered to `CRAWL_TOOL_NAMES`.
    `auth_cookies` (from the project's `auth_context.cookies`) is threaded to the
    default provider so the browser context is seeded for non-interactive auth;
    an injected `client_factory` stays a zero-arg callable (tests build the
    provider themselves) and does not receive cookies. Raises
    `SteelNotConfigured` when the steel.dev credential is absent.
    """
    if not steel_configured():
        raise SteelNotConfigured(
            "STEEL_API_KEY (steel.dev credential) must be set to use the crawl tools"
        )
    if client_factory is not None:
        client = client_factory()
    else:
        client = _default_client_factory(auth_cookies=auth_cookies)
    tools = await client.get_tools()
    return [t for t in tools if getattr(t, "name", "") in CRAWL_TOOL_NAMES]
