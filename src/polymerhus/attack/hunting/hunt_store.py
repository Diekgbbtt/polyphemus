"""The residual project notes vocabulary and notes surface (#70, #137, #138).

T10 (#383) disposed of the hunt-config family and the per-project
`memory.yaml` notes store: the hunt store's config I/O retired in T6 (#379)
with the threat-payload rework, its key helpers (`semantic_key`,
`config_file_name`, ...) had no live consumer, and its bounded notes surface
(`HuntStore`) was read by no dispatch path. What remains is the phase-1 note
vocabulary (`ProjectMemoryStore.NOTE_KINDS`) that the hunter and threat-model
stores take as their base kind set, plus the small record I/O that keeps the
vocabulary's own store honest.

The live stores are `hunter_memory.HunterMemoryStore` (the threat-keyed spec and
note store) and `threat_model_store.ThreatModelStore` (the unit model, threat
files and phase notes); this module imports no driver and performs no I/O at
import (CODING_STANDARD section 6).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from polymerhus.app.atomic_write import write_text_atomic


class ProjectMemoryStore:
    """The phase-1 per-project notes store (#70, spec #137, ticket #138).

    A persistent, per-project store of notes: per analyzed `(unit, fault)` pair
    reasoning artifacts - refusal reasons with evidence, missing adversarial
    capability, environmental constraints, implicit testing primitives,
    forward-useful notes. A project folder is created lazily at the first
    write; it is never created eagerly.

    Layout: `<store_root>/projects/<project_id>/notes.yaml`. The file
    accumulates YAML records monotonically (append-only, each with a per-file
    monotonic `_seq` and a `_ref`), so re-analysis layers knowledge and history
    is preserved; a read returns latest-first (read-latest).

    The class is retained as the note-kind vocabulary's single source (S2
    10.1: a store keeps its own copy of the enum, guarded against drift); the
    dispatch path uses `HunterMemoryStore` / `ThreatModelStore`. Determinism +
    fail-open: writes raise on failure, reads raise on a corrupt file, never a
    silent corruption.
    """

    # The closed enum of note kinds (#137, Q3). `constraint` is merged into
    # `hypothesis_refusal`; these three are canonical.
    NOTE_KINDS = (
        "hypothesis_refusal",
        "implicit_test_primitive",
        "wellformedness",
        "freeform",
    )

    def __init__(self, root_dir: str | Path):
        self._root = Path(root_dir)

    # -- paths -------------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return self._root / "projects" / str(project_id)

    def _notes_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "notes.yaml"

    @classmethod
    def _read_records(cls, path: Path) -> list[dict]:
        """All records in `path`, in append order; empty for a missing file.

        A CORRUPT/unparseable file raises (O4) rather than returning [] - the
        write paths here rewrite the whole file on append, so returning [] on a
        corrupt read and then rewriting would silently destroy every earlier
        record."""
        if not path.exists():
            return []
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(f"project memory: unreadable notes file {path}: {exc}") from exc
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
        write_text_atomic(path, yaml.safe_dump(records, sort_keys=False))

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

    @staticmethod
    def _norm(key: str) -> str:
        """Normalise a key's parent delimiter for comparison: `::` -> `:`."""
        return key.lower().replace("::", ":")
