"""The append-only markdown hunt-store stub (#68, spec O12).

The hunt store is the orchestrator's durable working memory: every event of an
orchestration pass is appended, never rewritten, under `<root>/<run_id>/`.
Each record kind gets its own append-only markdown file; a record is a
`## <seq>` block whose body is YAML, so records round-trip with full type
fidelity. Records carry `_seq` (the monotonic append counter, giving the
whole store one ordering) and `_ref` (`<run_id>/<kind>-<seq>`) so records can
point at each other (e.g. a D8 hunt record's `config_ref`).

The real persistence is #68's seam; this stub is the phase-1 shape the
orchestrator writes today, and it must fail openly: a write failure raises
(callers degrade to a warning and keep serving - spec O3), a read failure
raises (the orchestrator degrades prior-insight retrieval to an empty set and
keeps serving - spec O4). Never a silent corruption.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Record kinds written by the orchestrator (spec O12, D67-13):
#   run         - one per orchestration pass
#   config      - one per dispatched direction (D3 HuntConfig)
#   hunt        - one per carried direction (D8 hunt record)
#   dispatch    - one per hunting-agent dispatch attempt (IA-2)
#   result      - one per completed hunt (IA-2 delivery)
#   unresolved  - one per fault degraded to unresolved at the depth cap (IA-1)
#   cut         - one per direction cut by the budget (O9)
#   back_edge   - one per targeted-recon request raised by a hunt (IA-6)
#   memory      - one per completed hunt, the revive-keyed insight (#70)
# Record kinds written by the hunting agent (#83, Q6) - exactly the two Q6
# declares, nothing more:
#   spec        - one per authored TestImplementationSpec instance (D4), with
#                 parent_spec_ref for re-author lineages (D67-03/D67-08)
#   evidence    - one per pod outcome (D5 + D6 consumption), hypothesis-
#                 indexed, carrying the derived D7 verdict
KINDS = (
    "run", "config", "hunt", "dispatch", "result",
    "unresolved", "cut", "back_edge", "memory",
    "spec", "evidence",
)


class HuntStore:
    """Append-only markdown hunt-store stub keyed by `(run_id, kind)`."""

    def __init__(self, root_dir: str | Path):
        self._root = Path(root_dir)

    def _file(self, run_id: str, kind: str) -> Path:
        if kind not in KINDS:
            raise ValueError(f"unknown hunt-store record kind {kind!r}; known: {KINDS}")
        # Memory is the one cross-run kind (#70): revive-keyed insights must
        # survive from one orchestration pass into the next (E1).
        if kind == "memory":
            return self._root / "memory.md"
        return self._root / run_id / f"{kind}.md"

    @staticmethod
    def _file_last_seq(path: Path) -> int:
        if not path.exists():
            return 0
        last = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                try:
                    last = max(last, int(line[3:]))
                except ValueError:
                    continue
        return last

    def _next_seq(self, run_id: str) -> int:
        """The store-wide append counter for `run_id`: one ordering across all
        of the run's kind files, so records of different kinds are ordered
        (a D8 hunt record follows its D3 config record, C11)."""
        last = 0
        if self._root.exists():
            for path in self._root.glob(f"{run_id}/*.md"):
                last = max(last, self._file_last_seq(path))
            last = max(last, self._file_last_seq(self._root / "memory.md"))
        return last + 1

    def append(self, run_id: str, kind: str, record: dict) -> str:
        """Append `record` under `(run_id, kind)`; return its `_ref`.

        Raises on write failure - the caller degrades to a warning and keeps
        serving (O3); the append is atomic per file (a failed write leaves the
        file untouched).
        """
        path = self._file(run_id, kind)
        seq = self._next_seq(run_id)
        stored = {"_seq": seq, "_ref": f"{run_id}/{kind}-{seq:04d}", **record}
        block = "## %04d\n%s" % (seq, yaml.safe_dump(stored, sort_keys=False))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(block)
        return stored["_ref"]

    def list_records(self, run_id: str, kind: str) -> list[dict]:
        """All records of `kind` for `run_id`, in append order."""
        path = self._file(run_id, kind)
        if not path.exists():
            return []
        # Split on the `## <seq>` headers, NOT on "\n## ": a naive split on the
        # bare header leaves the sequence number on the leading line of every
        # block after the first, which is not valid YAML ("0006\n_ref: ...").
        # Keeping the header as the split delimiter leaves each block's body
        # clean, so every record round-trips - a two-hunt file must yield two
        # records, never just the first.
        records: list[dict] = []
        for block in re.split(r"(?m)^## \d+\n", path.read_text(encoding="utf-8")):
            block = block.strip()
            if not block:
                continue
            try:
                records.append(yaml.safe_load(block))
            except yaml.YAMLError:
                logger.warning("hunt store: unreadable %s block in %s", kind, path)
        return [r for r in records if isinstance(r, dict)]

    def read_memory(self, revival_key: str) -> list[dict]:
        """The revive-keyed prior-hunt insights for `revival_key` (#70 seam).

        Fails open on the CALLER's side: a read error raises (O4), the
        orchestrator degrades to an empty insight set and keeps serving.
        """
        return [r for r in self.list_records("memory", "memory")
                if r.get("revival_key") == revival_key]