"""Unit tier: the per-module checkpointer index + module_context seam (#120).

`checkpoints.py` reworks the process-wide pooled checkpointer into the ratified
per-module shape: a `module_context(name)` ContextVar routing checkpointer
resolution, a per-module in-memory `ModuleIndex` (lazily built, lock-guarded,
keyed on the deterministic #119 module-scoped thread_ids), BOUNDED latest-only
per-pass retention, fail-open flush hooks (run-terminal + shutdown) into the #94
pooled PG saver, and the lock-guarded read-only `agent_contexts` enumeration.
The #94 pooled PG saver is the flush TARGET only; the shared in-process
`InMemorySaver` remains the unset-context fallback.

All of this runs on pure in-memory state - no live model, no live database
(CODING_STANDARD sections 6, 10). The flush target is injected as a recording
fake so the unit tier never touches Postgres.
"""
from __future__ import annotations

import asyncio
import operator
import re

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from typing_extensions import Annotated, TypedDict

from polymerhus.app.llm import checkpoints as C
from polymerhus.app.llm.session_address import ModuleScopedSession


@pytest.fixture(autouse=True)
def _clean_module_state():
    """Isolate the process-global module registry + pooled saver per test."""
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
    """A real langgraph graph compiled on the given checkpointer - exercises the full
    saver surface (get_tuple / put / put_writes) without any LLM."""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(_CountState)
    graph.add_node("bump", lambda state: {"count": 1})
    graph.add_edge(START, "bump")
    graph.add_edge("bump", END)
    return graph.compile(checkpointer=checkpointer)


def _turn(graph, thread_id):
    graph.invoke({"count": 0}, {"configurable": {"thread_id": thread_id}})


def _commit(addresses):
    """Run one real graph turn per address under its module's context, so the index
    records each thread as committed."""
    by_module: dict[str, list] = {}
    for address in addresses:
        by_module.setdefault(address.module, []).append(address)
    for module, addrs in by_module.items():
        with C.module_context(module):
            graph = _compiled_graph(C.get_session_checkpointer())
            for address in addrs:
                _turn(graph, address.thread_id)


