"""The analysis episodic-memory store (the hunting-memory pattern, ADR D27-D32).

The analysis pipeline's durable per-Service memory, replicating the hunter's
`notes.yaml` data contract (`docs/design/hunting-memory-system-spec.md`, the
pattern document) over the SHARED `app.memory` primitives - never a copy of
hunting, and analysis never imports `attack.hunting`:

    data/<project_id>/analysis/memory.yaml

- ONE whole-file YAML list of note records, keyed by the Service slug
  (`<unit_slug>:<note_name>`, the analysis analogue of the hunter's
  `fault_key:<note_name>`). A project folder is created lazily at the first
  write; the app scaffold (`ensure_project`) owns the fixed `analysis/` bucket.
- The closed note-kind enum is L1-MODELLING only (`NOTE_KINDS`): the phase-3
  hunting vocabulary (fault hypothesis, payload, technique, vector) is
  unratified in this context, so no note kind may speak it (ADR D30).
- Write options append / update / delete; read is the grep-match read (by unit
  and by key / body keyword), latest-first. Notes keep their natural append
  order - no `_seq`/`_ref` bookkeeping.
- The file is BOUNDED by the shared `retain_bounded_records` (ADR D29): a long
  multi-Service run cannot grow one file without limit.

Read-back is both within-run (a later Service reads earlier Services' notes) and
cross-run, because the store is per-project and durable.

Degradation (unchanged canon): a read failure raises (the caller degrades to an
empty set and keeps serving), a write failure raises (the caller warns and keeps
serving), and a corrupt/unparseable file raises rather than silently returning
[] - the rewrite-on-write paths would otherwise destroy history. Every write is
atomic through the shared `app.atomic_write` primitive, so an aborted write
leaves the previous `memory.yaml` intact.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from polymerhus.app.data_root import DATA_ROOT, project_dir
from polymerhus.app.memory.store import BoundedRecordStore
from polymerhus.app.memory.tool_contract import (
    NotesFieldMap,
    build_notes_tool,
)

# The write/note operation enum (the pattern's G6).
_NOTE_ACTIONS = ("append", "update", "delete")

# The closed enum of analysis note kinds (ADR D30): L1-modelling only. The
# phase-3 hunting vocabulary stays unratified, so these names deliberately do
# not speak it.
NOTE_KINDS: tuple[str, ...] = (
    "assignment",
    "system",
    "data",
    "refusal",
    "open_question",
)

# The analysis write-time bound (ADR D29): the pattern's #341 bound, with the
# analysis module's own ceilings. A multi-Service run appends one or more notes
# per Service, so the bound keeps the whole-file rewrite O(bound), not O(run).
MEMORY_NOTES_MAX_RECORDS = 2000
MEMORY_NOTES_MAX_BYTES = 4 * 1024 * 1024


class AnalysisMemoryStore(BoundedRecordStore):
    """The analysis per-project episodic-memory store, keyed by Service slug.

    Per-project, durable notes written by the proposers during their turns (the
    `notes` tool) and by the per-unit backstop. A project folder is created
    lazily at the first write; the app scaffold owns the fixed `analysis/`
    bucket. Writes raise on failure (the caller warns and keeps serving - O3);
    reads raise on failure (the caller degrades to an empty set - O4). A corrupt
    file raises rather than returning [] - never a silent corruption.
    """

    def __init__(self, root_dir: str | Path | None = None):
        """Rooted under `root_dir` (default: the app-owned `DATA_ROOT`); the
        per-project `analysis/` bucket is resolved through the ONE
        `data_root.project_dir` layout owner. The explicit-root constructor is
        kept for the tests' temp stores."""
        self._root = Path(root_dir) if root_dir is not None else DATA_ROOT

    # -- paths -------------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return project_dir(project_id, "analysis", root=self._root)

    def _notes_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "memory.yaml"

    # -- record mechanics --------------------------------------------------

    @staticmethod
    def _validate_unit(unit: str) -> None:
        """Reject an empty or control-bearing Service slug: it is used verbatim
        as the note key's parent, so a control char or an empty value is a
        caller defect (the note would be unaddressable)."""
        if not isinstance(unit, str) or not unit:
            raise ValueError("analysis memory: unit must be a non-empty string")
        if any(ord(ch) < 32 for ch in unit):
            raise ValueError(
                f"analysis memory: unit {unit!r} contains a control character"
            )

    @classmethod
    def _read_records(cls, path: Path) -> list[dict]:
        """All records in `path`, in natural append order; empty for a missing
        file.

        A corrupt/unparseable file raises (O4) rather than returning [] - the
        write paths here rewrite the whole file, so returning [] on a corrupt
        read and then rewriting would silently destroy every earlier record."""
        if not path.exists():
            return []
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(f"analysis memory: unreadable memory file {path}: {exc}") from exc
        if isinstance(loaded, list):
            return [r for r in loaded if isinstance(r, dict)]
        if isinstance(loaded, dict):
            return [r for r in loaded.values() if isinstance(r, dict)]
        return []

    def _write_records(self, path: Path, records: list[dict]) -> None:
        """Rewrite the whole-file notes list, bounded by the shared
        `retain_bounded_records` and written atomically."""
        self._dump_yaml_atomic(
            path,
            self._bounded(
                records,
                max_records=MEMORY_NOTES_MAX_RECORDS,
                max_bytes=MEMORY_NOTES_MAX_BYTES,
            ),
        )

    @staticmethod
    def _project(record: dict, attributes: Sequence[str] | None) -> dict:
        """Project `record` onto `attributes`; the full record when none given."""
        if attributes is None:
            return record
        return {k: record[k] for k in attributes if k in record}

    @staticmethod
    def _norm(key: str) -> str:
        """Normalise a key's parent delimiter for comparison: `::` -> `:`."""
        return key.lower().replace("::", ":")

    # -- the notes surface -------------------------------------------------

    @staticmethod
    def note_key(unit: str, note_name: str) -> str:
        """The hierarchy key of a note: `<unit>:<note_name>` (the analysis
        analogue of the hunter's `fault_key:<note_name>`)."""
        return f"{unit}:{note_name}"

    def write_note(
        self,
        project_id: str,
        *,
        action: Literal["append", "update", "delete"] = "append",
        unit: str,
        note_name: str,
        kind: str,
        body: str,
        evidence: str | None = None,
        provenance: dict | None = None,
    ) -> str | None:
        """The `notes` body write over the per-project `memory.yaml`.

        `append` adds a new note for the `(unit, note_name)` key; `update`
        amends an existing note (replacing its kind/body/evidence/provenance);
        `delete` removes it. Returns the note `key` (`<unit>:<note_name>`); an
        update/delete on a missing key returns `None` (a denoted miss, never a
        failure). Notes keep their natural append order. Raises on write failure
        (O3) and on an unknown `kind` or `action`."""
        if action not in _NOTE_ACTIONS:
            raise ValueError(
                f"analysis memory: unknown note action {action!r}; known: {_NOTE_ACTIONS}"
            )
        if kind not in NOTE_KINDS:
            raise ValueError(
                f"analysis memory: unknown note kind {kind!r}; known: {NOTE_KINDS}"
            )
        self._validate_unit(unit)
        path = self._notes_file(project_id)
        key = self.note_key(unit, note_name)
        # The read-modify-write critical section runs under the shared per-project
        # lock (the `BoundedRecordStore` intent, I2), so concurrent appends never
        # lose a record and the tool write cannot race the backstop.
        with self._lock_for(project_id):
            records = self._read_records(path)
            if action == "append":
                records.append({
                    "key": key,
                    "unit": unit,
                    "note_name": note_name,
                    "kind": kind,
                    "body": body,
                    "evidence": evidence,
                    "provenance": provenance or {},
                })
                self._write_records(path, records)
                return key
            for rec in records:
                if rec.get("key") != key:
                    continue
                if action == "update":
                    rec.update({
                        "kind": kind,
                        "body": body,
                        "evidence": evidence,
                        "provenance": provenance or {},
                    })
                else:  # delete
                    records.remove(rec)
                self._write_records(path, records)
                return key
            return None

    def read_notes(
        self,
        project_id: str,
        *,
        parent_key: str | None = None,
        key_keyword: str | None = None,
        body_keyword: str | None = None,
        attributes: Sequence[str] | None = None,
    ) -> list[dict]:
        """Grep-match read over the project's notes, read-latest.

        Filters (combinable or singular):
          parent_key  - the Service slug (or a full note key); yields that
                        Service's notes.
          key_keyword - case-insensitive substring over the note KEYS.
          body_keyword- case-insensitive substring over the note BODY.
        Returns matching notes latest-first. Zero matches is a valid empty
        result, never a failure. A corrupt file raises (O4)."""
        with self._lock_for(project_id):
            records = self._read_records(self._notes_file(project_id))
            parent = self._norm(parent_key) if parent_key else None
            key_kw = key_keyword.lower() if key_keyword else None
            body_kw = body_keyword.lower() if body_keyword else None
            out: list[dict] = []
            for rec in records:
                key = str(rec.get("key") or "")
                if parent is not None:
                    unit = str(rec.get("unit") or "")
                    if parent != self._norm(unit) and parent not in self._norm(key):
                        continue
                if key_kw is not None and key_kw not in key.lower():
                    continue
                if body_kw is not None and body_kw not in str(rec.get("body") or "").lower():
                    continue
                out.append(self._project(rec, attributes))
            return list(reversed(out))

    def has_note(self, project_id: str, unit: str) -> bool:
        """Whether the project holds at least one note for `unit` (the exact
        Service slug). The per-unit backstop's coverage predicate."""
        with self._lock_for(project_id):
            return any(
                str(rec.get("unit") or "") == unit
                for rec in self._read_records(self._notes_file(project_id))
            )


