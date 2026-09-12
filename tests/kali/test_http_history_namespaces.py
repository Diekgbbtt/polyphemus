"""Bounded, session-serialized namespace leases with explicit backpressure."""
from __future__ import annotations

import threading
import time

import pytest

from kali.http_history.models import CaptureContext
from kali.http_history.namespaces import (
    NamespaceLeaseManager,
    PoolExhaustedError,
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
