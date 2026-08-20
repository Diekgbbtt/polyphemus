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

# The FIXED store root (seam 3.4, #110): the append-only hunt store lives at
# `src/polymerhus/attack/hunting/data/hunts/` - no env var. The explicit-root
# constructor is kept for the tests/the module tests' temp stores.
HUNT_STORE_ROOT = Path(__file__).resolve().parent / "data" / "hunts"

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

    def __init__(self, root_dir: str | Path | None = None):
        """The append-only store rooted under `root_dir` (default: the FIXED
        seam root `src/polymerhus/attack/hunting/data/hunts/`)."""
        self._root = Path(root_dir) if root_dir is not None else HUNT_STORE_ROOT
        self._project_memory: ProjectMemoryStore | None = None

    @property
    def project_memory(self) -> ProjectMemoryStore:
        """The per-project memory store (#70/#137) on the SAME durable seam.

        The orchestrator's `tools.store_reads` handle is this `HuntStore`, so
        one funnel serves both the per-run append-only trail (above) and the
        per-project configs + notes memory (#138). Lazy-constructed so a store
        that never touches memory pays no cost and any folder it creates is a
        write, not a read."""
        if self._project_memory is None:
            self._project_memory = ProjectMemoryStore(self._root)
        return self._project_memory

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


class ProjectMemoryStore:
    """The per-project hunt-orchestrator memory (#70, spec #137, ticket #138).

    A persistent, per-project store of two bodies of knowledge - hunt configs
    (the accumulated research-direction stamps; the hunting memory that keeps
    exploration from overlapping) and notes (per analyzed `(unit, fault)` pair
    reasoning artifacts NOT in the config: refusal reasons w/ evidence, missing
    adversarial capability, environmental constraints, implicit testing
    primitives, forward-useful notes). A project folder is created lazily at the
    first write; it is never created eagerly.

    Layout: `<store_root>/projects/<project_id>/{configs.yaml, notes.yaml}`.
    Each file accumulates YAML records monotonically (append-only, each with a
    per-file monotonic `_seq` and a `_ref` - sequences restart per file, so order
    is latest-first WITHIN a file, not store-wide), so re-analysis layers
    knowledge and history is preserved; a read returns latest-first
    (read-latest), noting the sequences so the latest version of a given key is
    distinguishable.

    Determinism + fail-open: writes raise on failure (the caller degrades to a
    warning and keeps serving - O3), reads raise on failure (the orchestrator
    degrades to an empty set and keeps serving - O4). Never a silent corruption.

    This module imports no driver and performs no I/O at import (CODING_STANDARD
    section 6).
    """

    # The closed enum of note kinds (#137, Q3). `constraint` is merged into
    # `hypothesis_refusal`; these three are canonical.
    NOTE_KINDS = ("hypothesis_refusal", "implicit_test_primitive", "freeform")

    def __init__(self, root_dir: str | Path):
        self._root = Path(root_dir)

    # -- paths -------------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return self._root / "projects" / str(project_id)

    def _configs_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "configs.yaml"

    def _notes_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "notes.yaml"

    @classmethod
    def _read_records(cls, path: Path) -> list[dict]:
        """All records in `path`, in append order; empty for a missing file.

        A CORRUPT/unparseable file raises (O4) rather than returning [] - the
        write paths here rewrite the whole file on append, so returning [] on a
        corrupt read and then rewriting would silently destroy every earlier
        record. Failing loudly (the caller degrades to a warning and keeps
        serving) preserves the append-only history guarantee."""
        if not path.exists():
            return []
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(f"hunt store: unreadable memory file {path}: {exc}") from exc
        if isinstance(loaded, list):
            return [r for r in loaded if isinstance(r, dict)]
        if isinstance(loaded, dict):
            return [r for r in loaded.values() if isinstance(r, dict)]
        return []

    @staticmethod
    def _next_seq(records: list[dict]) -> int:
        """The next monotonic append counter: one past the highest `_seq` so a
        `_ref`/`_seq` never collides under a partial/degraded read (max+1, not
        count+1)."""
        return max([int(r.get("_seq", 0)) for r in records] or [0]) + 1

    @classmethod
    def _write_records(cls, path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(records, fh, sort_keys=False)

    # -- configs (direction-stamp memory) -----------------------------------

    def append_config(self, project_id: str, record: dict) -> str:
        """Monotonically append a hunt-config direction stamp for `project_id`;
        return its `_ref`. The config set IS the overlap-prevention memory."""
        records = self._read_records(self._configs_file(project_id))
        seq = self._next_seq(records)
        stored = {"_seq": seq, "_ref": f"config-{seq:04d}", **record}
        records.append(stored)
        self._write_records(self._configs_file(project_id), records)
        return stored["_ref"]

    def read_configs(self, project_id: str) -> list[dict]:
        """All hunt-config direction stamps for `project_id`, latest-first."""
        return list(reversed(self._read_records(self._configs_file(project_id))))

    def read_memories(
        self,
        project_id: str,
        *,
        parent_key: str | None = None,
        key_keyword: str | None = None,
        body_keyword: str | None = None,
    ) -> list[dict]:
        """The note + hunt-config reading tool's grep-match read (#140): a
        combined read over the project's notes and hunt configs.

        Filters (combinable or singular, applied to BOTH notes and configs):
          parent_key  - the exact parent index `unit_id:fault_class` (or a full
                        key); yields that pair's notes + configs.
          key_keyword - case-insensitive substring over the KEYS.
          body_keyword- case-insensitive substring over the BODY/insight.
        Returns matching records latest-first (read-latest), each tagged with
        its `_ref` and a `memory_kind` ("note" | "config") so the caller can
        disambiguate. Zero matches is a valid empty result, never a failure.
        All retrieval matching lives strictly inside this store (ticket #140)."""
        notes = self.read_notes(project_id, parent_key=parent_key,
                                key_keyword=key_keyword, body_keyword=body_keyword)
        configs = self.read_configs(project_id)
        out: list[dict] = []
        parent = parent_key.lower() if parent_key else None
        key_kw = key_keyword.lower() if key_keyword else None
        body_kw = body_keyword.lower() if body_keyword else None
        for rec in configs:
            key = str(rec.get("key") or rec.get("revival_key") or "")
            body = str(rec.get("insight") or rec.get("rationale") or "")
            # Normalise `::` to `:` on BOTH sides so the single-colon parent
            # index matches the double-colon revival-key config keys.
            if parent is not None and self._norm(parent) not in self._norm(key):
                continue
            if key_kw is not None and key_kw not in key.lower():
                continue
            if body_kw is not None and body_kw not in body.lower():
                continue
            out.append({"memory_kind": "config", **rec})
        # Notes first (latest-first from read_notes), then configs. The two
        # bodies side by side; a caller wanting a strict global recency order
        # sorts on `_seq`/`_ref` itself.
        return [{"memory_kind": "note", **n} for n in notes] + out

    @staticmethod
    def _norm(key: str) -> str:
        """Normalise a key's parent delimiter for comparison: `::` -> `:`."""
        return key.lower().replace("::", ":")

    def config_keys(self, project_id: str) -> list[str]:
        """The keys/headers of every prior hunt-config direction stamp for the
        project, in newest-first order - the prompt-embedded index list (#141)."""
        out: list[str] = []
        for rec in self.read_configs(project_id):
            key = rec.get("key") or rec.get("revival_key")
            if key:
                out.append(str(key))
        return out

    # -- notes ---------------------------------------------------------------

    @staticmethod
    def notation_key(unit_id: str, fault_class: str, note_name: str) -> str:
        """The hierarchy key of a note: `unit_id:fault_class:<note_name>`.

        The note NAME encodes the kind as its initial namespace chained with the
        kind's concrete detail (e.g. a concrete missing adversarial capability, a
        defence, or the testing primitive) - #137 Q3."""
        return f"{unit_id}:{fault_class}:{note_name}"

    def append_note(
        self,
        project_id: str,
        unit_id: str,
        fault_class: str,
        note_name: str,
        kind: str,
        body: str,
        *,
        evidence: str | None = None,
        provenance: dict | None = None,
    ) -> str:
        """Monotonically append ONE note of a closed `kind` for the `(unit,
        fault)` pair, keyed `unit_id:fault_class:<note_name>` (#138, Q3/Q5).

        Fails open on the CALLER's side: a write failure raises (O3), the
        caller degrades to a warning and keeps serving. Returns the note `_ref`."""
        if kind not in self.NOTE_KINDS:
            raise ValueError(
                f"unknown note kind {kind!r}; known: {self.NOTE_KINDS}"
            )
        records = self._read_records(self._notes_file(project_id))
        seq = self._next_seq(records)
        stored = {
            "_seq": seq,
            "_ref": f"note-{seq:04d}",
            "key": self.notation_key(unit_id, fault_class, note_name),
            "unit_id": unit_id,
            "fault_class": fault_class,
            "kind": kind,
            "body": body,
            "evidence": evidence,
            "provenance": provenance or {},
        }
        records.append(stored)
        self._write_records(self._notes_file(project_id), records)
        return stored["_ref"]

    def read_notes(
        self,
        project_id: str,
        *,
        parent_key: str | None = None,
        key_keyword: str | None = None,
        body_keyword: str | None = None,
    ) -> list[dict]:
        """Grep-match read over the project's notes (#137 Q6, ticket #140): the
        matching logic lives strictly here, inside the store.

        Filters (combinable or singular):
          parent_key  - the exact parent index `unit_id:fault_class` (or a full
                        note key); yields that pair's notes.
          key_keyword - case-insensitive substring over the note KEYS.
          body_keyword- case-insensitive substring over the note BODY.
        Returns matching notes latest-first (read-latest). Zero matches is a
        valid empty result, never a failure."""
        records = self._read_records(self._notes_file(project_id))
        parent = parent_key.lower() if parent_key else None
        key_kw = key_keyword.lower() if key_keyword else None
        body_kw = body_keyword.lower() if body_keyword else None
        out = []
        for rec in records:
            if parent is not None:
                key = str(rec.get("key") or "")
                unit_id = str(rec.get("unit_id") or "")
                fault_class = str(rec.get("fault_class") or "")
                pair = f"{unit_id}:{fault_class}"
                # Match the parent index (normalising `::` to `:` on both sides)
                # or the full note key.
                if (self._norm(parent) not in self._norm(key)
                        and self._norm(parent) != self._norm(pair)):
                    continue
            if key_kw is not None and key_kw not in str(rec.get("key") or "").lower():
                continue
            if body_kw is not None and body_kw not in str(rec.get("body") or "").lower():
                continue
            out.append(rec)
        return list(reversed(out))