def ensure_unit_note(
    store: AnalysisMemoryStore | None,
    project_id: str | None,
    unit: str | None,
    *,
    run_id: str | None = None,
    source: str = "backstop",
) -> dict | None:
    """The per-unit coverage backstop (ADR D31): write ONE note for `unit` when
    the proposer wrote none during its turns.

    The guarantee is "one note per Service exists after the run" - an auditable
    coverage property, not merely a prompt instruction. The backstop is inert
    when no store, project, or unit is bound (the contract tier). It is
    fail-open: a write failure is logged and returns None, never raised into the
    run. Returns the recorded note or None (a note already existed, or the
    backstop was inert/failed)."""
    if store is None or not project_id or not unit:
        return None
    try:
        if store.has_note(project_id, unit):
            return None
        store.write_note(
            project_id,
            unit=unit,
            note_name=source,
            kind="open_question",
            body=(f"no note was recorded for {unit} during the run; the backstop "
                  f"records the Service so its coverage is auditable"),
            provenance={"source": source, "run_id": run_id or ""},
        )
    except Exception:  # noqa: BLE001 - the backstop is fail-open, never into the run
        import logging

        logging.getLogger(__name__).warning(
            "analysis memory: backstop note for %s failed; continuing", unit,
            exc_info=True,
        )
        return None
    return {"unit": unit, "note_name": source, "kind": "open_question"}


