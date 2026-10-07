"""The app-owned atomic whole-file write primitive (#340).

Every store that rewrites a whole file (a per-project YAML memory file, a
prose skill file) must make the rewrite atomic: a reader sees either the
previous complete file or the new complete file, never a truncated target.
The naive `path.open("w")` truncates before writing, so a kill or an
exception mid-write leaves a malformed file that every later read rejects
(the #340 hunter `notes.yaml` corruption, which also blocked the durable
pod-export record).

This module is the ONE construction point for that idiom. The caller renders
the full body in memory; `write_text_atomic` / `write_bytes_atomic` then write
it to a sibling temp file in the SAME directory, flush and `fsync` the file,
`os.replace` it onto the target (an atomic rename on POSIX), and `fsync` the
parent directory so the rename itself is durable. The temp file is cleaned up
best-effort. The same idiom lived privately in `hunt_store`, `app/auth/store.py`,
and the skill store; they now route here.

This module performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

__all__ = ["write_bytes_atomic", "write_text_atomic"]


def _fsync_dir(directory: Path) -> None:
    """Best-effort `fsync` of a directory so a rename's entry is durable.

    On POSIX a rename's directory entry is not durable across a power loss
    without an `fsync` on the parent directory (the classic ext4 zero-length
    case), so `write_bytes_atomic` calls this after `os.replace`. A platform
    that cannot open a directory for `fsync` (or a transient `OSError`) is
    tolerated: the write is still atomic and process-crash durable."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_bytes_atomic(path: str | Path, data: bytes) -> None:
    """Write `data` to `path` atomically (temp in the same dir + `os.replace`).

    The temp file is fully written, flushed, and `fsync`ed before the rename,
    and the parent directory is `fsync`ed after it, so a crash after the
    rename leaves a durable complete file and a crash before it leaves the
    previous file untouched. A caller-visible failure (an `OSError`, a kill
    mid-write) never leaves a partial target; the temp is unlinked
    best-effort."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        _fsync_dir(target.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def write_text_atomic(path: str | Path, text: str) -> None:
    """The UTF-8 text form of `write_bytes_atomic`."""
    write_bytes_atomic(path, text.encode("utf-8"))
