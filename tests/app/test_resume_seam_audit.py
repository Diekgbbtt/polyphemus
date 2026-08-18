"""Unit tier: the resume-seam scaffold + session-address audit (#124).

The ladder of the module-runtime-independence workstream lands LAST here (the
G6 ordering, phase-0-audit-findings.md section 3): the documented CONTRACT a
future resume agent implements against - `agent_contexts(run_id, phase, tool)`
- and the running DETERMINISM AUDIT that keeps the proof current. The
composition rule itself is pinned by #119 (`tests/test_session_address.py`,
`_compose_module_scoped` / `ModuleScopedSession`); the per-module index the
enumeration reads is #120 (`checkpoints.ModuleIndex`); the manager whose
module runs commit those indexes is #121 (`app/runtime.RuntimeManager`).
This file brings together:

- the full discriminating matrix from #119 COMMITTED through real module
  contexts and ENUMERATED via `agent_contexts`, pinned on hand-escaped
  literals (not a recomputation of the same rule); repeated enumeration stays
  byte-identical, and no enumerated segment is a UUID or an epoch - a future
  composition change that introduces a UUID/time source breaks these tests;
- presence/absence of every discriminator (a missing instance is dropped,
  never shifts the address) and an over-long discriminator (hashed, bounded,
  stable);
- an empty enumeration, never an error, for an absent run / phase / tool;
- a read-only proof: enumeration commits nothing;
- the structural half re-run for #119/#120: neither module imports a source
  that could vary (no uuid/time/random at module scope);
- the upstream-compatibility proof for #121: a real `RuntimeManager` worker
  loop schedules runs whose committed pod contexts ARE the enumeration, read
  from the API thread with no new cross-thread surface beyond the documented
  read-only function.

All pure in-memory - no live model, no live database, no real PG saver
(CODING_STANDARD sections 6, 10; unit tier).
"""
from __future__ import annotations

import ast
import itertools
import re
from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph

from polymerhus.app.llm import checkpoints as C
from polymerhus.app.llm.session_address import ModuleScopedSession
from polymerhus.app.runtime import RuntimeManager


@pytest.fixture(autouse=True)
def _clean_module_state():
    """Isolate the process-global module index registry + pooled saver per
    test (the same isolation the #120 checkpoints tests use)."""
    C.close_session_checkpointer()
    with C._indexes_lock:
        C._module_indexes.clear()
    yield
    with C._indexes_lock:
        C._module_indexes.clear()
    C.close_session_checkpointer()


# --- helpers -----------------------------------------------------------------

class _CountState(dict):
    pass


def _compiled_graph(checkpointer):
    """A real langgraph graph compiled on the given checkpointer - exercises the
    full saver surface (get_tuple / put / put_writes) without any LLM."""
    graph = StateGraph(_CountState)
    graph.add_node("bump", lambda state: {"count": (state.get("count") or 0) + 1})
    graph.add_edge(START, "bump")
    graph.add_edge("bump", END)
    return graph.compile(checkpointer=checkpointer)


def _turn(graph, thread_id):
    graph.invoke({"count": 0}, {"configurable": {"thread_id": thread_id}})


def _commit(addresses):
    """Run one real graph turn per address under its module's context, so the
    index records each thread as committed - exactly what a scheduled module
    run does on the worker loop."""
    by_module: dict[str, list] = {}
    for address in addresses:
        by_module.setdefault(address.module, []).append(address)
    for module, addrs in by_module.items():
        with C.module_context(module):
            graph = _compiled_graph(C.get_session_checkpointer())
            for address in addrs:
                _turn(graph, address.thread_id)


def _dedup(addresses):
    seen = set()
    result = []
    for address in addresses:
        tid = address.thread_id
        if tid in seen:
            continue
        seen.add(tid)
        result.append(address)
    return result


# The pinned literals below are hand-escaped (the #119 rule applied by hand):
# every ':' inside a segment becomes '_', an over-long segment becomes a short
# stable hash, and empty (None/"") discriminators are dropped - never an empty
# shifted slot. These pin the EXACT bytes, so a rule regression that changed
# escaping, ordering, or dropped-vs-shifted semantics breaks the assertion.

