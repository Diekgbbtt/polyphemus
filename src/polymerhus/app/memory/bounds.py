"""The shared bounded-retention primitive (the hunting-memory lift, #341).

A whole-file memory store rewrites its entire file on every append, so an
unbounded record list makes the rewrite cost grow linearly with the run and can
grow one file without limit (the observed 18 MB hunter `notes.yaml`). THIS
module is the ONE home for the bound: `retain_bounded_records` keeps the newest
records and evicts the oldest until the list fits a documented record-count OR
serialized-size ceiling, and `rendered_len` / `notes_body_len` measure the
exact YAML rendering a caller will write.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import yaml


def rendered_len(body: Any) -> int:
    """The byte length of the exact YAML rendering a whole-file write lands, so
    the size bound measures what actually reaches disk."""
    return len(yaml.safe_dump(body, sort_keys=False).encode("utf-8"))


def notes_body_len(notes: list[dict]) -> int:
    """The `memory.yaml` file's byte length for a notes list (the `notes:`
    wrapper included), so the bound measures the whole file."""
    return rendered_len({"notes": notes})


def retain_bounded_records(
    records: list[dict],
    *,
    max_records: int,
    max_bytes: int,
    protected: Callable[[dict], bool] | None = None,
    render: Callable[[Any], int] = rendered_len,
) -> list[dict]:
    """Bound a whole-file notes record list (issue #341).

    `records` is oldest-first (the natural append order). The NEWEST records are
    kept: while the list exceeds `max_records` records or its rendering exceeds
    `max_bytes` bytes, the OLDEST record is dropped, so the whole-file rewrite
    cost stays O(bound) instead of growing without limit over a long run.
    `render` measures the exact body a caller will write (the bare list by
    default, or the `notes:` wrapper for `memory.yaml`).

    A record for which `protected(record)` is true is dropped only after every
    unprotected record, so the durable prior-insight records survive ordinary
    eviction. When the protected records ALONE exceed the bound the hard ceiling
    still trims the oldest, so the bound is absolute. The newest record is
    always kept whole - a single record larger than the ceiling is never
    truncated (the write must land).
    """
    kept = list(records)
    while len(kept) > 1 and (
        len(kept) > max_records or render(kept) > max_bytes
    ):
        drop = next(
            (i for i, record in enumerate(kept)
             if not (protected is not None and protected(record))),
            0,
        )
        del kept[drop]
    return kept


__all__ = [
    "notes_body_len",
    "rendered_len",
    "retain_bounded_records",
]
