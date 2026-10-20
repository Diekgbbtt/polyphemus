"""Steel agentic-crawl tool provider.

Correct architecture (operator correction, SP4). The six `steel_*` MCP tools
(`steel_crawl_start`/`navigate`/`frontier`/`eval`/`click`/`crawl_finish`)
are provided by a Steel MCP tool provider instantiated **in-process** - they are
NOT reached over a remote MCP HTTP host. The browser runtime is the steel.dev
CLOUD BROWSER by default, or a self-hosted runtime when the deployment sets
`STEEL_BROWSER_API_URL` (#390). The provider opens a session and drives it with
Playwright connected over CDP at the session's own `websocket_url`:

    ws://<runtime host>:<port>/

When the SDK session omits `websocket_url`, the provider falls back to the
cloud pattern:

    wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<session id>

A cloud deployment is configured by the steel.dev API key (`STEEL_API_KEY`);
a local deployment is keyless and configured by `STEEL_BROWSER_API_URL`. There
is no `STEEL_MCP_URL`.

PROVIDER SEAM
------------
The concrete provider is `steel_provider.SteelCrawlProvider` (see that
module's docstring). This module pins the stable public contract:

  * `steel_configured()` accepts a key or an endpoint.
  * `get_crawl_tools(*, client_factory=None)` returns the `steel_*` tools from
    the in-process provider, filtered to `CRAWL_TOOL_NAMES`. `client_factory`
    is injectable so tests exercise the whole contract without live Steel.
  * `_default_client_factory()` builds the real provider. If its runtime deps
    (`playwright` + `steel-sdk`) are not importable in this build, it raises
    `SteelProviderUnavailable`, which the crawl pod's best-effort path turns
    into an empty manifest (reduced coverage), never a crash. `SteelNotConfigured`
    is raised earlier by `get_crawl_tools` when neither a key nor an endpoint is
    configured.
"""
from polymerhus.app.steel_endpoint import steel_browser_api_url
from polymerhus.recon import config

CRAWL_TOOL_NAMES = frozenset({
    "steel_crawl_start",
    "steel_navigate",
    "steel_frontier",
    "steel_eval",
    "steel_click",
    "steel_crawl_finish",
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
    """True when the Steel runtime is configured.

    A cloud deployment is configured by `STEEL_API_KEY`; a local deployment
    is configured by `STEEL_BROWSER_API_URL` alone and needs no key (#395,
    D359-12). The provider resolves the address through the same shared
    resolver.
    """
    return bool(config.STEEL_API_KEY or steel_browser_api_url())


def _default_client_factory(steel_state=None, browser_auth=None):
    """Build the in-process Steel crawl-tool provider.

    Returns a `steel_provider.SteelCrawlProvider`, which opens a browser
    session on the runtime named by `STEEL_BROWSER_API_URL` (the steel.dev
    cloud when unset) and connects Playwright over CDP at the session's
    `websocket_url`, lazily, only when `steel_crawl_start` is invoked - so
    constructing the provider performs no network I/O.

    `steel_state` is the resolved per-account state file; `browser_auth` is
    the feed-projected material (cookies, headers, storage tokens). The
    provider restores state, replicates the material, and runs the auth gate.

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

    from polymerhus.recon.crawl.steel_provider import SteelCrawlProvider  # noqa: PLC0415

    return SteelCrawlProvider(steel_state=steel_state, browser_auth=browser_auth)


async def get_crawl_tools(*, client_factory=None, steel_state=None, browser_auth=None) -> list:
    """Return the `steel_*` crawl tools from the in-process provider.

    The default provider (`_default_client_factory`) exposes
    `async get_tools() -> list`; the result is filtered to `CRAWL_TOOL_NAMES`.
    `steel_state` and `browser_auth` are threaded to the default provider.
    An injected `client_factory` stays a zero-arg callable (tests build the
    provider themselves) and receives nothing. Raises `SteelNotConfigured`
    when neither a key nor an endpoint is configured.
    """
    if not steel_configured():
        raise SteelNotConfigured(
            "STEEL_API_KEY or STEEL_BROWSER_API_URL must be set to use the crawl tools"
        )
    if client_factory is not None:
        client = client_factory()
    else:
        client = _default_client_factory(steel_state=steel_state, browser_auth=browser_auth)
    tools = await client.get_tools()
    return [t for t in tools if getattr(t, "name", "") in CRAWL_TOOL_NAMES]