class _RecordingFlushTarget:
    """The fake #94 pooled PG saver: records every archived thread and can be made to
    fail so the flush hooks' fail-open path is exercised without Postgres."""

    def __init__(self):
        self.puts: list[tuple[str, str, dict]] = []
        self.writes: list[tuple[str, list, str]] = []
        self.fail_puts = False

    def put(self, config, checkpoint, metadata, new_versions):
        if self.fail_puts:
            raise RuntimeError("pg down")
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint.get("id", "?")
        self.puts.append((thread_id, checkpoint_id, dict(new_versions)))
        return {
            "configurable": {
                **config["configurable"],
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(self, config, writes, task_id, task_path=""):
        self.writes.append((config["configurable"]["thread_id"], list(writes), task_id))


# --- module_context resolution + copy_context propagation ---------------------

def test_module_context_routes_resolution_to_that_modules_index():
    """Unset context resolves the shared in-process fallback; a module context
    resolves that module's OWN index checkpointer - the SAME object every call (the
    module's lazy-built, cached index), and a DIFFERENT object per module."""
    fallback = C.get_session_checkpointer()
    assert isinstance(fallback, InMemorySaver)

    with C.module_context("recon"):
        recon_cp = C.get_session_checkpointer()
        assert recon_cp is not fallback
        assert C.get_session_checkpointer() is recon_cp  # same module -> same index

    with C.module_context("analysis"):
        analysis_cp = C.get_session_checkpointer()
        assert analysis_cp is not fallback
        assert analysis_cp is not recon_cp               # different module -> different index

    assert C.get_session_checkpointer() is fallback       # context reset -> fallback again


def test_module_context_propagates_into_executor_and_to_thread_work():
    """`copy_context` carries the module context into executor work, so offloaded
    stateful turns resolve the right module's index (G3): both the explicit
    copy_context mechanism over a `ThreadPoolExecutor` worker and the native
    `asyncio.to_thread` path (which wraps the worker in `copy_context`) see the same
    checkpointer as the entry point."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    with C.module_context("recon"):
        entry_cp = C.get_session_checkpointer()

        # concurrent.futures: run the worker under a copy of the entry context - the
        # exact mechanism asyncio.to_thread uses internally (Python 3.13 does not
        # auto-propagate contexts from a bare submit, so the offload must carry it).
        ctx = contextvars.copy_context()
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker_cp = executor.submit(ctx.run, C.get_session_checkpointer).result()
        assert worker_cp is entry_cp

        async def scenario():
            def offload():
                return C.get_session_checkpointer()

            to_thread_cp = await asyncio.to_thread(offload)
            assert to_thread_cp is entry_cp

        asyncio.run(scenario())


def test_module_context_resets_on_exit_and_nests():
    """The context is set for the entry point's FULL duration only: it resets on exit
    (even through an exception) and nested contexts restore the outer module."""
    with pytest.raises(RuntimeError):
        with C.module_context("recon"):
            _ = C.get_session_checkpointer()
            raise RuntimeError("boom")
    assert C.get_session_checkpointer() is not None
    assert not isinstance(C._MODULE_CTX.get(), str) or C._MODULE_CTX.get() is None

    with C.module_context("recon"):
        outer = C.get_session_checkpointer()
        with C.module_context("analysis"):
            assert C.get_session_checkpointer() is not outer
        assert C.get_session_checkpointer() is outer   # outer restored


# --- the module checkpointer is a WORKING langgraph saver ---------------------

def test_module_checkpointer_is_a_working_sync_and_async_saver():
    """The object `get_session_checkpointer` resolves under a module context is a real
    langgraph checkpointer: a StateGraph compiles on it and runs (sync and async),
    resuming its thread across invokes - proving existing call sites (create_agent /
    stateful_turn) keep working against the new seam."""
    with C.module_context("recon"):
        cp = C.get_session_checkpointer()
        thread_id = "recon:run-s:1:httpx:a:triager"
        graph = _compiled_graph(cp)
        for _ in range(3):
            _turn(graph, thread_id)
        tup = cp.get_tuple({"configurable": {"thread_id": thread_id}})
        assert tup is not None
        assert tup.checkpoint["channel_values"]["count"] == 3

        async def async_turns():
            graph_a = _compiled_graph(cp)
            for _ in range(3):
                await graph_a.ainvoke(
                    {"count": 0}, {"configurable": {"thread_id": thread_id}}
                )
            return await cp.aget_tuple({"configurable": {"thread_id": thread_id}})

        tup_a = asyncio.run(async_turns())
        assert tup_a.checkpoint["channel_values"]["count"] == 6


def test_stateful_turn_call_site_keeps_working_through_the_module_checkpointer():
    """The ubiquitous `stateful_turn` seam (the pattern every call site uses) runs
    through the module-resolved checkpointer and RESUMES its deterministic thread."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from polymerhus.app.llm.session import stateful_turn

    class _CountFake(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=str(len(messages))))]
            )

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    with C.module_context("recon"):
        cp = C.get_session_checkpointer()
        thread_id = ModuleScopedSession(
            "recon", "run-t", 2, "httpx", "https://a.example", role_id="triager"
        ).thread_id
        factory = lambda role: _CountFake()  # noqa: E731
        c1 = stateful_turn("assigner", thread_id, [HumanMessage(content="a")],
                           checkpointer=cp, model_factory=factory, observe=False)
        c2 = stateful_turn("assigner", thread_id, [HumanMessage(content="b")],
                           checkpointer=cp, model_factory=factory, observe=False)
        assert c2 != c1                       # the thread resumed, not reset


# --- bounded retention (Phase D), measured on the longest-horizon case ---------

def test_bounded_retention_latest_only_on_the_longest_horizon_pass():
    """Phase D on the WORST case, not the average: the longest-horizon pass - the
    maximum number of concurrent pods, each running the maximum number of turns (the
    longest conversation) - must keep the index bounded at (pods) x (1 checkpoint),
    never growing with the turn count. Measured at the worst point of the pass, not
    the average."""
    pods = 25
    turns = 40
    tids = [
        ModuleScopedSession(
            "recon", "run-long", i, "httpx", f"asset-{i}", role_id="triager"
        ).thread_id
        for i in range(pods)
    ]
    with C.module_context("recon"):
        cp = C.get_session_checkpointer()
        graph = _compiled_graph(cp)
        for turn in range(1, turns + 1):
            for tid in tids:
                _turn(graph, tid)
            if turn % 10 == 0:
                for tid in tids:
                    retained = list(cp.list({"configurable": {"thread_id": tid}}))
                    assert len(retained) == 1, (
                        f"turn {turn}: thread {tid} retained {len(retained)} "
                        f"checkpoints (must stay latest-only)"
                    )
        index = C._module_index("recon")
        assert len(index.committed_ids()) == pods
        total_retained = sum(
            len(list(cp.list({"configurable": {"thread_id": tid}}))) for tid in tids
        )
        assert total_retained == pods  # one latest checkpoint per committed thread
        # pruning must not break resume: the thread truly accumulated all turns
        last = cp.get_tuple({"configurable": {"thread_id": tids[0]}})
        assert last.checkpoint["channel_values"]["count"] == turns


