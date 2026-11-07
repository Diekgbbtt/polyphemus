"""The crawl's typed adapter over the shared browser MCP client.

The transport lives in `polymerhus.app.llm.browser_client`; this module maps
its typed envelopes onto the crawl's session errors and projects one
`browser_start` into the crawl's `StartResult`. The crawl never sees the
agent-facing `BrowserTool`; it addresses the client directly so the passive
CDP capture keeps the endpoint.

The module imports no driver and performs no I/O at import.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from polymerhus.app.llm.browser_client import (
    BrowserMcpError as AppBrowserMcpError,
    BrowserStart as McpStart,
    BrowserUnavailable as AppBrowserUnavailable,
    McpBrowserClient as AppMcpBrowserClient,
)
from polymerhus.recon.crawl.steel.session import (
    CLI_ERROR_TYPES,
    BrowserUnavailable,
    CommandFailed,
    GuardError,
    InvalidCommand,
    RestoreFailed,
    SessionMissing,
    SessionStillLive,
    SessionTaken,
    StartResult,
    SteelSession,
    SteelSessionError,
    SteelSessionRegistry,
)

DEFAULT_CALL_TIMEOUT_S = 330.0
DEFAULT_CLOSE_TIMEOUT_S = 10.0

MCP_ERROR_TYPES: dict[str, type[SteelSessionError]] = {
    "no_session": SessionMissing,
    "session_in_use": SessionTaken,
    "invalid_command": InvalidCommand,
    "invalid_argument": InvalidCommand,
    "guard_error": GuardError,
    "pool_exhausted": BrowserUnavailable,
    "pool_unavailable": BrowserUnavailable,
    "browser_unavailable": BrowserUnavailable,
    "restore_failed": RestoreFailed,
    "store_error": CommandFailed,
    "lease_error": CommandFailed,
    "capture_failed": CommandFailed,
    "browser_error": CommandFailed,
    "internal_error": CommandFailed,
}

__all__ = [
    "DEFAULT_CALL_TIMEOUT_S",
    "DEFAULT_CLOSE_TIMEOUT_S",
    "MCP_ERROR_TYPES",
    "BrowserUnavailable",
    "McpBackend",
    "McpBrowserClient",
    "McpBrowserError",
    "McpStart",
    "raise_for_mcp_error",
]


class McpBrowserError(SteelSessionError):
    """The browser MCP returned a payload that violates its contract."""

    code = "mcp_protocol_error"
    default_message = "the browser MCP returned an invalid payload"


def _error_code(error: object) -> tuple[str, str]:
    if isinstance(error, Mapping):
        return str(error.get("code") or ""), str(error.get("message") or "")
    if isinstance(error, str):
        return error, ""
    return "", ""


def raise_for_mcp_error(error: object) -> None:
    """Raise the typed crawl error for one MCP error object."""
    code, message = _error_code(error)
    if not code:
        raise CommandFailed("the browser MCP reported failure without a code")
    mapped = MCP_ERROR_TYPES.get(code)
    if mapped is None:
        mapped = CLI_ERROR_TYPES.get(code)
    if mapped is None:
        raise CommandFailed(f"unmapped browser MCP error: {code}: {message}")
    payload = dict(error) if isinstance(error, Mapping) else None
    if mapped is GuardError:
        raise GuardError(message, payload=payload)
    raise mapped(message, payload=payload)


class McpBrowserClient(AppMcpBrowserClient):
    """The shared client with the crawl's typed error surface.

    The transport and the MCP session are the shared implementation; this
    subclass only maps the app-layer errors onto the crawl's session errors,
    so the engine keeps its typed stop reasons.
    """

    def start(self, name, *, url=None, context_ref=None):
        try:
            start = super().start(
                name, url=url, context_ref=context_ref
            )
        except AppBrowserUnavailable as exc:
            raise BrowserUnavailable(str(exc)) from exc
        except AppBrowserMcpError as exc:
            raise_for_mcp_error(
                {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                    "recovery": exc.recovery,
                }
            )
            raise  # pragma: no cover
        if not start.cdp_url or not start.cdp_host:
            raise McpBrowserError("browser_start carried no CDP endpoint")
        return start

    def exec(self, command):
        try:
            return super().exec(command)
        except AppBrowserUnavailable as exc:
            raise BrowserUnavailable(str(exc)) from exc
        except AppBrowserMcpError as exc:
            raise_for_mcp_error(
                {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                    "recovery": exc.recovery,
                }
            )
            raise  # pragma: no cover

    def end(self, *, persist_context=False):
        try:
            return super().end(persist_context=persist_context)
        except AppBrowserUnavailable as exc:
            raise BrowserUnavailable(str(exc)) from exc
        except AppBrowserMcpError as exc:
            if exc.code == "session_still_live":
                raise SessionStillLive(str(exc)) from exc
            raise_for_mcp_error(
                {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                    "recovery": exc.recovery,
                }
            )
            raise  # pragma: no cover


def _mapped_call(call):
    """Run one app-client call and map its typed failures to crawl errors."""
    try:
        return call()
    except AppBrowserUnavailable as exc:
        raise BrowserUnavailable(str(exc)) from exc
    except AppBrowserMcpError as exc:
        raise_for_mcp_error(
            {
                "code": exc.code,
                "message": str(exc),
                "retryable": exc.retryable,
                "recovery": exc.recovery,
            }
        )
        raise  # pragma: no cover - raise_for_mcp_error always raises


class McpBackend:
    """The session-client backend over one shared `McpBrowserClient`."""

    def __init__(
        self,
        client: McpBrowserClient,
        *,
        context_ref: str | None = None,
    ) -> None:
        self._client = client
        self._context_ref = context_ref
        self._registry = SteelSessionRegistry()

    @property
    def registry(self) -> SteelSessionRegistry:
        return self._registry

    def start(
        self, name: str, *, context_ref: str | None = None
    ) -> StartResult:
        start = _mapped_call(
            lambda: self._client.start(
                name, context_ref=context_ref or self._context_ref
            )
        )
        if not start.cdp_url or not start.cdp_host:
            raise McpBrowserError("browser_start carried no CDP endpoint")
        session = SteelSession.from_mcp(
            name=start.name,
            session_id=start.session_id,
            cdp_url=start.cdp_url,
            cdp_host=start.cdp_host,
            remaining_ms=start.remaining_ms,
        )
        self._registry.observe_start(session)
        return StartResult(
            session=session,
            restored=dict(start.restored),
            cdp_url=start.cdp_url,
            cdp_host=start.cdp_host,
            warnings=start.warnings,
            remaining_ms=start.remaining_ms,
        )

    def command(self, verb: str, *args: str) -> list[str]:
        if verb == "start":
            raise InvalidCommand("the crawl mounts a session through browser_start")
        return [verb, *args]

    def exec(self, command: Sequence[str]) -> Mapping[str, Any]:
        return _mapped_call(lambda: self._client.exec(command))

    def end(self) -> Mapping[str, Any]:
        report = dict(
            _mapped_call(lambda: self._client.end(persist_context=False))
        )
        report["state_managed"] = True
        return report

    def close(self) -> None:
        self._client.close()
