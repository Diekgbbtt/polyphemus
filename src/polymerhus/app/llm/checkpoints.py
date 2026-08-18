"""The stateful-agent checkpointer store: a per-module in-memory index + the pooled
Postgres flush target (#94, refactored by #120).

Every stateful agent (`stateful_turn`, `session.py`) resumes from a checkpoint. This
module owns the RUNTIME checkpointer shape of the module-runtime-independence
refactor: each module's stateful turns resolve a per-module in-memory `ModuleIndex`
(a lazily-built, lock-guarded per-thread in-memory saver + in-memory store per
thread, keyed on the deterministic module-scoped `thread_id` from #119), with
BOUNDED latest-only retention per pass (Phase D), flush hooks that archive the
index into the process-wide #94 pooled `PostgresSaver` at run-terminal and at
shutdown (fail-open), and the lock-guarded read-only `agent_contexts` enumeration
the resume seam implements against (G7a).

Resolution (`get_session_checkpointer()`), ratified in `module-runtime-architecture.md`
section 5.15: a module context set (`module_context(name)` at the module's outermost
runtime entry point, propagated via `copy_context` into executor work) resolves that
module's index checkpointer; a context UNSET (bootstrap, admin reads) resolves the
shared in-process `InMemorySaver` fallback - existing checkpointer call sites keep
working against either. The #94 pooled PG saver is the FLUSH TARGET only, never a
runtime resolution: it is pre-warmed at startup, archived into at run-terminal and
shutdown, and closed after the last flush (G1).

Fail-open: with no DSN (tests / a bare environment) or if Postgres cannot be opened,
`get_session_checkpointer()` returns a shared in-process `InMemorySaver`, and a
flush with no open pool is a no-op - a stateful agent still works, its memory just
does not persist beyond the process.

Importing this module performs no I/O, opens no connection, and imports no langgraph
(CODING_STANDARD section 6): the saver classes resolve lazily inside the functions
that need them. Its only top-level import beyond pure stdlib is the #119 address
composition it keys on.
"""
from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import logging
import threading
from typing import Any, Iterator

from polymerhus.app.llm.session_address import _seg

logger = logging.getLogger(__name__)

# The process-wide pooled saver (the flush target, set by setup), its pool, and the
# in-process unset-context fallback.
_saver = None
_pool = None
_fallback = None
_lock = threading.Lock()

# Pool sizing: enough for the concurrent recon pods (MAX_PODS) plus the serialized
# analysis/hunt agents, with headroom. Kept modest so a run never exhausts Postgres.
_POOL_MAX = 24

# The module context (`module_context(name)`), set at a module's outermost runtime
# entry point for its full duration. `copy_context` propagates it into executor work
# (concurrent.futures and asyncio.to_thread), so offloaded stateful turns resolve the
# right module's index (G3, entry-point residency).
_MODULE_CTX: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("module-context", default=None)
)

# The per-module in-memory index registry, lazily built on first resolution and
# owned by the worker loop (lock-guarded because the resume seam reads it
# cross-thread and the shutdown fan-out flushes it).
_module_indexes: dict[str, "ModuleIndex"] = {}
_indexes_lock = threading.Lock()


@contextlib.contextmanager
def module_context(name: str) -> Iterator[None]:
    """Set the module context for the entry point's full duration (G3).

    The OUTERMOST runtime entry point of each module opens this: recon `run_pipeline`,
    analysis `start_analysis` / the consume task and `run_analyser_chunked`, hunting
    `start_hunting`. While it is set, `get_session_checkpointer()` resolves that
    module's in-memory index. `copy_context` carries the ContextVar into executor
    work, so offloaded stateful turns resolve the same module. The context resets on
    exit (also through an exception)."""
    token = _MODULE_CTX.set(name)
    try:
        yield
    finally:
        _MODULE_CTX.reset(token)


@dataclasses.dataclass
class _ThreadPair:
    """One committed session thread's in-memory store: a bounded in-memory saver
    (latest-only retention) and the in-memory store that pairs with it (#85 seam,
    inert until wired)."""

    saver: Any
    store: Any


