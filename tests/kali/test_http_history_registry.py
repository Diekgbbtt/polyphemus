"""The shared source-address registry maps a lease to its capture context."""
from __future__ import annotations

from kali.http_history.models import CaptureContext
from kali.http_history.registry import SourceRegistry


def _context(**overrides):
    base = dict(session_id="s1", run_id="r1", spec_id="spec", variant_ref="v0", exec_id="e1")
    base.update(overrides)
    return CaptureContext(**base)


def test_register_then_lookup_roundtrips(tmp_path):
    registry = SourceRegistry(tmp_path / "registry.sqlite3")
    registry.register("172.30.0.2", "proj-1", _context())
    project, context = registry.lookup("172.30.0.2")
    assert project == "proj-1"
    assert context.run_id == "r1"
    assert context.variant_ref == "v0"


def test_lookup_unknown_address_is_none(tmp_path):
    assert SourceRegistry(tmp_path / "registry.sqlite3").lookup("10.0.0.1") is None


def test_release_removes_the_mapping(tmp_path):
    registry = SourceRegistry(tmp_path / "registry.sqlite3")
    registry.register("172.30.0.2", "proj-1", _context())
    registry.release("172.30.0.2")
    assert registry.lookup("172.30.0.2") is None


def test_expired_leases_are_not_returned(tmp_path):
    registry = SourceRegistry(tmp_path / "registry.sqlite3")
    registry.register("172.30.0.2", "proj-1", _context(), ttl_s=0)
    assert registry.lookup("172.30.0.2") is None


def test_registry_is_shared_across_handles(tmp_path):
    path = tmp_path / "registry.sqlite3"
    SourceRegistry(path).register("172.30.0.2", "proj-1", _context())
    assert SourceRegistry(path).lookup("172.30.0.2") is not None