# --- deterministic keys (G7a) --------------------------------------------------

def test_index_keys_are_the_deterministic_module_scoped_thread_ids():
    """Index entries key on the #119 module-scoped thread_id - a PURE function of
    (module, run, phase, tool, discriminator): no UUID, no time source in the key, so
    a post-crash enumeration re-derives the same key."""
    pods = [
        ModuleScopedSession("recon", "run-7", 2, "httpx", "https://a.example",
                            role_id="triager"),
        ModuleScopedSession("recon", "run-7", 2, "httpx", "https://b.example",
                            role_id="triager"),
        ModuleScopedSession("analysis", "run-7", 1, "openai", "asset-9",
                            role_id="analyst"),
    ]
    _commit(pods)

    recon = C._module_index("recon")
    analysis = C._module_index("analysis")
    assert set(recon.committed_ids()) == {p.thread_id for p in pods[:2]}
    assert analysis.committed_ids() == [pods[2].thread_id]

    uuid_shape = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    )
    for index in (recon, analysis):
        for tid in index.committed_ids():
            for segment in tid.split(":"):
                assert not uuid_shape.fullmatch(segment)


# --- agent_contexts: lock-guarded READ-ONLY enumeration ------------------------

def test_agent_contexts_matches_tool_only_ids_with_no_phase():
    """A thread composed WITHOUT a phase (tool present, no phase, no discriminator,
    no role) is a 3-part id (`recon:run1:httpx`); a phase-wildcard tool filter must
    still match it - the tool sits in the slot right after `run`, which the
    empty-dropping composition makes legal. Regression for the #120 address-matcher
    guard that rejected 3-part ids entirely."""
    pod = ModuleScopedSession("recon", "run-tool", None, "httpx", None, role_id=None)
    assert pod.thread_id == "recon:run-tool:httpx"
    _commit([pod])
    assert C.agent_contexts("run-tool", None, "httpx") == [pod.thread_id]


def test_agent_contexts_enumerates_committed_pod_contexts():
    """`agent_contexts(run_id, phase, tool)` enumerates a run's committed pod
    contexts across the module indexes - the exact deterministic thread_ids whose
    address matches the filter. None phase/tool are wildcards. No resumption logic."""
    pods = [
        ModuleScopedSession("recon", "run-1", 2, "httpx", "https://a.example",
                            role_id="triager"),
        ModuleScopedSession("recon", "run-1", 2, "httpx", "https://b.example",
                            role_id="triager"),
        ModuleScopedSession("recon", "run-1", 3, "nuclei", "https://a.example",
                            role_id="triager"),
        ModuleScopedSession("recon", "run-2", 2, "httpx", "https://c.example",
                            role_id="triager"),
        ModuleScopedSession("analysis", "run-1", 1, "openai", "asset-9",
                            role_id="analyst"),
    ]
    _commit(pods)

    assert C.agent_contexts("run-1", 2, "httpx") == [pods[0].thread_id, pods[1].thread_id]
    assert C.agent_contexts("run-1", 3, "nuclei") == [pods[2].thread_id]
    assert C.agent_contexts("run-2", 2, "httpx") == [pods[3].thread_id]
    assert C.agent_contexts("run-1", 1, "openai") == [pods[4].thread_id]
    assert C.agent_contexts("run-99", 2, "httpx") == []

    # wildcards: any phase / any phase+tool for a run
    run1 = {p.thread_id for p in pods if p.run_id == "run-1"}
    assert set(C.agent_contexts("run-1", None, None)) == run1
    assert set(C.agent_contexts("run-1", None, "httpx")) == {
        pods[0].thread_id, pods[1].thread_id,
    }
    # read-only: enumeration commits nothing new
    assert C.agent_contexts("run-1", 2, "httpx") == [pods[0].thread_id, pods[1].thread_id]