class ModuleIndex:
    """A module's in-memory checkpointer index (#120, G6 + Phase D).

    Owned by the worker loop and lazily built on the first stateful resolution under
    the module's context; lock-guarded because the resume seam reads it cross-thread
    (`agent_contexts`) and the shutdown fan-out flushes it. Each entry keys a
    DETERMINISTIC module-scoped `thread_id` (#119) to a per-thread pair (in-memory
    saver + in-memory store) with LATEST-ONLY retention, so a worst-case pass stays
    bounded at (committed threads) x (1 checkpoint) - measured on the longest-horizon
    case, never the average. Flush hooks iterate the committed threads at run-terminal
    and at shutdown, fail-open, into the still-open #94 pooled PG saver."""

    def __init__(self, module: str) -> None:
        self.module = module
        self._lock = threading.Lock()
        self._threads: dict[str, _ThreadPair] = {}
        self._committed: set[str] = set()
        self._checkpointer: Any = None

    def checkpointer(self) -> Any:
        """The module's resolved langgraph checkpointer - a per-thread-routing facade
        over this index, created lazily and cached (the same object every resolution)."""
        if self._checkpointer is None:
            self._checkpointer = _module_scoped_saver(self)
        return self._checkpointer

    def pair(self, thread_id: str) -> _ThreadPair:
        """Resolve a thread's (bounded saver, store) pair, lazily building it on first
        touch. `thread_id` is the deterministic #119 module-scoped composition."""
        with self._lock:
            pair = self._threads.get(thread_id)
            if pair is None:
                pair = _ThreadPair(_bounded_saver(), _new_store())
                self._threads[thread_id] = pair
            return pair

    def pairs(self) -> list[_ThreadPair]:
        with self._lock:
            return list(self._threads.values())

    def commit(self, thread_id: str) -> None:
        """Record that a thread has committed a checkpoint (its state is archivable
        and enumerable). Called by the module checkpointer after each successful put."""
        with self._lock:
            self._committed.add(thread_id)

    def drop(self, thread_id: str) -> None:
        with self._lock:
            self._committed.discard(thread_id)
            self._threads.pop(thread_id, None)

    def committed_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._committed)

    def flush(self, target: Any, run_id: str | None = None) -> None:
        """Archive the committed threads into the flush target and clear them from the
        index. With `run_id`, only that run's threads are archived (run-terminal flush);
        with None, the whole index (module drain / shutdown flush). Fail-open: a thread
        whose archive fails warns and is kept in the index (a later flush can retry);
        the hook never raises. With no target (pool not open) it is a no-op that keeps
        the in-memory state - the only store in a no-DSN process."""
        if target is None:
            logger.debug(
                "module index %s: no flush target (pooled PG saver closed); "
                "keeping in-memory state", self.module)
            return
        with self._lock:
            committed = sorted(self._committed)
        archived: list[str] = []
        for thread_id in committed:
            if run_id is not None and not _address_matches(
                thread_id, self.module, run_id, None, None
            ):
                continue
            try:
                self._archive_thread(target, thread_id)
                archived.append(thread_id)
            except Exception as exc:  # noqa: BLE001 - fail-open flush, never raises
                logger.warning(
                    "module index %s: flush of thread %s failed (fail-open, "
                    "dropped): %s", self.module, thread_id, exc)
        if archived:
            with self._lock:
                for thread_id in archived:
                    self._committed.discard(thread_id)
                    self._threads.pop(thread_id, None)

    def _archive_thread(self, target: Any, thread_id: str) -> None:
        """Replay a thread's retained checkpoints into the flush target (the #94 pooled
        PG saver), including its pending writes, so the archived thread resumes."""
        pair = self.pair(thread_id)
        config = {"configurable": {"thread_id": thread_id}}
        for tup in pair.saver.list(config):
            versions = tup.checkpoint.get("channel_versions", {})
            put_config = target.put(config, tup.checkpoint, tup.metadata, versions)
            pending = getattr(tup, "pending_writes", None) or ()
            by_task: dict[str, list] = {}
            for task_id, channel, value in pending:
                by_task.setdefault(task_id, []).append((channel, value))
            for task_id, writes in by_task.items():
                target.put_writes(put_config, writes, task_id)


def _module_index(module: str) -> ModuleIndex:
    """Resolve (and lazily build) a module's index. Lock-guarded: the resume seam and
    the shutdown fan-out read the registry cross-thread."""
    with _indexes_lock:
        index = _module_indexes.get(module)
        if index is None:
            index = ModuleIndex(module)
            _module_indexes[module] = index
        return index


def _address_matches(thread_id: str, module: str, run_id: str, phase, tool) -> bool:
    """True when a module-scoped thread id could have been composed for the given
    (run_id, phase, tool) filter. `module`/`run_id` lead the #119 composition and
    `phase`/`tool` are the next discriminator slots, each compared in its ESCAPED
    form so a separator inside a discriminator can never be misread as a boundary.

    The composition DROPS empty segments, so a None filter is a slot skip, not a
    constraint: with a phase filter, the tool sits in the slot right after the
    matched phase; with NO phase filter, a `tool` filter must match the segment
    right after `run` (an id composed without a phase) OR the one after a present
    phase slot - exactly the ids the composition can actually produce."""
    parts = thread_id.split(":")
    if len(parts) < 2 or parts[0] != _seg(module) or parts[1] != _seg(run_id):
        return False
    if phase is not None:
        if len(parts) < 3 or parts[2] != _seg(phase):
            return False
        if tool is not None and (len(parts) < 4 or parts[3] != _seg(tool)):
            return False
        return True
    if tool is None:
        return True
    return len(parts) >= 3 and (
        parts[2] == _seg(tool)
        or (len(parts) >= 4 and parts[3] == _seg(tool))
    )