# --- the notes tool (the shared StoreNotesTool, bound to this store) ----------


class AnalysisNotesArgs(BaseModel):
    """The analysis `notes` tool's ARGS contract: `read` / `write` cmds.

    The destination is the caller-bound analysis store; `unit` is the Service
    slug the note is keyed by (the write target, or the read filter). The note
    `kind` is the closed L1-modelling enum. `evidence` is prose; structured refs
    belong in the record's provenance (written by the code, never authored
    here)."""

    command: Literal["read", "write"] = Field(
        description="The operation: 'read' or 'write' (required); `action` is "
                    "the write option, never the command.")
    # -- read path -----------------------------------------------------------
    unit: str = Field(
        default="",
        description="The Service slug: the write target, or the read filter "
                    "(omit to read every Service's notes).")
    key_keyword: str = Field(
        default="", description="Read filter: substring over the note keys.")
    body_keyword: str = Field(
        default="", description="Read filter: substring over the note bodies.")
    attributes: list[str] = Field(
        default_factory=list,
        description="Read projection: return only these attributes per note.")
    # -- write path ----------------------------------------------------------
    action: Literal["append", "update", "delete"] = Field(
        default="append",
        description="The write option: 'append' a new note, 'update' or "
                    "'delete' an existing one.")
    note_name: str = Field(
        default="",
        description="The note's name, unique within the Service (required on a "
                    "write; ignored on a read).")
    kind: Literal["assignment", "system", "data", "refusal", "open_question"] = Field(
        default="open_question",
        description="The L1-modelling note kind (required on a write).")
    body: str = Field(default="", description="The note body.")
    evidence: str | None = Field(
        default=None,
        description="Prose evidence for the note; structured refs are stored "
                    "in the record's provenance by the code, not authored here.")

    model_config = ConfigDict(extra="forbid")


