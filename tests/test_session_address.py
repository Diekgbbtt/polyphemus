"""Unit tier: the typed session addresses (`app/llm/session_address.py`, #94).

The address is the domain identity of one agent instance's session memory. These tests
pin the collision-free property (concurrent same-role instances get DISTINCT thread ids),
the per-module shapes, and the boundary-safety (escape + hash) of the shared composer -
now expressed on the typed value objects rather than a positional-path builder.
"""
from __future__ import annotations

from polymerhus.app.llm.session_address import (
    AnalysisSession,
    HuntSession,
    PodSession,
    SessionAddress,
    SessionContext,
)


def test_analysis_session_is_run_and_role_only():
    """A serialized proposer (one graph/run) needs no instance discriminator: run + role
    is already unique."""
    assert AnalysisSession("run1", "assigner").thread_id == "run1:assigner"


def test_pod_sessions_disambiguate_concurrent_same_role_instances():
    """The whole point: two pods running the SAME role in the SAME run get DISTINCT
    thread ids via their (phase, tool, asset), so the checkpointer never routes one pod's
    memory into another (the mis-routing the operator flagged)."""
    a = PodSession("run1", 2, "httpx", "https://a.example", "triager")
    b = PodSession("run1", 2, "httpx", "https://b.example", "triager")
    assert a.thread_id != b.thread_id
    assert a.thread_id == "run1:2:httpx:https_//a.example:triager"  # ':' in the url escaped


def test_hunt_sessions_are_per_hunt_and_per_spec():
    """One thread per hunt (author+judge+re-entries share it); the #84 test-executor pod
    adds a per-spec discriminator."""
    assert HuntSession("run1", "hunt-A").thread_id == "run1:hunt-A:hunting_hunter"
    assert HuntSession("run1", "hunt-A").thread_id != HuntSession("run1", "hunt-B").thread_id
    p1 = HuntSession("run1", "hunt-A", role_id="pod", spec="spec-1")
    p2 = HuntSession("run1", "hunt-A", role_id="pod", spec="spec-2")
    assert p1.thread_id == "run1:hunt-A:spec-1:pod"
    assert p1.thread_id != p2.thread_id


def test_none_discriminator_is_dropped_not_shifted():
    """A missing discriminator (hunt with no spec) vanishes rather than leaving an empty
    segment that would shift the address."""
    assert HuntSession("run1", "hunt-A", spec=None).thread_id == "run1:hunt-A:hunting_hunter"


def test_overlong_discriminator_is_hashed_but_stays_unique():
    """An unbounded discriminator (a long url) is hashed to keep the key bounded, and two
    different long values still map to different threads."""
    long_a = "https://host.example/" + "a" * 200
    long_b = "https://host.example/" + "b" * 200
    ta = PodSession("run1", 2, "httpx", long_a, "triager").thread_id
    tb = PodSession("run1", 2, "httpx", long_b, "triager").thread_id
    assert ta != tb
    assert len(ta.split(":")[3]) <= 20  # the asset segment was hashed, not carried verbatim


def test_addresses_are_frozen_and_satisfy_the_protocol():
    """Frozen (immutable value objects) and structurally a `SessionAddress` (role_id +
    thread_id) - so a generic consumer types against the Protocol, never a concrete type."""
    import dataclasses
    import pytest

    a = AnalysisSession("run1", "assigner")
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.run_id = "x"  # type: ignore[misc]
    for addr in (AnalysisSession("r", "assigner"),
                 PodSession("r", 1, "httpx", "x", "triager"),
                 HuntSession("r", "h")):
        assert hasattr(addr, "role_id") and isinstance(addr.thread_id, str)


def test_session_context_pairs_a_typed_address_with_its_checkpointer():
    saver = object()
    ctx = SessionContext(AnalysisSession("run1", "assigner"), saver)
    assert ctx.address.thread_id == "run1:assigner"
    assert ctx.checkpointer is saver


def test_recon_pod_session_keys_by_the_concurrent_pod_instance():
    """The recon helper (`pod.pod_session`) builds a `PodSession` keyed by the input-asset
    url (operator-chosen scheme); a url-less asset falls back to a stable hash rather than
    colliding on an empty discriminator."""
    from polymerhus.recon.domain.pod import pod_session
    from polymerhus.recon.domain.types import JobSpec

    job = JobSpec(tool="httpx", skill="recon", command_template="", produces=[], consumes="BaseURL")
    k1 = pod_session("run1", 2, job, {"url": "https://a.example"}, role_id="triager").thread_id
    k2 = pod_session("run1", 2, job, {"url": "https://b.example"}, role_id="triager").thread_id
    assert k1 != k2 and k1.endswith(":triager")
    n1 = pod_session("run1", 2, job, {"batch": ["x"]}, role_id="triager").thread_id
    n2 = pod_session("run1", 2, job, {"batch": ["y"]}, role_id="triager").thread_id
    assert n1 != n2  # url-less assets do not collapse to one key
