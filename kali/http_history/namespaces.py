"""Persistent network-namespace leases: one per concurrent MCP execution.

Each lease owns a unique veth source address, so the addon correlates a flow by
``source_ip`` rather than by a time window or command order. Commands that
belong to the same ``session_id`` are serialized; different sessions run
concurrently up to the pool size, after which acquisition applies explicit
backpressure (a bounded wait that raises ``PoolExhaustedError``).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

from kali.http_history.models import CaptureContext
from kali.http_history.registry import SourceRegistry

logger = logging.getLogger(__name__)


class PoolExhaustedError(RuntimeError):
    """The namespace pool stayed full for the whole acquire timeout."""


class SessionBusyError(RuntimeError):
    """The session already holds a lease that did not free in time."""


class NamespaceBackendError(RuntimeError):
    """The kernel refused to build the namespace/veth pair."""


@dataclass
class NamespaceLease:
    namespace: str
    source_ip: str
    session_id: str
    project_id: str
    slot: int
    expires_at: float
    handle: object | None = None
    metadata: dict = field(default_factory=dict)


class SubprocessBackend:
    """Real ``ip netns``/veth backend; transparent-routing rules are installed
    by ``entrypoint.sh``/``postrun.sh`` and re-asserted per lease here."""

    def __init__(self, *, proxy_port: int = 8080):
        self.proxy_port = proxy_port

    def create(self, namespace: str, source_ip: str) -> None:
        veth_host = f"vh{namespace[-6:]}"
        veth_ns = f"vn{namespace[-6:]}"
        last = int(source_ip.rsplit(".", 1)[-1])
        gateway_ip = f"{source_ip.rsplit('.', 1)[0]}.{last - 1}"
        self._run("ip", "netns", "add", namespace)
        try:
            self._run("ip", "link", "add", veth_host, "type", "veth", "peer", "name", veth_ns)
            self._run("ip", "link", "set", veth_ns, "netns", namespace)
            self._run("ip", "addr", "add", f"{gateway_ip}/30", "dev", veth_host)
            self._run("ip", "link", "set", veth_host, "up")
            self._run("ip", "-n", namespace, "addr", "add", f"{source_ip}/30", "dev", veth_ns)
            self._run("ip", "-n", namespace, "link", "set", veth_ns, "up")
            self._run("ip", "-n", namespace, "link", "set", "lo", "up")
            self._run("ip", "-n", namespace, "route", "add", "default", "via", gateway_ip)
            resolv_dir = f"/etc/netns/{namespace}"
            self._run("mkdir", "-p", resolv_dir)
            if os.path.exists("/etc/resolv.conf"):
                shutil.copy("/etc/resolv.conf", f"{resolv_dir}/resolv.conf")
            for port in (80, 443):
                self._run(
                    "iptables", "-t", "nat", "-A", "PREROUTING", "-i", veth_host,
                    "-p", "tcp", "--dport", str(port),
                    "-j", "REDIRECT", "--to-ports", str(self.proxy_port),
                )
        except Exception:
            self.destroy(namespace)
            raise

    def destroy(self, namespace: str) -> None:
        veth_host = f"vh{namespace[-6:]}"
        for port in (80, 443):
            self._run(
                "iptables", "-t", "nat", "-D", "PREROUTING", "-i", veth_host,
                "-p", "tcp", "--dport", str(port), "-j", "REDIRECT",
                "--to-ports", str(self.proxy_port),
            )
        self._run("ip", "link", "del", veth_host)
        self._run("ip", "netns", "del", namespace)
        self._run("rm", "-rf", f"/etc/netns/{namespace}")

    def _run(self, *argv: str) -> None:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        if proc.returncode != 0 and argv[0] != "rm":
            logger.debug("netns backend step failed: %s -> %s", argv, proc.stderr.strip())


class NamespaceLeaseManager:
    def __init__(
        self,
        *,
        registry: SourceRegistry,
        pool_size: int = 8,
        backend=None,
        acquire_timeout_s: float = 30.0,
        ttl_s: int = 900,
        ip_start: int = 2,
        subnet: str = "172.30.0",
    ):
        self.registry = registry
        self.pool_size = max(1, pool_size)
        self.backend = backend or SubprocessBackend()
        self.acquire_timeout_s = acquire_timeout_s
        self.ttl_s = ttl_s
        self.subnet = subnet
        self.ip_start = ip_start
        self._cond = threading.Condition()
        self._free = list(range(self.pool_size))
        self._leased: dict[int, NamespaceLease] = {}
        self._sessions: set[str] = set()
        self._counter = 0

    def _source_ip(self, slot: int) -> str:
        # Each lease owns a /30: .1 is the root-namespace gateway and .2 is the
        # leased namespace source address. Slots are spaced by four so every
        # source remains inside the single /24 that postrun.sh MASQUERADEs.
        return f"{self.subnet}.{self.ip_start + (slot * 4)}"

    def acquire(
        self,
        *,
        session_id: str,
        project_id: str,
        context: CaptureContext,
        ttl_s: int | None = None,
        now: float | None = None,
    ) -> NamespaceLease:
        now = time.time() if now is None else now
        ttl = self.ttl_s if ttl_s is None else ttl_s
        deadline = now + self.acquire_timeout_s
        with self._cond:
            while session_id in self._sessions:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise SessionBusyError(
                        f"session {session_id!r} already holds a capture lease "
                        f"(waited {self.acquire_timeout_s}s)"
                    )
                self._cond.wait(remaining)
            while not self._free:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise PoolExhaustedError(
                        "namespace pool exhausted: "
                        f"{self.pool_size} slots busy after {self.acquire_timeout_s}s"
                    )
                self._cond.wait(remaining)
            slot = self._free.pop(0)
            self._sessions.add(session_id)
            self._counter += 1
            namespace = f"kali-http-{self._counter:04d}"
            source_ip = self._source_ip(slot)
            lease = NamespaceLease(
                namespace=namespace,
                source_ip=source_ip,
                session_id=session_id,
                project_id=project_id,
                slot=slot,
                expires_at=(now if now is not None else time.time()) + max(0, ttl),
            )
        try:
            self.backend.create(namespace, source_ip)
            self.registry.register(source_ip, project_id, context, ttl_s=ttl)
        except Exception:
            with self._cond:
                self._sessions.discard(session_id)
                if slot not in self._free:
                    self._free.append(slot)
                self._free.sort()
                self._leased.pop(slot, None)
                self._cond.notify_all()
            raise
        with self._cond:
            self._leased[slot] = lease
            self._cond.notify_all()
        return lease

    def release(self, lease: NamespaceLease) -> None:
        with self._cond:
            if self._leased.pop(lease.slot, None) is None:
                return
            if lease.slot not in self._free:
                self._free.append(lease.slot)
                self._free.sort()
            self._sessions.discard(lease.session_id)
            self._cond.notify_all()
        try:
            self.backend.destroy(lease.namespace)
        finally:
            self.registry.release(lease.source_ip)

    def reap_expired(self, *, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._cond:
            expired = [lease for lease in self._leased.values() if lease.expires_at <= now]
        for lease in expired:
            self.release(lease)
        return len(expired)

    def status(self) -> dict:
        with self._cond:
            active = len(self._leased)
            return {
                "pool_size": self.pool_size,
                "active": active,
                "available": self.pool_size - active,
                "ttl_s": self.ttl_s,
                "acquire_timeout_s": self.acquire_timeout_s,
            }