def test_agent_contexts_is_lock_guarded_under_concurrent_commits_and_reads():
    """Concurrent commits (executor threads, context propagated) and concurrent
    `agent_contexts` reads never race: every read returns a consistent snapshot and
    never raises."""
    from concurrent.futures import ThreadPoolExecutor

    pods = [
        ModuleScopedSession("recon", f"run-{i}", i, "httpx", f"asset-{i}",
                            role_id="triager")
        for i in range(20)
    ]

    def commit(pod):
        with C.module_context("recon"):
            graph = _compiled_graph(C.get_session_checkpointer())
            _turn(graph, pod.thread_id)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(commit, pods))

    for pod in pods:
        found = C.agent_contexts(pod.run_id, pod.phase, pod.tool)
        assert found == [pod.thread_id]
    assert len(C.agent_contexts("run-0", None, None)) == 1


# --- flush hooks: run-terminal + shutdown, fail-open ---------------------------

def test_flush_module_index_archives_into_flush_target_and_clears(monkeypatch):
    """The run-terminal flush iterates the index and archives every committed thread
    into the (fake, still-open) #94 pooled PG saver, REPLAYING an interrupted thread's
    pending writes so it resumes mid-stream; the archived threads are then dropped from
    the index so the process stays bounded. A second flush is a no-op."""
    pods = [
        ModuleScopedSession("recon", "run-9", 2, "httpx", "a", role_id="triager"),
        ModuleScopedSession("recon", "run-9", 2, "httpx", "b", role_id="triager"),
    ]
    _commit(pods)
    # an interrupt's pending writes (as a node writing to a channel before resuming)
    with C.module_context("recon"):
        cp = C.get_session_checkpointer()
        for i, pod in enumerate(pods):
            tup = cp.get_tuple({"configurable": {"thread_id": pod.thread_id}})
            cp.put_writes(
                tup.config,
                [("pending_events", [f"resume-{i}"])],
                f"task-{i}",
            )
    target = _RecordingFlushTarget()
    monkeypatch.setattr(C, "_saver", target)

    index = C._module_index("recon")
    assert set(index.committed_ids()) == {p.thread_id for p in pods}

    C.flush_module_index("recon")
    assert {t[0] for t in target.puts} == {p.thread_id for p in pods}
    assert {w[0] for w in target.writes} == {p.thread_id for p in pods}  # pending writes
    assert index.committed_ids() == []

    C.flush_module_index("recon")               # second flush: no-op, never raises


def test_flush_run_terminal_only_archives_that_runs_threads(monkeypatch):
    """Run-terminal flush is per RUN: flushing run-A archives and clears only run-A's
    committed threads; a concurrent run-B's threads stay in the index."""
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

    C.flush_module_index("recon", run_id="run-A")
    assert {t[0] for t in target.puts} == {p.thread_id for p in run_a}
    assert C._module_index("recon").committed_ids() == [run_b[0].thread_id]


def test_flush_failure_warns_and_drops_never_raises(monkeypatch, caplog):
    """A failing flush target warns and drops the thread (kept in the index so a later
    flush can retry); the hook NEVER raises (fail-open)."""
    pod = ModuleScopedSession("recon", "run-9", 2, "httpx", "a", role_id="triager")
    _commit([pod])
    target = _RecordingFlushTarget()
    target.fail_puts = True
    monkeypatch.setattr(C, "_saver", target)

    C.flush_module_index("recon")               # must not raise
    assert C._module_index("recon").committed_ids() == [pod.thread_id]
    assert any("flush" in record.message.lower() for record in caplog.records)


def test_flush_without_open_pooled_saver_is_a_noop(monkeypatch):
    """With no #94 pool open (no DSN / tests) the flush is a fail-open no-op: the
    in-memory state is the only store, so it is kept, and the hook never raises."""
    pod = ModuleScopedSession("recon", "run-9", 2, "httpx", "a", role_id="triager")
    _commit([pod])
    monkeypatch.setattr(C, "_saver", None)
    C.close_session_checkpointer()

    C.flush_module_index("recon")
    assert C._module_index("recon").committed_ids() == [pod.thread_id]


def test_flush_all_indexes_covers_every_live_module(monkeypatch):
    """The shutdown flush hook iterates every live module index and archives each
    committed thread into the still-open pooled saver (fail-open)."""
    pods = [
        ModuleScopedSession("recon", "run-1", 2, "httpx", "a", role_id="triager"),
        ModuleScopedSession("analysis", "run-1", 1, "openai", "asset-9",
                            role_id="analyst"),
    ]
    _commit(pods)
    target = _RecordingFlushTarget()
    monkeypatch.setattr(C, "_saver", target)

    C.flush_all_indexes()
    assert {t[0] for t in target.puts} == {p.thread_id for p in pods}
    assert C._module_index("recon").committed_ids() == []
    assert C._module_index("analysis").committed_ids() == []
