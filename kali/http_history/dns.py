"""A resolver the LEASED namespaces can actually reach.

Docker writes ``nameserver 127.0.0.11`` into the container's
``/etc/resolv.conf``: that is Docker's embedded resolver, listening on the
CONTAINER's loopback. A lease namespace has its own loopback, so copying that
file verbatim (what the backend used to do) leaves every system-resolver client
inside the lease resolving nothing - observed live 2026-09-17 in a leased
namespace: ``curl: (6) Could not resolve host: example.com``, ``getent hosts``
and ``socket.gethostbyname`` failing the same way. The recon tools papered over
it because httpx/katana carry their own resolver list, but the replay sender
(``curl`` in the lease) and every other client do not.

The fix has two halves:

* ``lease_resolv_conf`` writes the namespace its own ``/etc/resolv.conf`` (the
  ``ip netns exec`` wrapper bind-mounts ``/etc/netns/<ns>/`` over ``/etc/``)
  whose FIRST nameserver is the lease's gateway - an address the namespace can
  reach;
* ``DnsForwarder`` listens on that gateway (per lease) and relays to the
  container's own resolver, so the lease gets the SAME answers the container
  does: compose service names and public names, without weakening anything.

UDP only, deliberately: the queries a scanner issues are A/AAAA/PTR-sized and
the resolv.conf we write keeps EDNS0, so truncation-then-TCP is not a path these
jobs take. A truncated answer fails that one query, never the lease.
"""
from __future__ import annotations

import logging
import socket
import threading

logger = logging.getLogger(__name__)

#: Loopback and "any" addresses cannot answer from inside a child namespace.
_UNREACHABLE_PREFIXES = ("127.", "0.0.0.0")
_MAX_QUERY_BYTES = 4096


def lease_resolv_conf(parent_text: str, gateway_ip: str) -> str:
    """The resolver file for one lease namespace.

    The gateway goes first (it forwards to the container's resolver and knows
    both compose and public names), then any nameserver of the parent that is
    still reachable from the namespace. ``search``/``options`` are naming policy,
    not addresses, so they ride along untouched. Pure, so the policy is testable
    without a namespace.
    """
    nameservers: list[str] = []
    passthrough: list[str] = []
    for raw in (parent_text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) < 2:
                continue
            address = parts[1]
            if address.startswith(_UNREACHABLE_PREFIXES) or address == gateway_ip:
                continue
            nameservers.append(address)
        else:
            passthrough.append(line)
    lines = [f"nameserver {gateway_ip}", *(f"nameserver {ns}" for ns in nameservers), *passthrough]
    return "\n".join(lines) + "\n"


class DnsForwarder:
    """Relay UDP DNS from a lease gateway to the container's own resolver.

    One listener per gateway address, started on the first lease that uses it and
    stopped on release, so the socket never outlives the veth that carries it.
    A query that cannot be relayed is DROPPED (the client retries or falls
    through to the next nameserver) - never answered with a fabricated result.
    """

    def __init__(
        self,
        *,
        upstream_host: str = "127.0.0.11",
        upstream_port: int = 53,
        timeout_s: float = 5.0,
    ):
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.timeout_s = timeout_s
        self._listeners: dict[str, _Listener] = {}
        self._lock = threading.Lock()

    def bind(self, address: str, *, port: int = 53) -> int:
        """Serve ``address`` (idempotent per address); returns the bound port."""
        with self._lock:
            existing = self._listeners.get(address)
            if existing is not None:
                return existing.port
            listener = _Listener(
                address=address,
                port=port,
                upstream=(self.upstream_host, self.upstream_port),
                timeout_s=self.timeout_s,
            )
            listener.start()
            self._listeners[address] = listener
            return listener.port

    def unbind(self, address: str) -> bool:
        """Stop serving ``address``; True when a listener was actually stopped."""
        with self._lock:
            listener = self._listeners.pop(address, None)
        if listener is None:
            return False
        listener.stop()
        return True

    def is_alive(self, address: str) -> bool:
        with self._lock:
            listener = self._listeners.get(address)
        return bool(listener and listener.is_alive())

    def stop(self) -> None:
        with self._lock:
            listeners = list(self._listeners.values())
            self._listeners.clear()
        for listener in listeners:
            listener.stop()


class _Listener:
    """One UDP socket on a lease gateway, with its own relay thread."""

    def __init__(self, *, address: str, port: int, upstream: tuple[str, int], timeout_s: float):
        self.address = address
        self.upstream = upstream
        self.timeout_s = timeout_s
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((address, port))
        self._sock.settimeout(0.5)
        self.port = self._sock.getsockname()[1]
        self._stopping = threading.Event()
        self._thread = threading.Thread(
            target=self._serve, name=f"kali-dns-{address}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self) -> None:
        self._stopping.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                query, client = self._sock.recvfrom(_MAX_QUERY_BYTES)
            except socket.timeout:
                continue
            except OSError:
                return  # the socket was closed by stop()
            answer = self._relay(query)
            if answer is None:
                continue
            try:
                self._sock.sendto(answer, client)
            except OSError:
                continue

    def _relay(self, query: bytes) -> bytes | None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
            upstream.settimeout(self.timeout_s)
            try:
                upstream.sendto(query, self.upstream)
                answer, _peer = upstream.recvfrom(_MAX_QUERY_BYTES)
                return answer
            except OSError as exc:  # noqa: BLE001 - a dropped query, never a crash
                logger.debug("dns relay to %s failed: %s", self.upstream, exc)
                return None
