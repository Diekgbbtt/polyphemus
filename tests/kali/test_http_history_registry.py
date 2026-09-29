"""The shared source-address registry maps a lease to its capture context."""
from __future__ import annotations

import json
import sqlite3

from kali.http_history.models import CaptureContext
from kali.http_history.registry import SourceRegistration, SourceRegistry


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


_POLICY = {
    "target_key": "app.example.com",
    "host_patterns": ["app.example.com"],
    "rate_per_s": 2.0,
    "burst": 1,
    "max_concurrency": 1,
    "min_delay_ms": 500.0,
    "source": "measured-transition",
    "version": "traffic-policy/v2",
}


def test_lookup_registration_carries_project_context_and_policy(tmp_path):
    """#238 Task 7: the addon needs the POLICY, the capture path needs the
    CONTEXT, and `lookup()` keeps returning exactly the legacy two-tuple."""
    registry = SourceRegistry(tmp_path / "registry.sqlite3")
    registry.register("172.30.0.2", "proj-1", _context(), traffic_policy=_POLICY)

    registration = registry.lookup_registration("172.30.0.2")

    assert isinstance(registration, SourceRegistration)
    assert registration.project_id == "proj-1"
    assert registration.capture_context.run_id == "r1"
    assert registration.traffic_policy == _POLICY
    project, context = registry.lookup("172.30.0.2")
    assert (project, context.run_id) == ("proj-1", "r1")


def test_a_registration_without_a_policy_is_still_a_registration(tmp_path):
    registry = SourceRegistry(tmp_path / "registry.sqlite3")
    registry.register("172.30.0.2", "proj-1", _context())
    assert registry.lookup_registration("172.30.0.2").traffic_policy is None
    assert registry.lookup_registration("10.0.0.1") is None


def test_an_expired_registration_is_not_returned(tmp_path):
    registry = SourceRegistry(tmp_path / "registry.sqlite3")
    registry.register("172.30.0.2", "proj-1", _context(), traffic_policy=_POLICY, ttl_s=0)
    assert registry.lookup_registration("172.30.0.2") is None


def test_the_additive_migration_preserves_existing_rows(tmp_path):
    """The registry is a live SQLite file: opening it with the new column must
    ADD the column and leave every pre-#238 row (and its capture lookup) intact."""
    path = tmp_path / "registry.sqlite3"
    legacy = sqlite3.connect(path)
    with legacy:
        legacy.execute(
            "CREATE TABLE leases ("
            " source_ip TEXT PRIMARY KEY, project_id TEXT NOT NULL, session_id TEXT,"
            " run_id TEXT, spec_id TEXT, variant_ref TEXT, exec_id TEXT,"
            " created_at REAL NOT NULL, expires_at REAL NOT NULL)"
        )
        legacy.execute(
            "INSERT INTO leases (source_ip, project_id, session_id, run_id, spec_id,"
            " variant_ref, exec_id, created_at, expires_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("172.30.0.2", "proj-1", "s1", "r1", "spec", "v0", "e1", 1.0, 4_102_444_800.0),
        )
    legacy.close()

    registry = SourceRegistry(path)

    registration = registry.lookup_registration("172.30.0.2")
    assert registration is not None
    assert registration.project_id == "proj-1"
    assert registration.capture_context.exec_id == "e1"
    # The new column exists and defaults to "no policy" for a migrated row.
    assert registration.traffic_policy is None
    # ... and it is writable afterwards.
    registry.register("172.30.0.2", "proj-1", _context(), traffic_policy=_POLICY)
    assert registry.lookup_registration("172.30.0.2").traffic_policy == _POLICY


def test_the_policy_is_stored_as_json_text(tmp_path):
    """The registry is read by a DIFFERENT process (mitmdump), so the policy
    travels as JSON, never as a pickled Python object."""
    path = tmp_path / "registry.sqlite3"
    SourceRegistry(path).register("172.30.0.2", "proj-1", _context(), traffic_policy=_POLICY)
    raw = sqlite3.connect(path).execute(
        "SELECT traffic_policy FROM leases WHERE source_ip='172.30.0.2'"
    ).fetchone()[0]
    assert json.loads(raw)["target_key"] == "app.example.com"
