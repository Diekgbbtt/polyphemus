"""A transparent TCP forwarder for the #196 WAF fixture.

The OWASP ModSecurity CRS image deliberately refuses to bind a privileged port
(it runs unprivileged and tells you to map "80:8080"). The capture plane's
transparent REDIRECT, however, only covers tcp/80 and tcp/443 inside a lease - so
the WAF must be *reachable on port 80 inside the compose network*, or it would
never be captured.

This front does exactly that and nothing else: raw TCP in, raw TCP out. No HTTP
parsing, no header rewriting - the WAF in front of us stays the authority on what
the client sees.
"""
from __future__ import annotations

import os
import select
import socket

LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "80"))
UPSTREAM_HOST = os.environ["UPSTREAM_HOST"]
UPSTREAM_PORT = int(os.environ.get("UPSTREAM_PORT", "8080"))


def _pump(src: socket.socket, dst: socket.socket) -> bool:
    chunk = src.recv(65536)
    if not chunk:
        return False
    dst.sendall(chunk)
    return True


def _serve(client: socket.socket) -> None:
    with socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=10) as upstream:
        sockets = [client, upstream]
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 30)
            if errored:
                return
            if not readable:
                return  # idle: drop, the WAF front is stateless
            for src in readable:
                dst = upstream if src is client else client
                if not _pump(src, dst):
                    return


def main() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(64)
    while True:
        client, _peer = server.accept()
        try:
            _serve(client)
        except OSError:
            pass
        finally:
            client.close()


if __name__ == "__main__":
    main()
