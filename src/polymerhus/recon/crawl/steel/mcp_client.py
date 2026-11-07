"""The crawl's synchronous MCP client for the browser pool.

The browser MCP is the only executor the crawl may address. This client holds
one MCP session for the whole crawl, so the lease the server mounts on
``browser_start`` stays with this client until ``browser_end``.

The crawl engine is synchronous, so the client owns one private asyncio loop
thread and submits every tool call to it. The loop is started lazily and
closed once, which keeps imports free of I/O and keeps a dropped crawl from
leaving an MCP session behind.

Error contract: an MCP tool error code maps to the crawler's typed session
error. A command-level CLI envelope keeps the CLI's own code. A transport
failure is ``BrowserUnavailable``. The client never invents a success.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
import json
import shlex
import threading
from typing import Any
from urllib.parse import urlsplit

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

# The browser MCP's own codes. A code outside both tables is a CommandFailed;
# the envelope's error is authoritative over any transport result.
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
]


class McpBrowserError(SteelSessionError):
    """The browser MCP returned a payload that violates its contract."""

    code = "mcp_protocol_error"
    default_message = "the browser MCP returned an invalid payload"


@dataclass(frozen=True)
class McpStart:
    """The fields one ``browser_start`` call returns to the crawl."""

    name: str
    session_id: str
    restored: dict[str, Any]
    cdp_url: str
    cdp_host: str
    warnings: tuple[str, ...] = ()
    remaining_ms: int | None = None


def _error_code(error: object) -> tuple[str, str]:
    if isinstance(error, Mapping):
        return str(error.get("code") or ""), str(error.get("message") or "")
    if isinstance(error, str):
        return error, ""
    return "", ""


def raise_for_mcp_error(error: object) -> None:
    """Raise the typed error for one MCP error object."""
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


def _result_data(result: object) -> Mapping[str, Any]:
    """Read the structured payload, falling back to the text content block."""
    data = getattr(result, "data", None)
    if isinstance(data, Mapping):
        return data
    for block in getattr(result, "content", None) or ():
        text = getattr(block, "text", None)
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, Mapping):
            return parsed
    raise McpBrowserError("the browser MCP returned no object")


class McpBrowserClient:
    """One persistent MCP session over the streamable-HTTP transport."""

    def __init__(
        self,
        url: str,
        *,
        client_factory=None,
        timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
        close_timeout_s: float = DEFAULT_CLOSE_TIMEOUT_S,
    ) -> None:
        parsed = urlsplit((url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("the browser MCP URL must be an http(s) origin")
        if timeout_s <= 0:
            raise ValueError("the browser MCP call timeout must be positive")
        if close_timeout_s <= 0:
            raise ValueError("the browser MCP close timeout must be positive")
        self._url = url.strip()
        self._client_factory = client_factory
        self._timeout_s = timeout_s
        self._close_timeout_s = close_timeout_s
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Any = None

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def start(self, name: str) -> McpStart:
        data = self._call("browser_start", {"name": name})
        session = data.get("session")
        if not isinstance(session, Mapping):
            raise McpBrowserError("browser_start carried no session object")
        session_name = session.get("name")
        session_id = session.get("session_id")
        if not isinstance(session_name, str) or not session_name:
            raise McpBrowserError("browser_start carried no session name")
        if not isinstance(session_id, str) or not session_id:
            raise McpBrowserError("browser_start carried no session id")
        cdp_url = data.get("cdp_url")
        cdp_host = data.get("cdp_host")
        if not isinstance(cdp_url, str) or not cdp_url:
            raise McpBrowserError("browser_start carried no CDP URL")
        if not isinstance(cdp_host, str) or not cdp_host:
            raise McpBrowserError("browser_start carried no CDP Host")
        restored = data.get("restored")
        remaining = data.get("remaining_ms")
        return McpStart(
            name=session_name,
            session_id=session_id,
            restored=dict(restored) if isinstance(restored, Mapping) else {},
            cdp_url=cdp_url,
            cdp_host=cdp_host,
            warnings=tuple(str(item) for item in data.get("warnings") or ()),
            remaining_ms=remaining if isinstance(remaining, int) else None,
        )

    def exec(self, command: Sequence[str]) -> Mapping[str, Any]:
        if isinstance(command, (str, bytes)) or not command:
            raise ValueError("a browser command is required")
        if any(not isinstance(item, str) for item in command):
            raise ValueError("a browser command argument is not a string")
        return self._call("browser_exec", {"command": shlex.join(list(command))})

    def end(self) -> Mapping[str, Any]:
        data = self._call_raw("browser_end", {})
        if data.get("success") is False:
            if not data.get("stopped") and data.get("released") is None:
                raise SessionStillLive(
                    "the browser session was neither stopped nor released"
                )
            if data.get("released") is False:
                # The API reported the session already gone: the lease is
                # released even though this call did not release it.
                return data
            raise_for_mcp_error(data.get("error"))
        return data

    def close(self) -> None:
        """Exit the MCP session and stop the private loop. Idempotent."""
        with self._lock:
            loop = self._loop
            thread = self._thread
            self._loop = None
            self._thread = None
        if loop is None or thread is None:
            return
        try:
            self._submit(self._close_session(), loop, self._close_timeout_s)
        except Exception:  # noqa: BLE001 - close is best-effort
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        thread.join(timeout=self._close_timeout_s)

    # ------------------------------------------------------------------
    # Async plumbing
    # ------------------------------------------------------------------

    async def _open_session(self) -> None:
        if self._client_factory is not None:
            client = self._client_factory()
        else:
            from fastmcp import Client  # noqa: PLC0415

            client = Client(self._url)
        self._client = await client.__aenter__()

    async def _close_session(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.__aexit__(None, None, None)

    def _ensure_open(self) -> None:
        with self._lock:
            if self._loop is not None:
                return
            loop = asyncio.new_event_loop()
            ready = threading.Event()
            failure: list[BaseException] = []

            def run() -> None:
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()

            thread = threading.Thread(
                target=run, name="steel-mcp-client", daemon=True
            )
            thread.start()
            if not ready.wait(10):
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=5)
                raise BrowserUnavailable("the MCP client loop did not start")
            self._loop = loop
            self._thread = thread
            try:
                self._submit(self._open_session(), loop, self._timeout_s)
            except BaseException as exc:  # noqa: BLE001 - started nowhere
                self._loop = None
                self._thread = None
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=5)
                if isinstance(exc, SteelSessionError):
                    raise
                if isinstance(exc, (BrowserUnavailable, ValueError)):
                    raise
                raise BrowserUnavailable(
                    f"the browser MCP session could not open: {exc}"
                ) from exc

    def _call(self, name: str, arguments: dict[str, Any]) -> Mapping[str, Any]:
        data = self._call_raw(name, arguments)
        if data.get("success") is False:
            raise_for_mcp_error(data.get("error"))
        return data

    def _call_raw(
        self, name: str, arguments: dict[str, Any]
    ) -> Mapping[str, Any]:
        self._ensure_open()
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None or not thread.is_alive():
            raise BrowserUnavailable("the browser MCP session is not running")
        result = self._submit(
            self._client.call_tool(name, arguments), loop, self._timeout_s
        )
        if getattr(result, "is_error", False):
            raise BrowserUnavailable(
                f"the browser MCP tool {name!r} reported a transport error"
            )
        return _result_data(result)

    @staticmethod
    def _submit(
        coroutine,
        loop: asyncio.AbstractEventLoop,
        timeout_s: float,
    ) -> Any:
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        except RuntimeError as exc:
            raise BrowserUnavailable(
                "the browser MCP session loop is closed"
            ) from exc
        try:
            return future.result(timeout_s)
        except (FutureTimeout, TimeoutError) as exc:
            future.cancel()
            raise BrowserUnavailable(
                f"the browser MCP call did not answer within {timeout_s}s"
            ) from exc
        except SteelSessionError:
            raise
        except Exception as exc:  # noqa: BLE001 - one typed transport failure
            raise BrowserUnavailable(
                f"the browser MCP call failed: {type(exc).__name__}: {exc}"
            ) from exc


class McpBackend:
    """The session-client backend over one `McpBrowserClient`.

    The MCP speaks the bare browser grammar, so `command` never adds the CLI's
    session flags. The registry observes the start for the `session_missing`
    distinction; the MCP server still owns the lease.
    """

    def __init__(self, client: McpBrowserClient) -> None:
        self._client = client
        self._registry = SteelSessionRegistry()

    @property
    def registry(self) -> SteelSessionRegistry:
        return self._registry

    def start(self, name: str) -> StartResult:
        start = self._client.start(name)
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
        return self._client.exec(command)

    def end(self) -> Mapping[str, Any]:
        report = dict(self._client.end())
        report["state_managed"] = True
        return report

    def close(self) -> None:
        self._client.close()
