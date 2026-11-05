#!/usr/bin/env python3
"""Relay the pool worker ports onto the browser MCP's loopback.

The pool manager derives ``http://localhost:<published-port>`` worker URLs by
design. When the operator's SSH forward lands on the Docker host instead of
inside this container, that contract needs one bridge: this script listens on
both loopback families and relays each connection to
``<STEEL_POOL_FORWARD_HOST>:<port>``.

The worker API advertises its CDP websocket from ``DOMAIN``. The worker keeps
``DOMAIN=localhost:<port>``, so the CLI's Host header stays ``localhost`` and
the API's CDP proxy is accepted by Chrome. The relay preserves that byte for
byte; it never rewrites the Host header.

The script is stdlib-only, performs no I/O at import, and runs only when
``STEEL_POOL_FORWARD_PORTS`` is set.
"""
from __future__ import annotations

import asyncio
import os
import sys

BIND_HOSTS = ("127.0.0.1", "::1")


def forward_ports(raw: str) -> list[int]:
    """Parse the comma-separated worker ports and validate each one."""
    ports: list[int] = []
    for token in (raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            port = int(token)
        except ValueError as exc:
            raise ValueError(f"the forward port {token!r} is not an integer") from exc
        if not 0 < port < 65536:
            raise ValueError(f"the forward port {port} is out of range")
        ports.append(port)
    return ports


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    upstream_host: str,
    port: int,
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(
            upstream_host, port
        )
    except Exception as exc:  # noqa: BLE001 - a dead worker is a refused relay
        print(
            f"[forward] {port}: upstream {upstream_host}:{port} failed: {exc}",
            file=sys.stderr,
        )
        writer.close()
        return
    await asyncio.gather(
        _pipe(reader, upstream_writer),
        _pipe(upstream_reader, writer),
    )


async def _serve(host: str, port: int, upstream_host: str):
    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await _handle(reader, writer, upstream_host=upstream_host, port=port)

    try:
        server = await asyncio.start_server(handler, host, port)
    except OSError as exc:
        print(f"[forward] {host}:{port} not bound: {exc}", file=sys.stderr)
        return None
    print(f"[forward] {host}:{port} -> {upstream_host}:{port}", file=sys.stderr)
    return server


async def _run(ports: list[int], upstream_host: str) -> int:
    servers = []
    for port in ports:
        for bind in BIND_HOSTS:
            server = await _serve(bind, port, upstream_host)
            if server is not None:
                servers.append(server)
    if not servers:
        print("[forward] no listener was bound", file=sys.stderr)
        return 1
    try:
        await asyncio.gather(*(server.serve_forever() for server in servers))
    finally:
        for server in servers:
            server.close()
    return 0


def main() -> int:
    try:
        ports = forward_ports(os.environ.get("STEEL_POOL_FORWARD_PORTS", ""))
    except ValueError as exc:
        print(f"[forward] {exc}", file=sys.stderr)
        return 2
    if not ports:
        print("[forward] STEEL_POOL_FORWARD_PORTS unset; no forward", file=sys.stderr)
        return 0
    upstream_host = (
        os.environ.get("STEEL_POOL_FORWARD_HOST") or "host.docker.internal"
    ).strip()
    if not upstream_host:
        print("[forward] STEEL_POOL_FORWARD_HOST is empty", file=sys.stderr)
        return 2
    return asyncio.run(_run(ports, upstream_host))


if __name__ == "__main__":
    raise SystemExit(main())