def _module_scoped_saver(index: ModuleIndex) -> Any:
    """Build the module-resolved langgraph checkpointer facade (lazily, so importing
    this module imports no langgraph). The facade routes every graph config by its
    thread_id to the index's per-thread bounded saver, delegating the langgraph
    checkpoint surface, and marks each thread committed on write."""
    global _scoped_saver_cls
    if _scoped_saver_cls is None:
        from langgraph.checkpoint.base import BaseCheckpointSaver

        class _ModuleScopedSaver(BaseCheckpointSaver[str]):
            def __init__(self, index_):
                super().__init__()
                self._index = index_

            def _thread_id(self, config) -> str:
                return config["configurable"]["thread_id"]

            def _saver_for(self, config):
                return self._index.pair(self._thread_id(config)).saver

            def get_tuple(self, config):
                return self._saver_for(config).get_tuple(config)

            def list(self, config=None, *, filter=None, before=None, limit=None):
                if config is None:
                    for pair in self._index.pairs():
                        yield from pair.saver.list(
                            None, filter=filter, before=before, limit=limit)
                else:
                    yield from self._saver_for(config).list(
                        config, filter=filter, before=before, limit=limit)

            def put(self, config, checkpoint, metadata, new_versions):
                result = self._saver_for(config).put(
                    config, checkpoint, metadata, new_versions)
                self._index.commit(self._thread_id(config))
                return result

            def put_writes(self, config, writes, task_id, task_path=""):
                return self._saver_for(config).put_writes(
                    config, writes, task_id, task_path)

            def get_next_version(self, current, channel):
                return _version_saver().get_next_version(current, channel)

            def delete_thread(self, thread_id):
                self._index.drop(thread_id)

            async def aget_tuple(self, config):
                return await self._saver_for(config).aget_tuple(config)

            async def alist(self, config=None, *, filter=None, before=None, limit=None):
                for item in self.list(config, filter=filter, before=before, limit=limit):
                    yield item

            async def aput(self, config, checkpoint, metadata, new_versions):
                result = await self._saver_for(config).aput(
                    config, checkpoint, metadata, new_versions)
                self._index.commit(self._thread_id(config))
                return result

            async def aput_writes(self, config, writes, task_id, task_path=""):
                return await self._saver_for(config).aput_writes(
                    config, writes, task_id, task_path)

            async def adelete_thread(self, thread_id):
                self.delete_thread(thread_id)

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

        _scoped_saver_cls = _ModuleScopedSaver
    return _scoped_saver_cls(index)


_scoped_saver_cls = None


def _bounded_saver() -> Any:
    """A lazily-defined `InMemorySaver` subclass whose per-thread retention is
    LATEST-ONLY (Phase D): after each `put` it drops every older checkpoint of that
    thread (and their writes and now-unreferenced blobs), so a pass's retained state
    is bounded at (committed threads) x (1 checkpoint) no matter how long the
    conversation grows."""
    global _bounded_saver_cls
    if _bounded_saver_cls is None:
        from langgraph.checkpoint.memory import InMemorySaver

        class _BoundedInMemorySaver(InMemorySaver):
            def put(self, config, checkpoint, metadata, new_versions):
                result = super().put(config, checkpoint, metadata, new_versions)
                self._prune_latest_only(config["configurable"]["thread_id"])
                return result

            def _prune_latest_only(self, thread_id):
                storage = self.storage.get(thread_id)
                if not storage:
                    return
                for ns, checkpoints in storage.items():
                    if len(checkpoints) <= 1:
                        continue
                    latest = max(checkpoints.keys())
                    for checkpoint_id in [c for c in checkpoints if c != latest]:
                        del checkpoints[checkpoint_id]
                        self.writes.pop((thread_id, ns, checkpoint_id), None)
                    referenced = set()
                    entry = self.storage[thread_id][ns].get(latest)
                    if entry is not None:
                        checkpoint = self.serde.loads_typed(entry[0])
                        for channel, version in checkpoint.get(
                            "channel_versions", {}
                        ).items():
                            referenced.add((channel, version))
                    for key in list(self.blobs.keys()):
                        if key[0] == thread_id and key[1] == ns and key[2:] not in referenced:
                            del self.blobs[key]

        _bounded_saver_cls = _BoundedInMemorySaver
    return _bounded_saver_cls()


_bounded_saver_cls = None

# A scratch InMemorySaver whose (stateless) `get_next_version` format the module
# facade reuses, so channel versions stay consistent with the per-thread savers.
_version_saver_obj = None


