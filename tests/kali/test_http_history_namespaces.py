"""Bounded, session-serialized namespace leases with explicit backpressure."""
from __future__ import annotations

import threading
import time

import pytest

from kali.http_history.models import CaptureContext
from kali.http_history.namespaces import (
    NamespaceLeaseManager,
    PoolExhaustedError,
    SubprocessBackend,
)
from kali.http_history.registry import SourceRegistry


class FakeBackend:
    def __init__(self):
        self.created: list[tuple[str, str]] = []
        self.destroyed: list[str] = []

    def create(self, namespace: str, source_ip: str) -> None:
        self.created.append((namespace, source_ip))

    def destroy(self, namespace: str) -> None:
        self.destroyed.append(namespace)


def _manager(tmp_path, *, pool_size=2, backend=None, acquire_timeout_s=0.2):
    return NamespaceLeaseManager(
        registry=SourceRegistry(tmp_path / "registry.sqlite3"),
        pool_size=pool_size,
        backend=backend or FakeBackend(),
        acquire_timeout_s=acquire_timeout_s,
        ttl_s=60,
    )


def test_acquire_creates_a_namespace_and_registers_the_mapping(tmp_path):
    backend = FakeBackend()
    manager = _manager(tmp_path, backend=backend)
    lease = manager.acquire(
        session_id="s1", project_id="proj-1", context=CaptureContext(exec_id="e1")
    )
    assert lease.namespace.startswith("kali-http-")
    assert backend.created == [(lease.namespace, lease.source_ip)]
    project, context = manager.registry.lookup(lease.source_ip)
    assert project == "proj-1" and context.exec_id == "e1"


def test_concurrent_sessions_get_distinct_source_ips(tmp_path):
    manager = _manager(tmp_path, pool_size=2)
    a = manager.acquire(session_id="s1", project_id="p", context=CaptureContext())
    b = manager.acquire(session_id="s2", project_id="p", context=CaptureContext())
    assert a.source_ip != b.source_ip
    manager.release(a)
    manager.release(b)


def test_pool_exhaustion_applies_explicit_backpressure(tmp_path):
    manager = _manager(tmp_path, pool_size=1, acquire_timeout_s=0.05)
    first = manager.acquire(session_id="s1", project_id="p", context=CaptureContext())
    with pytest.raises(PoolExhaustedError):
        manager.acquire(session_id="s2", project_id="p", context=CaptureContext())
    manager.release(first)


def test_same_session_is_serialized(tmp_path):
    manager = _manager(tmp_path, pool_size=4, acquire_timeout_s=0.5)
    first = manager.acquire(session_id="s1", project_id="p", context=CaptureContext())
    lease2 = {}

    def second():
        lease2["lease"] = manager.acquire(
            session_id="s1", project_id="p", context=CaptureContext()
        )

    thread = threading.Thread(target=second)
    thread.start()
    time.sleep(0.03)
    assert "lease" not in lease2  # the second acquire is still waiting
    manager.release(first)
    thread.join(timeout=2)
    assert "lease" in lease2
    manager.release(lease2["lease"])


def test_release_returns_the_slot_and_destroys_the_namespace(tmp_path):
    backend = FakeBackend()
    manager = _manager(tmp_path, pool_size=1, backend=backend)
    lease = manager.acquire(session_id="s1", project_id="p", context=CaptureContext())
    manager.release(lease)
    assert backend.destroyed == [lease.namespace]
    assert manager.registry.lookup(lease.source_ip) is None
    manager.acquire(session_id="s2", project_id="p", context=CaptureContext())


def test_ttl_reaps_abandoned_leases(tmp_path):
    backend = FakeBackend()
    manager = _manager(tmp_path, pool_size=1, backend=backend)
    lease = manager.acquire(
        session_id="s1", project_id="p", context=CaptureContext(), ttl_s=0
    )
    assert manager.reap_expired() == 1
    assert backend.destroyed == [lease.namespace]
    assert manager.registry.lookup(lease.source_ip) is None


def test_status_reports_pool_state(tmp_path):
    manager = _manager(tmp_path, pool_size=2)
    manager.acquire(session_id="s1", project_id="p", context=CaptureContext())
    status = manager.status()
    assert status["pool_size"] == 2
    assert status["active"] == 1
    assert status["available"] == 1


class RecordingForwarder:
    """Stands in for the DNS forwarder: records which gateways were served."""

    def __init__(self):
        self.bound: list[str] = []
        self.unbound: list[str] = []

    def bind(self, address: str, *, port: int = 53) -> int:
        self.bound.append(address)
        return port

    def unbind(self, address: str) -> bool:
        self.unbound.append(address)
        return True


def _backend(tmp_path, forwarder=None) -> SubprocessBackend:
    return SubprocessBackend(
        netns_dir=str(tmp_path / "etc-netns"),
        resolv_conf=str(tmp_path / "resolv.conf"),
        hosts_file=str(tmp_path / "hosts"),
        dns_forwarder=forwarder,
    )


def test_backend_gives_the_lease_a_resolver_it_can_actually_reach(tmp_path, monkeypatch):
    """The container's `nameserver 127.0.0.11` is Docker's resolver on the
    CONTAINER's loopback: copied into a child namespace it answers nothing
    (live 2026-09-17, `curl` rc=6 on every hostname). The lease gets its gateway
    first, the forwarder is bound there, and /etc/hosts rides along so the
    aliases (extra_hosts, VPN names) keep working inside the namespace."""
    (tmp_path / "resolv.conf").write_text(
        "# Generated by Docker Engine.\n\nnameserver 127.0.0.11\nsearch example.it\n", encoding="utf-8"
    )
    (tmp_path / "hosts").write_text(
        "127.0.0.1 localhost\n192.33.91.87 soupmarket.shop\n", encoding="utf-8"
    )
    forwarder = RecordingForwarder()
    backend = _backend(tmp_path, forwarder)
    monkeypatch.setattr(backend, "_run", lambda *argv: None)

    backend.create("kali-http-0001", "172.30.0.6")

    conf_dir = tmp_path / "etc-netns" / "kali-http-0001"
    resolv = (conf_dir / "resolv.conf").read_text(encoding="utf-8")
    assert resolv.splitlines()[0] == "nameserver 172.30.0.5", resolv
    assert "127.0.0.11" not in resolv, resolv
    assert "search example.it" in resolv
    assert "soupmarket.shop" in (conf_dir / "hosts").read_text(encoding="utf-8")
    assert forwarder.bound == ["172.30.0.5"]

    backend.destroy("kali-http-0001")
    assert forwarder.unbound == ["172.30.0.5"], "the listener must not outlive its veth"


def test_backend_without_a_forwarder_still_rewrites_the_resolver(tmp_path, monkeypatch):
    (tmp_path / "resolv.conf").write_text("nameserver 127.0.0.11\n", encoding="utf-8")
    backend = _backend(tmp_path)
    monkeypatch.setattr(backend, "_run", lambda *argv: None)

    backend.create("kali-http-0002", "172.30.0.2")

    resolv = (tmp_path / "etc-netns" / "kali-http-0002" / "resolv.conf").read_text(encoding="utf-8")
    assert resolv.strip() == "nameserver 172.30.0.1"
    backend.destroy("kali-http-0002")