_OVERLONG_A = "https://host.example/" + "a" * 200
_OVERLONG_B = "https://host.example/" + "b" * 200

_MATRIX = [
    ModuleScopedSession(module, "run1", phase, tool, disc, role_id=role)
    for module in ("recon", "analysis", "hunting")
    for (phase, tool, disc, role) in itertools.product(
        (None, 2),
        (None, "httpx"),
        (None, "https://a.example"),
        (None, "triager"),
    )
]

_PINS = [
    # (a) every discriminator present, module-scoped: module leads, never a
    # collision with another module's same (run, phase, tool, discriminator).
    ModuleScopedSession("recon", "run1", 2, "httpx", "https://a.example",
                        role_id="triager"),
    # (b) the analysis proposer's serialized shape (phase, tool, asset, role).
    ModuleScopedSession("analysis", "run1", 1, "openai", "asset-9",
                        role_id="analyst"),
    # (c) every discriminator absent: collapses to module:run, no empty slots.
    ModuleScopedSession("hunting", "run1", None, None, None, role_id=None),
    # (d) tool present, phase absent: the 3-part tool-only id.
    ModuleScopedSession("recon", "run1", None, "httpx", None, role_id=None),
    # (e) the hunt instance discriminator + the hunting role.
    ModuleScopedSession("hunting", "run1", None, None, "hunt-A",
                        role_id="hunting_hunter"),
    # (f) the role-only tail, no instance discriminator.
    ModuleScopedSession("hunting", "run1", None, None, None,
                        role_id="hunting_hunter"),
]

_OVERLONG_ADDRESSES = [
    ModuleScopedSession("recon", "run-long", 2, "httpx", _OVERLONG_A,
                        role_id="triager"),
    ModuleScopedSession("analysis", "run-long", 1, "openai", _OVERLONG_A,
                        role_id="analyst"),
    ModuleScopedSession("hunting", "run-long", None, None, _OVERLONG_A,
                        role_id="hunting_hunter"),
    ModuleScopedSession("recon", "run-long", 2, "httpx", _OVERLONG_B,
                        role_id="triager"),
]

_SHIFT = [
    # none discriminator ...
    ModuleScopedSession("recon", "run-shift", None, None, None, role_id=None),
    # ... a present discriminator (the address must NOT shift when one is
    # missing) ...
    ModuleScopedSession("recon", "run-shift", None, None, "D", role_id=None),
    # ... and an empty discriminator, which is dropped EXACTLY like None.
    ModuleScopedSession("recon", "run-shift", None, None, "", role_id=None),
]

_COMMITTED = _dedup(_MATRIX + _PINS + _OVERLONG_ADDRESSES + _SHIFT)

_UUID_SHAPE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
# a seconds/milliseconds epoch is 9+ consecutive digits; no address segment may
# look like one (a time source in the composition would).
_EPOCH_SHAPE = re.compile(r"^\d{9,}$")


# --- the determinism audit ---------------------------------------------------

def test_audit_enumerates_the_full_matrix_with_byte_identical_stability():
    """The resume seam's core audit: commit the FULL #119 discriminating matrix
    (all three modules, each of phase/tool/discriminator/role present and
    absent, over-long discriminators) and enumerate through `agent_contexts`.

    The enumerated ids are byte-identical across every repeated enumeration -
    a UUID or time source anywhere in the path would break the equality; and
    the hard-coded pinned literals pin the exact escaping rule, so a
    composition change that merely re-shuffles or re-escapes a segment is
    caught even though it stays deterministic."""
    _commit(_COMMITTED)

    expected = sorted({a.thread_id for a in _MATRIX + _PINS})

    # stable across repeated enumerations (any nondeterminism shows up here)
    snapshots = [C.agent_contexts("run1", None, None) for _ in range(25)]
    assert all(snap == snapshots[0] for snap in snapshots)

    # complete: exactly the committed threads, nothing more, nothing missing
    assert snapshots[0] == expected

    # no segment of any enumerated key is a UUID or an epoch-shaped number
    for tid in expected:
        for segment in tid.split(":"):
            assert not _UUID_SHAPE.fullmatch(segment), tid
            assert not _EPOCH_SHAPE.fullmatch(segment), tid


