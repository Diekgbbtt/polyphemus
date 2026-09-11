"""In-container TCP relay: 0.0.0.0:14000 -> 127.0.0.1:4000 (the gateway).

Stdlib only. Runs detached inside the agent container so the scaffolded
port forwarding (docker-compose.probe.yml, host 14000 -> container 14000)
reaches the loopback-bound gateway. Dies with the container; re-run after
any recreate:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml \\
      -f docker-compose.e2e.yml -f docker-compose.probe.yml \\
      exec -d agent python -c \"$(cat tools/gateway_relay.py)\"
"""

import socket
import threading


def _pipe(source, target):
    try:
        while True:
            chunk = source.recv(65536)
            if not chunk:
                break
            target.sendall(chunk)
    except OSError:
        pass
    finally:
        for sock in (source, target):
            try:
                sock.close()
            except OSError:
                pass


def main():
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 14000))
    server.listen(50)
    while True:
        client, _ = server.accept()
        try:
            upstream = socket.create_connection(("127.0.0.1", 4000))
        except OSError:
            client.close()
            continue
        for args in ((client, upstream), (upstream, client)):
            threading.Thread(target=_pipe, args=args, daemon=True).start()


main()
