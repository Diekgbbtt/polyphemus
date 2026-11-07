"""The synchronous client for the browser MCP.

One client owns one MCP session and one private asyncio loop. It is the
transport under `BrowserTool`; the crawl engine also uses it directly so both
the agent surface and the deterministic crawl share one client contract.

The client never invents a success. A typed MCP error raises
`BrowserMcpError`; a transport failure raises `BrowserUnavailable`. The caller
decides whether the failure is a degraded capability or a terminal stop.

The module imports no driver and performs no I/O at import.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
import json
import shlex
import threading
from typing import Any
from urllib.parse import urlsplit

DEFAULT_CALL_TIMEOUT_S = 330.0
DEFAULT_CLOSE_TIMEOUT_S = 10.0

__all__ = [
    "BrowserMcpError",
    "BrowserStart",
    "BrowserUnavailable",
    "DEFAULT_CALL_TIMEOUT_S",
    "DEFAULT_CLOSE_TIMEOUT_S",
    "McpBrowserClient",
]


class BrowserUnavailable(RuntimeError):
    """The browser MCP or the worker pool is unreachable or exhausted."""

    def __init__(self, message: str, *, code: str = "browser_unavailable") -> None:
        super().__init__(message)
        self.code = code
        self.retryable = True


class BrowserMcpError(RuntimeError):
    """The browser MCP returned a typed error envelope."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "browser_error",
        retryable: bool = False,
        recovery: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.recovery = recovery
        self.payload = dict(payload) if isinstance(payload, Mapping) else None


@dataclass(frozen=True)
class BrowserStart:
    """The model-safe fields one `browser_start` returns."""

    name: str
    session_id: str
    restored: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    remaining_ms: int | None = None
    context_ref: str | None = None
    cdp_url: str = ""
    cdp_host: str = ""


def _error_shape(error: object) -> tuple[str, str, bool, str | None]:
    if isinstance(error, Mapping):
        return (
            str(error.get("code") or "browser_error"),
            str(error.get("message") or ""),
            bool(error.get("retryable", False)),
            error.get("recovery") if isinstance(error.get("recovery"), str) else None,
        )
    if isinstance(error, str):
        return error or "browser_error", "", False, None
    return "browser_error", "", False, None


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
    raise BrowserUnavailable("the browser MCP returned no object")


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

    def start(
        self,
        name: str,
        *,
        url: str | None = None,
        context_ref: str | None = None,
    ) -> BrowserStart:
        arguments: dict[str, Any] = {"name": name}
        if url is not None:
            arguments["url"] = url
        if context_ref is not None:
            arguments["context_ref"] = context_ref
        data = self._call("browser_start", arguments)
        session = data.get("session")
        if not isinstance(session, Mapping):
            raise BrowserUnavailable("browser_start carried no session object")
        session_name = session.get("name")
        session_id = session.get("session_id")
        if not isinstance(session_name, str) or not session_name:
            raise BrowserUnavailable("browser_start carried no session name")
        if not isinstance(session_id, str) or not session_id:
            raise BrowserUnavailable("browser_start carried no session id")
        restored = data.get("restored")
        remaining = data.get("remaining_ms")
        cdp_url = data.get("cdp_url")
        cdp_host = data.get("cdp_host")
        return BrowserStart(
            name=session_name,
            session_id=session_id,
            restored=dict(restored) if isinstance(restored, Mapping) else {},
            warnings=tuple(str(item) for item in data.get("warnings") or ()),
            remaining_ms=remaining if isinstance(remaining, int) else None,
            context_ref=context_ref,
            cdp_url=cdp_url if isinstance(cdp_url, str) else "",
            cdp_host=cdp_host if isinstance(cdp_host, str) else "",
        )

    def exec(self, command: str | Sequence[str]) -> Mapping[str, Any]:
        if isinstance(command, (str, bytes)):
            text = command if isinstance(command, str) else command.decode("utf-8")
        else:
            if not command:
                raise ValueError("a browser command is required")
            if any(not isinstance(item, str) for item in command):
                raise ValueError("a browser command argument is not a string")
            text = shlex.join(list(command))
        if not text.strip():
            raise ValueError("a browser command is required")
        return self._call("browser_exec", {"command": text})

    def end(self, *, persist_context: bool = False) -> Mapping[str, Any]:
        arguments = {"persist_context": True} if persist_context else {}
        data = self._call_raw("browser_end", arguments)
        if data.get("success") is False:
            if not data.get("stopped") and data.get("released") is None:
                raise BrowserMcpError(
                    "the browser session was neither stopped nor released",
                    code="session_still_live",
                    retryable=False,
                )
            if data.get("released") is False:
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

            def run() -> None:
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()

            thread = threading.Thread(
                target=run, name="browser-mcp-client", daemon=True
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
                if isinstance(exc, (BrowserUnavailable, BrowserMcpError, ValueError)):
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
        except (BrowserMcpError, BrowserUnavailable):
            raise
        except Exception as exc:  # noqa: BLE001 - one typed transport failure
            raise BrowserUnavailable(
                f"the browser MCP call failed: {type(exc).__name__}: {exc}"
            ) from exc


def raise_for_mcp_error(error: object) -> None:
    """Raise the typed error for one MCP error object."""
    code, message, retryable, recovery = _error_shape(error)
    if not message:
        message = f"the browser MCP reported {code}"
    raise BrowserMcpError(
        message,
        code=code,
        retryable=retryable,
        recovery=recovery,
        payload=dict(error) if isinstance(error, Mapping) else None,
    )