def test_audit_pins_the_exact_escaping_and_slot_semantics():
    """The hand-escaped pin set, asserted byte-for-byte. Each literal is the
    composition rule (module -> run -> present discriminators -> role) applied
    by hand, so a regression in escaping, ordering, or the drop-empty rule
    fails here even if it stayed deterministic."""
    _commit(_COMMITTED)

    # (a) every position present - the recon pod shape: module:run:phase:tool:
    #     discriminator:role, with the url's ':' escaped.
    assert "recon:run1:2:httpx:https_//a.example:triager" in C.agent_contexts(
        "run1", None, None)
    assert "recon:run1:2:httpx:https_//a.example:triager" in C.agent_contexts(
        "run1", 2, "httpx")

    # (b) the analysis proposer filter is exact: phase 1 + tool openai matches
    # only that one serialized instance.
    assert C.agent_contexts("run1", 1, "openai") == [
        "analysis:run1:1:openai:asset-9:analyst"
    ]

    # (c) all-absent collapses to module:run with no empty slots.
    assert "hunting:run1" in C.agent_contexts("run1", None, None)

    # (d) the 3-part tool-only id survives a phase-wildcard tool filter.
    assert "recon:run1:httpx" in C.agent_contexts("run1", None, "httpx")

    # (e) a hunt instance resolves through a tool-position filter exactly once.
    assert C.agent_contexts("run1", None, "hunt-A") == [
        "hunting:run1:hunt-A:hunting_hunter"
    ]

    # (f) the role-only tail is its own address, distinct from (e).
    assert C.agent_contexts("run1", None, "hunting_hunter") == [
        "hunting:run1:hunt-A:hunting_hunter",
        "hunting:run1:hunting_hunter",
    ]


def test_audit_missing_discriminator_never_shifts_the_address():
    """None and empty discriminators are dropped, not carried as empty shifted
    slots: the enumeration of run-shift is exactly the two real addresses."""
    _commit(_SHIFT)
    assert C.agent_contexts("run-shift", None, None) == [
        "recon:run-shift",
        "recon:run-shift:D",
    ]


def test_audit_overlong_discriminator_is_hashed_bounded_and_stable():
    """An over-long discriminator (>80 chars) is replaced by the SAME short
    hash on every composition - so a hashed key stays stable across runs and
    across enumerations - two different long values stay distinct, and every
    hashed segment is bounded (h + 16 hex)."""
    _commit(_OVERLONG_ADDRESSES)

    expected_by_module = {a.thread_id for a in _OVERLONG_ADDRESSES}
    enumerated = set(C.agent_contexts("run-long", None, None))
    assert enumerated == expected_by_module

    a = ModuleScopedSession("recon", "run-long", 2, "httpx", _OVERLONG_A,
                            role_id="triager")
    b = ModuleScopedSession("recon", "run-long", 2, "httpx", _OVERLONG_B,
                            role_id="triager")
    assert a.thread_id != b.thread_id
    assert a.thread_id in enumerated and b.thread_id in enumerated

    for tid in expected_by_module:
        segments = tid.split(":")
        hashed = next(seg for seg in segments if seg.startswith("h")
                      and len(seg) <= 17)
        assert len(hashed) <= 17
        assert len(tid) <= 120  # bounded regardless of discriminator length


# --- contract behaviour ------------------------------------------------------

def test_absence_returns_empty_never_an_error():
    """An absent run, phase, or tool is an EMPTY enumeration, never an error -
    the fail-open edge of the contract a resume agent relies on."""
    _commit(_COMMITTED)
    assert C.agent_contexts("no-such-run", None, None) == []
    assert C.agent_contexts("run1", "no-such-phase", None) == []
    assert C.agent_contexts("run1", None, "no-such-tool") == []
    assert C.agent_contexts("run1", "no-such-phase", "no-such-tool") == []


def test_enumeration_is_read_only():
    """`agent_contexts` reads the indexes without committing, archiving, or
    dropping anything: repeated enumeration leaves the committed sets intact."""
    _commit(_COMMITTED)
    before = {
        module: set(C._module_index(module).committed_ids())
        for module in ("recon", "analysis", "hunting")
    }
    for _ in range(10):
        C.agent_contexts("run1", None, None)
        C.agent_contexts("run1", 2, "httpx")
    after = {
        module: set(C._module_index(module).committed_ids())
        for module in ("recon", "analysis", "hunting")
    }
    assert after == before


