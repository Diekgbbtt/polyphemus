"""The per-replica HTTP and WebSocket reverse proxy.

The Steel API builds its session ``websocketUrl`` from ``DOMAIN`` and forwards
the client's ``Host`` to Chrome, which rejects a non-localhost host. The CLI
also insists on a loopback API origin. This proxy reconciles both: it binds one
loopback port per replica, forwards every request to the worker's container
address, keeps the client's localhost Host, and rewrites the session create
response's ``websocketUrl`` to the proxy's own origin.

The proxy is deliberately small: plain HTTP/1.1 with one request per
connection, and WebSocket upgrade passthrough. It never synthesises a browser
action and never changes a response other than the one documented rewrite.

The module is stdlib-only and performs no I/O at import.
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
import json
import socket
import threading
from typing import Any

try:  # package layout
    from kali.steel_pool.pool import Worker
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.pool import Worker  # type: ignore[no-redef]

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
UPSTREAM_TIMEOUT_S = 30.0
MAX_HEADER_BYTES = 65536
MAX_BODY_BYTES = 2**24
_WEBSOCKET_URL = "websocketUrl"

__all__ = ["LOOPBACK_HOSTS", "ProxyError", "WorkerProxy"]


class ProxyError(RuntimeError):
    """The reverse proxy could not start, stop, or forward a request."""


def _header_lines(head: bytes) -> tuple[str, list[tuple[str, str]]]:
    lines = head.decode("latin-1").split("\r\n")
    if not lines or not lines[0]:
        raise ProxyError("the request carries no request line")
    return lines[0], [
        (name.strip(), value.strip())
        for name, _, value in (
            line.partition(":") for line in lines[1:] if ":" in line
        )
    ]


def _header_value(headers: Sequence[tuple[str, str]], name: str) -> str:
    wanted = name.lower()
    for header, value in headers:
        if header.lower() == wanted:
            return value
    return ""


def _has_websocket_upgrade(headers: Sequence[tuple[str, str]]) -> bool:
    connection = _header_value(headers, "connection").lower()
    upgrade = _header_value(headers, "upgrade").lower()
    return "upgrade" in connection.split(",") and upgrade == "websocket"


async def _read_head(reader: asyncio.StreamReader) -> tuple[bytes, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(4096)
        if not chunk:
            return data, b""
        data += chunk
        if len(data) > MAX_HEADER_BYTES:
            raise ProxyError("the request head is too large")
    head, _, rest = data.partition(b"\r\n\r\n")
    return head, rest


async def _read_body(
    reader: asyncio.StreamReader, headers: Sequence[tuple[str, str]], initial: bytes
) -> bytes:
    raw_length = _header_value(headers, "content-length")
    if not raw_length:
        return initial
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ProxyError("the request content length is not an integer") from exc
    if length < 0 or length > MAX_BODY_BYTES:
        raise ProxyError("the request body is out of range")
    body = initial
    while len(body) < length:
        chunk = await reader.read(length - len(body))
        if not chunk:
            break
        body += chunk
    return body[:length]


def _upstream_head(
    request_line: str, headers: Sequence[tuple[str, str]]
) -> bytes:
    lines = [request_line]
    for name, value in headers:
        if name.lower() in {"connection", "proxy-connection"}:
            continue
        lines.append(f"{name}: {value}")
    lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


class _Buffered:
    """A reader that never loses the bytes already read past the head."""

    def __init__(
        self, reader: asyncio.StreamReader, initial: bytes
    ) -> None:
        self._reader = reader
        self._buffer = bytearray(initial)

    async def readline(self) -> bytes:
        while b"\n" not in self._buffer:
            chunk = await self._reader.read(4096)
            if not chunk:
                break
            self._buffer.extend(chunk)
        index = self._buffer.find(b"\n")
        if index < 0:
            data = bytes(self._buffer)
            self._buffer.clear()
            return data
        data = bytes(self._buffer[: index + 1])
        del self._buffer[: index + 1]
        return data

    async def readexactly(self, size: int) -> bytes:
        while len(self._buffer) < size:
            chunk = await self._reader.read(size - len(self._buffer))
            if not chunk:
                raise asyncio.IncompleteReadError(bytes(self._buffer), size)
            self._buffer.extend(chunk)
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    async def read(self) -> bytes:
        data = bytes(self._buffer)
        self._buffer.clear()
        return data + await self._reader.read()


async def _read_chunked(reader: _Buffered) -> bytes:
    body = bytearray()
    while True:
        line = await reader.readline()
        if not line:
            raise ProxyError("the chunked response ended without a terminator")
        token = line.split(b";", 1)[0].strip()
        try:
            size = int(token, 16)
        except ValueError as exc:
            raise ProxyError("the chunk size is not hexadecimal") from exc
        if size == 0:
            while True:
                trailer = await reader.readline()
                if trailer in (b"\r\n", b"\n", b""):
                    return bytes(body)
        body.extend(await reader.readexactly(size))
        terminator = await reader.readexactly(2)
        if terminator != b"\r\n":
            raise ProxyError("the chunk terminator is malformed")
        if len(body) > MAX_BODY_BYTES:
            raise ProxyError("the response body is too large")


async def _read_response(
    reader: asyncio.StreamReader,
) -> tuple[int, list[tuple[str, str]], bytes]:
    head, rest = await _read_head(reader)
    if not head:
        raise ProxyError("the upstream returned no response")
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise ProxyError("the upstream response line is malformed")
    status = int(parts[1])
    headers = [
        (name.strip(), value.strip())
        for name, _, value in (
            line.partition(":") for line in lines[1:] if ":" in line
        )
    ]
    buffered = _Buffered(reader, rest)
    if "chunked" in _header_value(headers, "transfer-encoding").lower():
        return status, headers, await _read_chunked(buffered)
    raw_length = _header_value(headers, "content-length")
    if raw_length:
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ProxyError("the upstream content length is not an integer") from exc
        try:
            body = await buffered.readexactly(length)
        except asyncio.IncompleteReadError as exc:
            body = exc.partial
        return status, headers, body
    return status, headers, await buffered.read()


def _rewrite_body(body: bytes, public_port: int) -> bytes:
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return body
    if not isinstance(payload, dict):
        return body
    url = payload.get(_WEBSOCKET_URL)
    if isinstance(url, str) and url.startswith(("ws://", "wss://")):
        payload[_WEBSOCKET_URL] = f"ws://localhost:{public_port}/"
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return body


def _response_bytes(
    status: int,
    headers: Sequence[tuple[str, str]],
    body: bytes,
) -> bytes:
    lines = [f"HTTP/1.1 {status} {_reason(status)}"]
    for name, value in headers:
        if name.lower() in {"connection", "content-length", "transfer-encoding"}:
            continue
        lines.append(f"{name}: {value}")
    lines.append(f"Content-Length: {len(body)}")
    lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def _reason(status: int) -> str:
    return {
        101: "Switching Protocols",
        200: "OK",
        201: "Created",
        204: "No Content",
        400: "Bad Request",
        404: "Not Found",
        502: "Bad Gateway",
    }.get(status, "OK")


def _error_response(code: str, message: str) -> bytes:
    body = json.dumps(
        {"success": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    ).encode("utf-8")
    return _response_bytes(502, [("Content-Type", "application/json")], body)


class WorkerProxy:
    """One loopback listener forwarding to one worker's container address."""

    def __init__(self, worker: Worker, *, bind_host: str = "127.0.0.1") -> None:
        if bind_host not in LOOPBACK_HOSTS:
            raise ValueError("the reverse proxy bind host must be loopback")
        self._worker = worker
        self._bind_host = bind_host
        self._port = worker.public_port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._started = False

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        return f"http://localhost:{self._port}"

    def start(self) -> None:
        if self._started:
            raise ProxyError("the reverse proxy is already started")
        loop = asyncio.new_event_loop()
        ready = threading.Event()
        failure: list[BaseException] = []

        def serve() -> None:
            asyncio.set_event_loop(loop)

            async def boot() -> None:
                try:
                    self._server = await asyncio.start_server(
                        self._handle,
                        self._bind_host,
                        self._port,
                        backlog=64,
                    )
                except BaseException as exc:  # noqa: BLE001 - surfaced to start()
                    failure.append(exc)
                finally:
                    ready.set()

            loop.create_task(boot())
            loop.run_forever()

        thread = threading.Thread(
            target=serve,
            name=f"steel-proxy-{self._worker.container_name}",
            daemon=True,
        )
        thread.start()
        if not ready.wait(10):
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            raise ProxyError("the reverse proxy did not bind within 10s")
        if failure:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            raise ProxyError(f"the reverse proxy could not bind: {failure[0]}")
        self._loop = loop
        self._thread = thread
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        loop, thread, server = self._loop, self._thread, self._server
        self._started = False
        self._loop = None
        self._thread = None
        self._server = None
        if loop is None or thread is None:
            return

        async def shutdown() -> None:
            if server is not None:
                server.close()
                await server.wait_closed()
            for writer in list(self._writers):
                try:
                    writer.close()
                except Exception:  # noqa: BLE001 - stop is best-effort
                    pass
            self._writers.clear()
            loop.stop()

        try:
            loop.call_soon_threadsafe(lambda: loop.create_task(shutdown()))
        except RuntimeError:
            return
        thread.join(timeout=10)

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        try:
            head, rest = await _read_head(reader)
            if not head:
                return
            request_line, headers = _header_lines(head)
            if _has_websocket_upgrade(headers):
                await self._websocket(reader, writer, head, rest)
                return
            body = await _read_body(reader, headers, rest)
            await self._http(writer, request_line, headers, body)
        except (ProxyError, OSError, asyncio.IncompleteReadError):
            if not writer.is_closing():
                writer.write(
                    _error_response(
                        "proxy_upstream_unavailable",
                        "the Steel worker request could not be completed",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - one request never kills the proxy
            if not writer.is_closing():
                writer.write(
                    _error_response(
                        "proxy_internal_error",
                        f"the reverse proxy failed: {type(exc).__name__}: {exc}",
                    )
                )
        finally:
            self._writers.discard(writer)
            try:
                await writer.drain()
            except Exception:  # noqa: BLE001 - the peer may be gone
                pass
            writer.close()

    async def _http(
        self,
        writer: asyncio.StreamWriter,
        request_line: str,
        headers: Sequence[tuple[str, str]],
        body: bytes,
    ) -> None:
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self._worker.container_ip, self._worker.api_port
                ),
                timeout=UPSTREAM_TIMEOUT_S,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise ProxyError(f"the Steel worker is unreachable: {exc}") from exc
        try:
            upstream_writer.write(_upstream_head(request_line, headers))
            if body:
                upstream_writer.write(body)
            await upstream_writer.drain()
            status, response_headers, response_body = await asyncio.wait_for(
                _read_response(upstream_reader), timeout=UPSTREAM_TIMEOUT_S
            )
        finally:
            upstream_writer.close()
        content_type = _header_value(response_headers, "content-type").lower()
        if (
            200 <= status < 300
            and "application/json" in content_type
            and response_body
        ):
            response_body = _rewrite_body(response_body, self._port)
        writer.write(_response_bytes(status, response_headers, response_body))
        await writer.drain()

    async def _websocket(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        head: bytes,
        rest: bytes,
    ) -> None:
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self._worker.container_ip, self._worker.api_port
                ),
                timeout=UPSTREAM_TIMEOUT_S,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise ProxyError(f"the Steel worker is unreachable: {exc}") from exc
        upstream_writer.write(head + b"\r\n\r\n" + rest)
        await upstream_writer.drain()

        async def pipe(
            source: asyncio.StreamReader, target: asyncio.StreamWriter
        ) -> None:
            try:
                while True:
                    chunk = await source.read(65536)
                    if not chunk:
                        break
                    target.write(chunk)
                    await target.drain()
            except (OSError, asyncio.IncompleteReadError):
                pass
            finally:
                try:
                    target.write_eof()
                except (OSError, RuntimeError):
                    pass

        upstream = asyncio.ensure_future(pipe(reader, upstream_writer))
        downstream = asyncio.ensure_future(pipe(upstream_reader, writer))
        try:
            await asyncio.wait(
                {upstream, downstream}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (upstream, downstream):
                task.cancel()
            upstream_writer.close()
            await asyncio.gather(upstream, downstream, return_exceptions=True)
