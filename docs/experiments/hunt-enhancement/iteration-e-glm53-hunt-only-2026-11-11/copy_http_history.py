#!/usr/bin/env python3
"""Copy one project's HTTP-history store to a fresh project id inside Kali.

The store is `<root>/<project_id>/http-history/{history.sqlite3,bodies/}`.
A plain directory copy is WRONG: the `flows` table carries its own
`project_id`, and every read filters on it, so a copied store under the new
directory would answer "no such traffic". This script takes a consistent
SQLite backup of the source database, rewrites `flows.project_id` to the new
id, and copies the content-addressed body blobs.

Run inside the Kali container (it owns `/data` and the `sqlite3` module):

    OLD_PROJECT_ID=<old> NEW_PROJECT_ID=<new> python3 copy_http_history.py

The source database may be live (WAL). `sqlite3.Connection.backup` reads a
consistent snapshot without stopping the edge server.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(os.environ.get("KALI_HTTP_HISTORY_ROOT", "/data"))


def main() -> int:
    old = os.environ.get("OLD_PROJECT_ID", "").strip()
    new = os.environ.get("NEW_PROJECT_ID", "").strip()
    if not old or not new:
        raise SystemExit("OLD_PROJECT_ID and NEW_PROJECT_ID are required")
    if old == new:
        raise SystemExit("the old and new project ids must differ")

    source = ROOT / old / "http-history"
    target = ROOT / new / "http-history"
    source_db = source / "history.sqlite3"
    if not source_db.is_file():
        print(f"no HTTP history at {source}; nothing to copy")
        return 0
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"target HTTP history {target} is not empty")

    (target / "bodies").mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(target / "history.sqlite3")
    try:
        src.backup(dst)
        dst.execute("UPDATE flows SET project_id = ?", (new,))
        dst.commit()
        dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        rows = dst.execute("SELECT count(*) FROM flows WHERE project_id = ?",
                           (new,)).fetchone()[0]
        total = dst.execute("SELECT count(*) FROM flows").fetchone()[0]
    finally:
        dst.close()
        src.close()

    bodies = 0
    for blob in (source / "bodies").glob("*.blob"):
        shutil.copy2(blob, target / "bodies" / blob.name)
        bodies += 1

    if rows != total:
        raise SystemExit(
            f"rewrite mismatch: {rows} of {total} flows carry project_id {new}"
        )
    print(f"copied {rows} HTTP artifacts and {bodies} bodies from {old} to {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
