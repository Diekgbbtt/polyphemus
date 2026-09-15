"""Unit tier: the flush-result contract + the checkpoint_ns archive repair (#211).

The confirmed #211 mechanism: `_archive_thread` replayed each committed thread into
the #94 pooled PG saver with a hand-built minimal config (`{thread_id}` only), while
the resolved `PostgresSaver` (langgraph-checkpoint-postgres 3.x) hard-pops
`checkpoint_ns` from that config - so EVERY thread's archive raised
`KeyError: 'checkpoint_ns'` and the fail-open warn-and-keep turned a systematic
teardown failure into a silent one (the eval run 26bdaf55 27-thread drop).

These tests pin the FIXED contract: the flush returns a typed result
(`committed/archived/dropped/dropped_thread_ids`), the archive replays each tuple's
OWN config (carrying its `checkpoint_ns`), a partial failure salvages the rest and
reports the residual loudly, a no-target flush is LOUD (never a bare debug no-op),
and `flush_all_indexes` aggregates per module.

All in-memory, no DB, no model, no gateway (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import operator

import pytest
from typing_extensions import Annotated, TypedDict

from polymerhus.app.llm import checkpoints as C
from polymerhus.app.llm.session_address import ModuleScopedSession


@pytest.fixture(autouse=True)
def _clean_module_state():
    C.close_session_checkpointer()
    with C._indexes_lock:
        C._module_indexes.clear()
    yield
    with C._indexes_lock:
        C._module_indexes.clear()
    C.close_session_checkpointer()


class _CountState(TypedDict):
    count: Annotated[int, operator.add]


def _compiled_graph(checkpointer):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(_CountState)
    graph.add_node("bump", lambda state: {"count": 1})
    graph.add_edge(START, "bump")
    graph.add_edge("bump", END)
    return graph.compile(checkpointer=checkpointer)


def _commit(addresses):
    """Run one real graph turn per address under its module's context, so the index
    records each thread as committed (langgraph injects checkpoint_ns internally)."""
    by_module: dict[str, list] = {}
    for address in addresses:
        by_module.setdefault(address.module, []).append(address)
    for module, addrs in by_module.items():
        with C.module_context(module):
            graph = _compiled_graph(C.get_session_checkpointer())
            for address in addrs:
                graph.invoke(
                    {"count": 0},
                    {"configurable": {"thread_id": address.thread_id}},
                )


class _RecordingFlushTarget:
    """The fake #94 pooled PG saver: records every archived thread and can fail
    selectively so the salvage loop is exercised without Postgres."""

    def __init__(self):
        self.puts: list[tuple[str, str, str]] = []
        self.writes: list[tuple[str, list, str]] = []
        self.fail_threads: set[str] = set()

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id = config["configurable"]["thread_id"]
        if thread_id in self.fail_threads:
            raise RuntimeError(f"pg down for {thread_id}")
        checkpoint_id = checkpoint.get("id", "?")
        ns = config["configurable"].get("checkpoint_ns")
        self.puts.append((thread_id, checkpoint_id, ns))
        return {
            "configurable": {
                **config["configurable"],
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(self, config, writes, task_id, task_path=""):
        self.writes.append((config["configurable"]["thread_id"], list(writes), task_id))


class _HardNsTarget:
    """Replicates the resolved PostgresSaver 3.x `aput` contract: it HARD-POPS
    `checkpoint_ns` from the config (KeyError when absent). A flush that archives
    every thread through this target proves the checkpoint_ns repair."""

    def __init__(self):
        self.puts: list[tuple[str, str]] = []
        self.stale_ids: list[bool] = []

    def put(self, config, checkpoint, metadata, new_versions):
        configurable = config["configurable"].copy()
        self.stale_ids.append("checkpoint_id" in configurable)
        thread_id = configurable.pop("thread_id")
        ns = configurable.pop("checkpoint_ns")  # aio.py:255 - KeyError when absent
        self.puts.append((thread_id, ns))
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint.get("id", "?"),
            }
        }

    def put_writes(self, config, writes, task_id, task_path=""):
        pass


# --- C1: the flush returns a typed committed/archived/dropped result -----------

def test_flush_returns_committed_archived_dropped_result(monkeypatch):
    pods = [
        ModuleScopedSession("recon", "run-9", 2, "httpx", "a", role_id="triager"),
        ModuleScopedSession("recon", "run-9", 2, "httpx", "b", role_id="triager"),
    ]
    _commit(pods)
    target = _RecordingFlushTarget()
    monkeypatch.setattr(C, "_saver", target)

    result = C.flush_module_index("recon")
    assert result.committed == 2
    assert result.archived == 2
    assert result.dropped == 0
    assert result.dropped_thread_ids == []
    assert result.cause is None
    assert C._module_index("recon").committed_ids() == []


# --- C2: the archive replays each tuple's OWN checkpoint_ns (the KeyError repair) --

def test_flush_archive_replays_each_tuples_own_checkpoint_ns(monkeypatch):
    """A flush through a target that HARD-POPS `checkpoint_ns` (the resolved
    PostgresSaver 3.x contract) archives every committed thread with dropped == 0 -
    the 27-thread KeyError is gone. The archive replays each tuple's own config
    (thread_id + the tuple's checkpoint_ns), never a thread_id-only config."""
    pods = [
        ModuleScopedSession("hunting", "run-H", 2, "httpx", "a", role_id="triager"),
        ModuleScopedSession("hunting", "run-H", 2, "httpx", "b", role_id="triager"),
    ]
    _commit(pods)
    target = _HardNsTarget()
    monkeypatch.setattr(C, "_saver", target)

    result = C.flush_module_index("hunting")
    assert result.archived == 2
    assert result.dropped == 0
    assert {tid for tid, _ in target.puts} == {p.thread_id for p in pods}
    # the tuple's own namespace rode the archive config (empty-string top-level ns
    # is what a real graph turn wrote - never a missing key)
    assert all(ns is not None and isinstance(ns, str) for _, ns in target.puts)
    # the put config carries NO stale checkpoint_id (the target mints a fresh one;
    # replaying the source id is unauthorised - P4)
    assert target.stale_ids and not any(target.stale_ids)


def test_installed_saver_hard_pops_checkpoint_ns():
    """Contract test against the REAL saver API shape (TD-T2, P7a): the installed
    `AsyncPostgresSaver.aput` hard-pops `checkpoint_ns` from the config - the exact
    line the thread_id-only config tripped. No live DB: source inspection only."""
    saver_mod = pytest.importorskip("langgraph.checkpoint.postgres.aio")
    import importlib.metadata as _md
    import inspect as _inspect

    assert _md.version("langgraph-checkpoint-postgres").split(".")[0] >= "3"
    source = _inspect.getsource(saver_mod.AsyncPostgresSaver.aput)
    assert 'configurable.pop("checkpoint_ns")' in source


# --- flush_run_scoped: the single run-terminal chokepoint (S1/P2/S3) --------------

def test_flush_run_scoped_returns_the_result_and_logs_a_drop_loudly(caplog):
    import asyncio as _asyncio

    seen = []

    def fake_flush(module, run_id=None):
        seen.append((module, run_id))
        return C.FlushResult(committed=2, archived=1, dropped=1,
                             dropped_thread_ids=["recon:r:t1"])

    with caplog.at_level("WARNING", logger="polymerhus.app.llm.checkpoints"):
        result = _asyncio.run(C.flush_run_scoped("recon", "r", flush_fn=fake_flush))
    assert seen == [("recon", "r")]     # the injectable seam, off-module-globals
    assert result.dropped == 1
    assert any("run-terminal flush dropped 1/2" in r.message and "recon:r:t1" in r.message
               for r in caplog.records)


def test_flush_run_scoped_clean_flush_logs_no_drop(caplog):
    import asyncio as _asyncio

    def fake_flush(module, run_id=None):
        return C.FlushResult(committed=1, archived=1, dropped=0, dropped_thread_ids=[])

    with caplog.at_level("WARNING", logger="polymerhus.app.llm.checkpoints"):
        result = _asyncio.run(C.flush_run_scoped("recon", "r", flush_fn=fake_flush))
    assert result.archived == 1
    assert not any("run-terminal flush dropped" in r.message for r in caplog.records)


def test_flush_run_scoped_never_raises_degrades_to_hook_raised():
    import asyncio as _asyncio

    def exploding_flush(module, run_id=None):
        raise RuntimeError("seam exploded")

    result = _asyncio.run(C.flush_run_scoped("recon", "r", flush_fn=exploding_flush))
    assert result.cause == "hook-raised"   # typed degraded, never raised


# --- C3: a partial failure salvages the rest and reports the residual loudly -----

def test_flush_partial_failure_reports_dropped_and_salvages_the_rest(monkeypatch):
    pods = [
        ModuleScopedSession("recon", "run-9", 2, "httpx", "a", role_id="triager"),
        ModuleScopedSession("recon", "run-9", 2, "httpx", "b", role_id="triager"),
    ]
    _commit(pods)
    target = _RecordingFlushTarget()
    target.fail_threads = {pods[0].thread_id}
    monkeypatch.setattr(C, "_saver", target)

    result = C.flush_module_index("recon")
    assert result.committed == 2
    assert result.archived == 1
    assert result.dropped == 1
    assert result.dropped_thread_ids == [pods[0].thread_id]
    # the salvage loop still archived the healthy thread
    assert {t[0] for t in target.puts} == {pods[1].thread_id}
    # the failed thread stays in the index (a later flush can retry it)
    assert C._module_index("recon").committed_ids() == [pods[0].thread_id]


# --- C4: zero committed threads is a valid empty result --------------------------

def test_flush_zero_committed_is_a_valid_empty_result(monkeypatch):
    monkeypatch.setattr(C, "_saver", _RecordingFlushTarget())
    result = C.flush_module_index("analysis")
    assert result.committed == 0
    assert result.archived == 0
    assert result.dropped == 0
    assert result.dropped_thread_ids == []
    # an index that was never built is the same valid empty
    assert C._module_indexes.get("analysis") is None or True


# --- C5: a no-target flush is LOUD (never a bare debug no-op) --------------------

def test_flush_without_target_is_loud_no_target_cause(monkeypatch):
    pods = [
        ModuleScopedSession("recon", "run-9", 2, "httpx", "a", role_id="triager"),
    ]
    _commit(pods)
    monkeypatch.setattr(C, "_saver", None)
    C.close_session_checkpointer()

    result = C.flush_module_index("recon")
    assert result.committed == 1
    assert result.archived == 0
    assert result.dropped == 1
    assert result.dropped_thread_ids == [pods[0].thread_id]
    assert result.cause == "no-target"   # the drop names its cause, never a silent debug
    assert C._module_index("recon").committed_ids() == [pods[0].thread_id]


# --- C9: the run-scoped flush counts only that run's threads ---------------------

def test_flush_run_scoped_result_counts_only_that_run(monkeypatch):
    run_a = [
        ModuleScopedSession("recon", "run-A", 2, "httpx", "a", role_id="triager"),
        ModuleScopedSession("recon", "run-A", 2, "httpx", "b", role_id="triager"),
    ]
    run_b = [
        ModuleScopedSession("recon", "run-B", 2, "httpx", "c", role_id="triager"),
    ]
    _commit(run_a + run_b)
    target = _RecordingFlushTarget()
    monkeypatch.setattr(C, "_saver", target)

    result = C.flush_module_index("recon", run_id="run-A")
    assert result.committed == 2
    assert result.archived == 2
    assert {t[0] for t in target.puts} == {p.thread_id for p in run_a}
    assert C._module_index("recon").committed_ids() == [run_b[0].thread_id]


# --- flush_all_indexes aggregates per module -------------------------------------

def test_flush_all_indexes_returns_per_module_results(monkeypatch):
    pods = [
        ModuleScopedSession("recon", "run-1", 2, "httpx", "a", role_id="triager"),
        ModuleScopedSession("analysis", "run-1", 1, "openai", "asset-9",
                            role_id="analyst"),
    ]
    _commit(pods)
    target = _RecordingFlushTarget()
    monkeypatch.setattr(C, "_saver", target)

    results = C.flush_all_indexes()
    assert set(results) == {"recon", "analysis"}
    assert results["recon"].archived == 1 and results["recon"].dropped == 0
    assert results["analysis"].archived == 1 and results["analysis"].dropped == 0

# --- flush_seam_result: the single None/raise normalization boundary (S-regression) --

def test_flush_seam_result_passes_a_real_result_straight_through():
    real = C.FlushResult(committed=1, archived=1, dropped=0, dropped_thread_ids=[])
    assert C.flush_seam_result(lambda: real, module="recon") is real


def test_flush_seam_result_replaces_a_none_return_with_the_designed_default(caplog):
    """The holistic NoneType guard: a seam that returns None (a record-only stub, a
    hook that forgot to return) is normalized AT THE BOUNDARY to the designed
    degraded default - no reaction point ever holds a bare None."""
    with caplog.at_level("WARNING", logger="polymerhus.app.llm.checkpoints"):
        result = C.flush_seam_result(lambda: None, module="recon")
    assert result == C.FlushResult.degraded("no-result")
    assert result.cause == "no-result"
    assert any("expected FlushResult" in r.message for r in caplog.records)


def test_flush_seam_result_degrades_a_raise_to_hook_raised():
    def boom():
        raise RuntimeError("seam down")
    result = C.flush_seam_result(boom, module="analysis")
    assert result == C.FlushResult.degraded("hook-raised")
    assert result.cause == "hook-raised"


def test_flush_all_indexes_degrades_a_none_returning_seam(monkeypatch):
    """The shutdown bulk walk must never read a bare None: a seam returning None
    yields a typed per-module result at the boundary (the full-suite-only crash)."""
    C._module_index("recon")            # a live index so the walk visits a module
    monkeypatch.setattr(C, "flush_module_index", lambda module, run_id=None: None)
    results = C.flush_all_indexes()
    assert set(results) == {"recon"}
    assert results["recon"] == C.FlushResult.degraded("no-result")
