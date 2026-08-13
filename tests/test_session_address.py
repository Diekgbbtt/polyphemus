"""Unit tier: the typed session addresses (`app/llm/session_address.py`, #94).

The address is the domain identity of one agent instance's session memory. These tests
pin the collision-free property (concurrent same-role instances get DISTINCT thread ids),
the per-module shapes, and the boundary-safety (escape + hash) of the shared composer -
now expressed on the typed value objects rather than a positional-path builder.
"""
from __future__ import annotations

import pytest

from polymerhus.app.llm.session_address import (
    AnalysisSession,
    HuntSession,
    ModuleScopedSession,
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


_ESCAPED_SEGMENT = {
    None: [],
    2: ["2"],
    "httpx": ["httpx"],
    "https://a.example": ["https_//a.example"],
    "triager": ["triager"],
}


@pytest.mark.parametrize("module", ("recon", "analysis", "hunting"))
@pytest.mark.parametrize("phase", (None, 2))
@pytest.mark.parametrize("tool", (None, "httpx"))
@pytest.mark.parametrize("disc", (None, "https://a.example"))
@pytest.mark.parametrize("role_id", (None, "triager"))
def test_module_scoped_session_is_deterministic_across_the_matrix(
    module, phase, tool, disc, role_id
):
    """The determinism audit (module-runtime-architecture.md section 6, G7a): the
    module-scoped address is a PURE function of (module, run, phase, tool, discriminator)
    - same inputs, byte-identical output, so a post-crash enumeration re-derives the same
    key. The module is the LEADING segment so two modules never collide on the same (run,
    phase, tool, discriminator) in the shared #94 pooled store, and empty (None/"")
    discriminators are dropped exactly like `_compose`, so a missing instance never shifts
    the address. The expected segment literals are hard-coded (escaping applied by hand),
    so this is an exact pin, not a recomputation of the same rule."""
    expected = [module, "run1"]
    for value in (phase, tool, disc, role_id):
        expected += _ESCAPED_SEGMENT[value]
    a = ModuleScopedSession(module, "run1", phase, tool, disc, role_id=role_id)
    b = ModuleScopedSession(module, "run1", phase, tool, disc, role_id=role_id)
    assert a.thread_id == b.thread_id  # pure: same inputs, byte-identical output
    assert a.thread_id == ":".join(expected)


def test_overlong_discriminator_hash_path_is_deterministic_and_bounded():
    """The hash path is part of the pure composition: an over-long discriminator (> the
    80-char threshold) is replaced by the SAME short hash every time, so even hashed keys
    stay stable across runs, and two different long values stay distinct."""
    long_a = "https://host.example/" + "a" * 200
    long_b = "https://host.example/" + "b" * 200
    a1 = ModuleScopedSession("recon", "run1", 2, "httpx", long_a, role_id="triager").thread_id
    a2 = ModuleScopedSession("recon", "run1", 2, "httpx", long_a, role_id="triager").thread_id
    b = ModuleScopedSession("recon", "run1", 2, "httpx", long_b, role_id="triager").thread_id
    assert a1 == a2  # the hash is deterministic, not a random/short-lived value
    assert a1 != b
    assert len(a1.split(":")[4]) <= 20  # the discriminator segment was hashed, not verbatim


def test_repeated_composition_stays_byte_identical_with_no_uuid_segment():
    """The no-UUID/no-time proof, exercised: composing the SAME logical instance a hundred
    times yields byte-identical ids, and no segment is a UUID shape - a single UUID or
    time source in the path would break the equality or the shape."""
    import re

    ids = {
        ModuleScopedSession(
            "analysis", "run1", 1, "openai", "asset-42", role_id="analyst"
        ).thread_id
        for _ in range(100)
    }
    assert len(ids) == 1
    uuid_shape = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    )
    for segment in ids.pop().split(":"):
        assert not uuid_shape.fullmatch(segment)


def test_module_scoped_composition_imports_nothing_that_could_vary():
    """The audit's structural half: the composition lives in a module whose imports are
    limited to pure stdlib (hashlib, dataclasses, typing) - no uuid/time/random, no
    network or DB client - so no run-to-run variability can enter through an import, and
    the module performs no I/O at import (CODING_STANDARD 6)."""
    import ast
    from pathlib import Path

    import polymerhus.app.llm.session_address as session_address

    tree = ast.parse(Path(session_address.__file__).read_text(encoding="utf-8"))
    top_level = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            top_level.add(node.names[0].name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module.split(".")[0])
    assert top_level <= {"__future__", "hashlib", "dataclasses", "typing"}