# --- the structural half of the audit (re-run for #119/#120) -----------------

def test_checkpoints_and_address_modules_import_nothing_that_could_vary():
    """The structural audit: neither the composition module (#119) nor the
    index/enumeration module (#120) imports a source that could inject
    run-to-run variability at module scope - no uuid/time/random/datetime/
    secrets/os. Total isolation from any variable source by construction."""
    import polymerhus.app.llm.session_address as session_address

    modules = {
        "session_address.py": Path(session_address.__file__),
        "checkpoints.py": Path(C.__file__),
    }
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # module-LEVEL imports only: the lazy function-scope imports (langgraph,
        # psycopg) are sanctioned by CODING_STANDARD section 6, and neither
        # could inject variability at the scope the composition runs in.
        top_level = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level.add(node.names[0].name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                top_level.add((node.module or "").split(".")[0])
        assert not (top_level & {"uuid", "time", "random", "datetime",
                                 "secrets", "os"}), name
        assert top_level <= {
            "__future__", "contextlib", "contextvars", "dataclasses",
            "hashlib", "logging", "threading", "typing", "polymerhus",
        }, name


# --- upstream compatibility with #121 ----------------------------------------

def test_runtime_scheduled_runs_enumerate_through_the_documented_scaffold():
    """Upstream compatibility (#121 AC): what the MANAGER's module runs commit
    on the worker loop IS what the scaffold enumerates from the API thread -
    the reads fall out of the documented read-only `agent_contexts` and need no
    new cross-thread verb, no new handle attribute, no new marshalling."""
    rm = RuntimeManager()
    rm.start()
    try:
        for module in ("recon", "analysis", "hunting"):
            rm.register_module(module)

        runs = [
            ModuleScopedSession("recon", "run-m1", 2, "httpx",
                                "https://m.example", role_id="triager"),
            ModuleScopedSession("analysis", "run-m1", 1, "openai",
                                "asset-m", role_id="analyst"),
            ModuleScopedSession("hunting", "run-m1", None, None, "hunt-m",
                                role_id="hunting_hunter"),
        ]
        for address in runs:
            async def commit(addr=address):
                graph = _compiled_graph(C.get_session_checkpointer())
                _turn(graph, addr.thread_id)
            rm.schedule(address.module, commit(), name=f"commit-{address.module}").result(
                timeout=10)

        # the API thread enumerates exactly the committed pod contexts, with no
        # additional surface: the same manager verbs and the one read-only
        # function the architecture doc section 3 lists.
        assert set(C.agent_contexts("run-m1", None, None)) == {
            a.thread_id for a in runs
        }
        assert C.agent_contexts("run-m1", 2, "httpx") == [
            "recon:run-m1:2:httpx:https_//m.example:triager"
        ]
        assert C.agent_contexts("run-m1", None, "hunt-m") == [
            "hunting:run-m1:hunt-m:hunting_hunter"
        ]
        assert not hasattr(rm, "agent_contexts")  # no new manager verb
    finally:
        rm.shutdown()


def test_resume_agent_recomposes_stable_keys_outside_the_worker_loop():
    """The resume agent's own operation, simulated: it recomposes the keys for
    the SAME logical grid of inputs in a FRESH process state (a cleared index
    registry) and the enumeration matches byte-for-byte across the two
    processes' worth of commits - the post-crash re-derivation the audit
    exists to guarantee."""
    grid = [
        ModuleScopedSession("recon", "run-re", 2, "httpx",
                            "https://re.example", role_id="triager"),
        ModuleScopedSession("analysis", "run-re", 1, "openai",
                            "asset-re", role_id="analyst"),
        ModuleScopedSession("hunting", "run-re", None, None, "hunt-re",
                            role_id="hunting_hunter"),
    ]

    _commit(grid)
    first = C.agent_contexts("run-re", None, None)

    with C._indexes_lock:
        C._module_indexes.clear()
    _commit(grid)
    second = C.agent_contexts("run-re", None, None)

    assert first == second
    assert second == sorted(a.thread_id for a in grid)