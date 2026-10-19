"""The shared per-project bounded-record store base (the hunting-memory lift).

Every hunting-style memory store repeats three mechanics: a per-project write
lock serialising its check-then-write / read-modify-write critical section, an
atomic whole-file YAML write, and a write-time record bound so a long run cannot
grow one file without limit (#341). THIS module is the ONE home for those
mechanics; a consuming store (hunting's `HunterMemoryStore` / `ThreatModelStore`, and
the analysis memory store) subclasses `BoundedRecordStore` and keeps its own
paths and its own read semantics - a store chooses fail-open or fail-loud on a
corrupt file, so only the write side is shared.

The whole-file write routes through the app-owned atomic primitive
(`app.atomic_write`); the bound is the shared `retain_bounded_records`.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.memory.bounds import rendered_len, retain_bounded_records

# Per-project write serialisation (the pattern's I2): a store's check-then-write
# gate and its read-modify-write notes surface can run from different threads
# (the async caller offloads reads to worker threads while writes stay on the
# loop). A per-project lock covers the whole critical section regardless of
# which thread calls, so a gate is not TOCTOU and concurrent appends never lose
# a record. The registry is shared across the consuming stores; it guards only
# in-process threads.
_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


def project_lock(project_id: str) -> threading.Lock:
    """The shared per-project lock, created once (the registry itself is guarded
    against concurrent creation)."""
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(project_id)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_LOCKS[project_id] = lock
        return lock


class BoundedRecordStore:
    """The minimal base for a per-project, whole-file YAML record store.

    A subclass supplies its paths and its read semantics and calls `_lock_for`
    around a critical section, `_bounded` for the retained records under its own
    bounds, and `_dump_yaml_atomic` for the whole-file write. Only the write
    side is shared: a store's fail-open vs fail-loud read contract stays its own.
    """

    @staticmethod
    def _lock_for(project_id: str) -> threading.Lock:
        return project_lock(project_id)

    @staticmethod
    def _dump_yaml_atomic(path: Path, body: Any) -> None:
        """Write `body` as YAML atomically through the shared app primitive
        (#340): render the body in memory, then temp + fsync + `os.replace`, so
        a crash mid-dump leaves the previous file content intact and never a
        partial target."""
        write_text_atomic(path, yaml.safe_dump(body, sort_keys=False))

    @staticmethod
    def _bounded(
        records: list[dict],
        *,
        max_records: int,
        max_bytes: int,
        protected: Callable[[dict], bool] | None = None,
        render: Callable[[Any], int] = rendered_len,
    ) -> list[dict]:
        """The records retained under a write-time bound (the shared
        `retain_bounded_records`)."""
        return retain_bounded_records(
            records,
            max_records=max_records,
            max_bytes=max_bytes,
            protected=protected,
            render=render,
        )


__all__ = ["BoundedRecordStore", "project_lock"]