def _version_saver() -> Any:
    global _version_saver_obj
    if _version_saver_obj is None:
        from langgraph.checkpoint.memory import InMemorySaver

        _version_saver_obj = InMemorySaver()
    return _version_saver_obj


def _new_store() -> Any:
    """A fresh in-memory store for a thread's pair (#85 long-term memory seam, inert
    until that ticket wires it)."""
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()


def setup_session_checkpointer(dsn: str | None = None) -> None:
    """Open the process-wide pooled `PostgresSaver` at app startup (idempotent).

    The pooled saver is the FLUSH TARGET of every module's in-memory index: it is
    pre-warmed here and archived into at run-terminal and at shutdown, never served as
    a runtime resolution (see `get_session_checkpointer`). Resolves `dsn` (or the app
    `POSTGRES_DSN`); with none, leaves the store unset so flushes are fail-open no-ops.
    Fail-open: any failure to open Postgres logs and leaves the store unset rather
    than blocking startup."""
    global _saver, _pool
    with _lock:
        if _saver is not None:
            return
        resolved = dsn
        if resolved is None:
            try:
                from polymerhus.app.config import config as app_config
                resolved = getattr(app_config, "POSTGRES_DSN", None)
            except Exception:  # noqa: BLE001
                resolved = None
        if not resolved:
            logger.warning("session checkpointer: no POSTGRES_DSN; stateful agent "
                           "memory will not persist (in-process fallback)")
            return
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
                resolved, max_size=_POOL_MAX, open=True,
                # PostgresSaver requires autocommit + dict rows; prepare_threshold=0
                # avoids server-side prepared-statement churn across pooled conns.
                kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
            )
            saver = PostgresSaver(pool)
            saver.setup()  # idempotent DDL
            _pool, _saver = pool, saver
            logger.info("session checkpointer: pooled PostgresSaver open (max_size=%d)", _POOL_MAX)
        except Exception as exc:  # noqa: BLE001 - never block startup on it
            logger.warning("session checkpointer: could not open pooled Postgres (%s); "
                           "stateful agent memory degraded to in-process", exc)


def get_session_checkpointer():
    """Resolve the checkpointer for the CURRENT context (module-runtime-architecture
    section 5.15): a module context set -> that module's in-memory index checkpointer
    (per-thread in-memory saver + store, latest-only retention, keyed on the #119
    module-scoped thread_ids); context unset -> the shared in-process `InMemorySaver`
    fallback. Existing checkpointer call sites keep working against either; the pooled
    PG saver is reached through the flush hooks, never here."""
    module = _MODULE_CTX.get()
    if module is not None:
        return _module_index(module).checkpointer()
    global _fallback
    if _fallback is None:
        with _lock:
            if _fallback is None:
                from langgraph.checkpoint.memory import InMemorySaver
                _fallback = InMemorySaver()
    return _fallback


def agent_contexts(run_id: str, phase=None, tool=None) -> list[str]:
    """Lock-guarded READ-ONLY enumeration of a run's committed pod contexts across the
    module indexes (module-runtime-architecture.md section 6, G7a): the deterministic
    module-scoped thread_ids whose #119 address matches (run_id[, phase[, tool]]).
    A None phase/tool is a wildcard on that position. Contains NO resumption logic -
    this is the contract surface a future resume agent implements against."""
    with _indexes_lock:
        modules = list(_module_indexes.items())
    found: list[str] = []
    for module, index in modules:
        for thread_id in index.committed_ids():
            if _address_matches(thread_id, module, run_id, phase, tool):
                found.append(thread_id)
    return sorted(found)


def flush_module_index(module: str, run_id: str | None = None) -> None:
    """Run-terminal (per `run_id`) or full-module flush hook: archive the module
    index's committed threads into the still-open #94 pooled PG saver. Fail-open: any
    failure warns and drops that thread; the hook never raises. With no open pooled
    saver it is a no-op."""
    with _lock:
        target = _saver
    with _indexes_lock:
        index = _module_indexes.get(module)
    if index is None:
        return
    index.flush(target, run_id=run_id)


def flush_all_indexes() -> None:
    """Shutdown flush hook (G7c): archive every live module index's committed threads
    into the still-open #94 pooled PG saver (fail-open). Call BEFORE
    `close_session_checkpointer`."""
    with _indexes_lock:
        modules = list(_module_indexes)
    for module in modules:
        flush_module_index(module)


def close_session_checkpointer() -> None:
    """Close the pool at app shutdown (idempotent). Call AFTER the shutdown flush
    (`flush_all_indexes`) so the flush target is still open for the tail."""
    global _saver, _pool
    with _lock:
        if _pool is not None:
            try:
                _pool.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("session checkpointer: pool close failed (%s)", exc)
        _saver = None
        _pool = None