# The explicit notes field map (the shared #293 discipline): the analysis
# schema names, checked against `AnalysisNotesArgs` at construction - no alias
# guessing. The Service slug is the key on BOTH the read and the write path.
_ANALYSIS_NOTES_FIELD_MAP = NotesFieldMap(
    key="unit",
    read_key="unit",
    action="action",
    note="body",
    note_id=None,
    attributes="attributes",
    key_keyword="key_keyword",
    body_keyword="body_keyword",
    passthrough=("note_name", "kind", "evidence"),
)

_ANALYSIS_NOTES_DESCRIPTION = (
    "Read or write the project's analysis episodic memory (`memory.yaml`), one "
    "note per Service covering the modelling decisions. Commands: read / write.\n"
    "A write MUST set command=\"write\" (action is the write option - append | "
    "update | delete - not the command); a read sets command=\"read\".\n"
    "write takes an action, the Service `unit` slug, a `note_name`, the note "
    "kind (assignment | system | data | refusal | open_question), and the body. "
    "read is the grep-match read, latest-first, by the Service `unit`, or the "
    "key / body keyword; omit `unit` to read every Service's notes (a later "
    "Service reads earlier Services' findings)."
)


class AnalysisNotesHandle:
    """The analysis seam's store handle for the shared `notes` tool.

    It owns the `analysis/memory.yaml` destination (via `AnalysisMemoryStore`);
    the Service slug is a REQUEST field (read-back crosses Services), so the
    model may read any Service's notes but the filesystem destination is always
    the handle's store, never a request field."""

    def __init__(self, store: AnalysisMemoryStore | None, project_id: str):
        self._store = store
        self._project_id = project_id

    def read(self, query) -> dict:
        if self._store is None:
            return {"notes": [], "error": "store_unavailable", "degraded": True}
        try:
            notes = self._store.read_notes(
                self._project_id,
                parent_key=query.key or None,
                key_keyword=query.key_keyword or None,
                body_keyword=query.body_keyword or None,
                attributes=query.attributes or None,
            )
        except Exception as exc:  # noqa: BLE001 - O4: read failure -> empty set
            return {"notes": [], "error": "read_failed", "detail": str(exc)}
        return {"notes": notes}

    def write(self, request) -> dict:
        if self._store is None:
            return {"command": request.command, "error": "store_unavailable",
                    "degraded": True}
        if not request.key or not request.note_name:
            return {"ok": False, "error": "invalid_args",
                    "detail": "write needs a Service unit and a note_name"}
        try:
            key = self._store.write_note(
                self._project_id, action=request.action, unit=request.key,
                note_name=request.note_name, kind=request.kind, body=request.body,
                evidence=request.evidence, provenance=request.provenance,
            )
        except ValueError as exc:
            return {"ok": False, "error": "invalid_args", "detail": str(exc)}
        # O3: any other write failure raises to the harness, which warns and
        # keeps serving.
        if key is None:
            return {"ok": False, "error": "note_missing",
                    "unit": request.key, "note_name": request.note_name}
        return {"ok": True, "key": key}


def notes_tool_for(
    *, store: AnalysisMemoryStore | None = None, project_id: str = "",
) -> Any:
    """The production builder for the analysis `notes` tool: the shared
    `build_notes_tool` over the analysis store handle. The `memory.yaml`
    destination is derived from the handle, never a request field."""
    return build_notes_tool(
        AnalysisNotesHandle(store, project_id),
        args_schema=AnalysisNotesArgs,
        field_map=_ANALYSIS_NOTES_FIELD_MAP,
        name="notes",
        description=_ANALYSIS_NOTES_DESCRIPTION,
        discriminator="command",
        as_json=True,
        rejection_name="notes",
        write_intent_fields=("action", "note_name", "kind", "body"),
        require_write_intent=False,
    )


__all__ = [
    "AnalysisMemoryStore",
    "AnalysisNotesArgs",
    "AnalysisNotesHandle",
    "MEMORY_NOTES_MAX_BYTES",
    "MEMORY_NOTES_MAX_RECORDS",
    "NOTE_KINDS",
    "ensure_unit_note",
    "notes_tool_for",
]
