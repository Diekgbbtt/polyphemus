"""Probe the Steel API endpoint as the browser CDP channel.

The client connects to the Steel API's own WebSocket endpoint, sends a single
``Host: localhost`` header, attaches to the page target, enables Network, and
navigates through the commands API. It then prints the network events.

This avoids both the 9223 nginx proxy and the direct 9222 port. Chrome binds
127.0.0.1:9222, so the API endpoint is the only reachable CDP route from
another container or host.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import threading
import time
import urllib.request


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError("socket closed")
        data += chunk
    return data


def send_text(sock: socket.socket, text: str) -> None:
    payload = text.encode()
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", length)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    first, second = recv_exact(sock, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]
    mask = recv_exact(sock, 4) if second & 0x80 else None
    payload = recv_exact(sock, length)
    if mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


def call(
    sock: socket.socket,
    ident: int,
    method: str,
    params: dict | None = None,
    session: str | None = None,
) -> dict:
    message: dict = {"id": ident, "method": method}
    if params is not None:
        message["params"] = params
    if session:
        message["sessionId"] = session
    send_text(sock, json.dumps(message))
    while True:
        opcode, payload = recv_frame(sock)
        if opcode != 1:
            continue
        reply = json.loads(payload)
        if reply.get("id") == ident:
            return reply


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-port", type=int, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--page", default="")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    key = base64.b64encode(os.urandom(16)).decode()
    sock = socket.create_connection(("127.0.0.1", args.api_port), 5)
    request = (
        "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(4096)
    print(head.split(b"\r\n")[0].decode(), flush=True)

    targets = call(sock, 1, "Target.getTargets")["result"]["targetInfos"]
    pages = [target for target in targets if target.get("type") == "page"]
    page = next(
        (target for target in pages if target.get("targetId") == args.page),
        pages[0],
    )
    print("PAGE", page.get("targetId"), page.get("url"), flush=True)
    attached = call(
        sock,
        2,
        "Target.attachToTarget",
        {"targetId": page["targetId"], "flatten": True},
    )
    session = attached["result"]["sessionId"]
    print("CDP_SESSION", session, flush=True)
    call(sock, 3, "Network.enable", {}, session)
    call(sock, 4, "Page.enable", {}, session)

    def navigate() -> None:
        body = json.dumps(
            {"commands": [{"command": "navigate", "url": args.url}]}
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.api_port}/v1/sessions/{args.session}/commands",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            print("NAV", urllib.request.urlopen(request, timeout=30).status, flush=True)
        except Exception as exc:  # noqa: BLE001 - probe reports and exits
            print("NAV_ERR", exc, flush=True)

    threading.Thread(target=navigate, daemon=True).start()
    sock.settimeout(2)
    seen = 0
    deadline = time.time() + args.timeout
    while time.time() < deadline and seen < 8:
        try:
            opcode, payload = recv_frame(sock)
        except socket.timeout:
            continue
        if opcode != 1:
            continue
        message = json.loads(payload)
        method = message.get("method")
        if method in (
            "Network.requestWillBeSent",
            "Network.responseReceived",
            "Page.frameNavigated",
        ):
            params = message.get("params", {})
            url = (
                params.get("request", {}).get("url")
                or params.get("response", {}).get("url")
                or params.get("frame", {}).get("url")
            )
            print("EVENT", method, url, flush=True)
            seen += 1
    sock.close()


if __name__ == "__main__":
    main()
