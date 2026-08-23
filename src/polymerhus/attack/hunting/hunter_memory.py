"""The hunter-owned per-project memory store (#164, W3).

The hunter's durable memory, replicating the hunt-config memory store pattern
(`docs/design/hunting-memory-system-spec.md`, the pattern document) and
adapted to the hunter domain by the ratified dispositions G1-G9
(`docs/design/hunting-164-state-graph-adr.md` GP6, `hunting-164-state-graph-spec.md`
section 6). The store is per-project (a folder keyed by `project_id`, created
lazily at the first write), one YAML file per spec, produced/consumed
directories, the file carrying the status lifecycle, and a duplicate-write
novelty gate.

Topology under the FIXED module root `HUNTER_MEMORY_ROOT`
(`src/polymerhus/attack/hunting/data/hunting/`, sibling to the hunt store's
`data/hunts/` - no env var; the explicit-root constructor is kept for tests):

    <project_id>/test-specs/<fault_key>/produced/<fault>_<strategy>.yaml
    <project_id>/test-specs/<fault_key>/consumed/<fault>_<strategy>.yaml
    <project_id>/notes.yaml

- `<fault_key>` is the config key itself (the `(unit_id, fault_class)`
  identity, used verbatim as the folder name); the `<fault>_<strategy>.yaml`
  file name encodes the concrete fault semantic + testing strategy keywords
  joined by `_`, the one safe separator (the pattern's ruling: `-`/`:` are
  poisoned as separators). Keywords are sanitised (`_`/`:`/path separators
  and control chars replaced with `-`).
- The produced/ spec file carries the `status` attribute
  (`hypothesised | verified | dropped | specified` from
  `hunter_state.FaultStatus`): the `hypothesised` write creates the fault
  draft, `verified`/`dropped` update it, `specified` completes it into the
  full spec - "the persisted environment state IS the fault-processing
  tracker" (G4/G10).
- A duplicate `create` write (a `<fault>_<strategy>.yaml` that already
  exists) FAILS with a `DuplicateSpecError` - the enforced novelty gate, a
  very rare path (G4). Re-authoring UPDATES the existing file in place
  (`mode="update"`, the G5 re-authoring pass). Every write is a file
  create/overwrite, never an append-record (GP2-c). The caller selects the
  mode from the lifecycle (a `hypothesised` write creates, `verified` /
  `dropped` / `specified` update).
- The produced->consumed movement is the inbox surfer loop's ownership, OUT
  OF SCOPE (G7); this store fixes the topology the surfer operates on. Both
  sides are addressable (`side` on write, `sides` on read); nothing here
  moves a file between them.
- The notes file follows the SAME data contract as the spec body (G6):
  read/write, write options append/update/delete, grep-match read,
  read-latest. Notes keep their natural append order - no `_seq`/`_ref`
  bookkeeping (the pattern's G11: the file name is the key, the notes file's
  list order is the ordering).

Degradation (unchanged canon, spec 9): a read failure raises (O4, the
caller degrades to an empty set and keeps serving), a write failure raises
(O3, the caller warns and keeps serving), and a corrupt/unparseable file
raises rather than silently returning [] - the rewrite-on-write paths would
otherwise destroy history. Never a silent corruption.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import yaml

from .hunt_store import ProjectMemoryStore
from .hunter_state import FAULT_STATUSES

# The FIXED store root (seam convention, #110): the hunter memory store lives
# at `src/polymerhus/attack/hunting/data/hunting/`, a sibling of the hunt
# store's `data/hunts/` - no env var. The explicit-root constructor is kept
# for the tests/the module tests' temp stores.
HUNTER_MEMORY_ROOT = Path(__file__).resolve().parent / "data" / "hunting"

# The produced/consumed sides and the write/note operation enums (G7, G6).
_SPEC_SIDES = ("produced", "consumed")
_SPEC_MODES = ("create", "update")
_NOTE_ACTIONS = ("append", "update", "delete")

# The closed enum of note kinds (the pattern's #137 Q3), reused verbatim on
# the hunter's notes so the data contract is the SAME as the pattern's store.
NOTE_KINDS = ProjectMemoryStore.NOTE_KINDS

# The filename-keyword sanitisation banned set (G3): `_` is the separator, so
# a keyword may not contain it; `:` is poisoned (it appears inside unit ids);
# `/`/`\` are path separators. Each banned char (plus control/NUL chars) is
# replaced with `-`, a safe, non-separator keyword char the pattern's own
# names use freely (`-` itself is never banned - it is the replacement char).
_UNSAFE_KEYWORD_CHARS = frozenset("_:/\\")


class DuplicateSpecError(Exception):
    """The denoted deduplication signal (G4).

    A `create`-mode write of a `<fault>_<strategy>.yaml` that already exists
    raises this - the enforced novelty gate, a very rare path the model
    interprets (it reflects on overlap and merges or refreshes instead of
    duplicating).
    """


class HunterMemoryStore:
    """The hunter-owned per-project memory store (#164, GP6).

    Per-project, per-`fault_key` durable memory of the state-graph hunter:
    one YAML file per authored spec (the produced/ file carries the status
    lifecycle), produced/consumed directories, and a per-project notes file
    on the same data contract. A project folder is created lazily at the
    first write; it is never created eagerly.

    Determinism + fail-open: writes raise on failure (the caller degrades to
    a warning and keeps serving - O3), reads raise on failure (the harness
    degrades to an empty set and keeps serving - O4). A corrupt file raises
    rather than returning [] - the rewrite-on-write paths would otherwise
    destroy history. Never a silent corruption.
    """

    def __init__(self, root_dir: str | Path | None = None):
        """The hunter memory store rooted under `root_dir` (default: the FIXED
        seam root `src/polymerhus/attack/hunting/data/hunting/`)."""
        self._root = Path(root_dir) if root_dir is not None else HUNTER_MEMORY_ROOT

    # -- paths -------------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        self._validate_component(project_id, "project_id")
        return self._root / str(project_id)

    def _spec_dir(self, project_id: str, fault_key: str) -> Path:
        self._validate_component(fault_key, "fault_key")
        return self._project_dir(project_id) / "test-specs" / fault_key

    def _spec_file(
        self,
        project_id: str,
        fault_key: str,
        fault_keyword: str,
        strategy_keyword: str,
        side: str,
    ) -> Path:
        self._validate_side(side)
        return (
            self._spec_dir(project_id, fault_key)
            / side
            / f"{self._sanitise_keyword(fault_keyword)}_{self._sanitise_keyword(strategy_keyword)}.yaml"
        )

    def _notes_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "notes.yaml"

    # -- validation + sanitisation (G3) --------------------------------------

    @staticmethod
    def _validate_component(value: str, what: str) -> None:
        """Reject a `project_id`/`fault_key` that is not one safe path component.

        The config key is used verbatim as the folder name, so `:` and `-`
        are legal (they are the config key's identity chars); only path
        separators, control chars, and dot-traversal forms are rejected."""
        if not isinstance(value, str) or not value:
            raise ValueError(f"hunter store: {what} must be a non-empty string")
        if value in (".", ".."):
            raise ValueError(
                f"hunter store: {what} {value!r} is not a valid path component"
            )
        if any(ch in value for ch in "/\\\x00") or any(ord(ch) < 32 for ch in value):
            raise ValueError(
                f"hunter store: {what} {value!r} contains a path separator or control character"
            )

    @classmethod
    def _sanitise_keyword(cls, keyword: str) -> str:
        """Sanitise a `<fault>`/`<strategy>` filename keyword (G3).

        Each char in the banned set (`_` the separator, `:` poisoned, path
        separators) and every control char is replaced with `-` (a safe,
        non-separator keyword char; `-` itself is never banned). A
        keyword that sanitises to an empty/dot component is a pathological
        authoring input and is rejected, never silently mangled."""
        out = "".join(
            "-" if ch in _UNSAFE_KEYWORD_CHARS or ord(ch) < 32 else ch
            for ch in keyword
        )
        if not out or out in (".", ".."):
            raise ValueError(
                f"hunter store: keyword {keyword!r} sanitises to the unsafe "
                f"file component {out!r}"
            )
        return out

    @staticmethod
    def _validate_side(side: str) -> None:
        if side not in _SPEC_SIDES:
            raise ValueError(f"hunter store: unknown spec side {side!r}; known: {_SPEC_SIDES}")

    # -- record mechanics (mirrored from the pattern) -------------------------

    @classmethod
    def _read_records(cls, path: Path) -> list[dict]:
        """All records in `path`, in natural list order; empty for a missing file.

        A CORRUPT/unparseable file raises (O4) rather than returning [] - the
        write paths here rewrite the whole file, so returning [] on a corrupt
        read and then rewriting would silently destroy every earlier record.
        Failing loudly (the caller degrades to a warning and keeps serving)
        preserves the memory guarantee."""
        if not path.exists():
            return []
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(f"hunter memory: unreadable memory file {path}: {exc}") from exc
        if isinstance(loaded, list):
            return [r for r in loaded if isinstance(r, dict)]
        if isinstance(loaded, dict):
            return [r for r in loaded.values() if isinstance(r, dict)]
        return []

    @classmethod
    def _write_records(cls, path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(records, fh, sort_keys=False)

    def _read_spec_file(self, path: Path) -> dict:
        """Read ONE produced/consumed spec file; a corrupt or non-mapping body raises."""
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(f"hunter store: unreadable spec file {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise OSError(f"hunter store: spec file {path} is not a YAML mapping")
        return loaded

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

    # -- the spec surface (the `hunts_store`-analogue, G8) -------------------

    def write_spec(
        self,
        project_id: str,
        fault_key: str,
        *,
        fault_keyword: str,
        strategy_keyword: str,
        spec: dict,
        mode: Literal["create", "update"] = "create",
        side: Literal["produced", "consumed"] = "produced",
    ) -> Path:
        """Write the fault/spec object to `test-specs/<fault_key>/<side>/<fault>_<strategy>.yaml`.

        `spec` is the fault/spec object carrying the `status` attribute
        (`hypothesised | verified | dropped | specified` from
        `hunter_state.FaultStatus`); it is persisted verbatim. The
        `fault_keyword` / `strategy_keyword` are the file-name components
        (the concrete fault semantic + testing strategy keywords, sanitised
        under G3) - explicit because the hypothesised/verified/dropped drafts
        are `FaultItem`s that carry no strategy field, so the file name must
        be fixed at the first (creating) write and stable across the
        lifecycle.

        `mode="create"` FAILS with a `DuplicateSpecError` when the file
        already exists (the novelty gate, G4); `mode="update"` overwrites the
        existing file in place (the G5 re-authoring pass). Returns the
        written `Path`. Raises on write failure - the caller degrades to a
        warning and keeps serving (O3)."""
        if mode not in _SPEC_MODES:
            raise ValueError(f"hunter store: unknown spec write mode {mode!r}; known: {_SPEC_MODES}")
        if not isinstance(spec, dict):
            raise ValueError("hunter store: spec must be a dict carrying the status attribute")
        status = spec.get("status")
        if status not in FAULT_STATUSES:
            raise ValueError(
                f"hunter store: spec must carry a status in FAULT_STATUSES; got {status!r}"
            )
        path = self._spec_file(
            project_id, fault_key, fault_keyword, strategy_keyword, side,
        )
        if mode == "create" and path.exists():
            raise DuplicateSpecError(f"hunter store: spec file already exists (novelty gate): {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(spec, fh, sort_keys=False)
        return path

    def read_spec(
        self,
        project_id: str,
        fault_key: str,
        fault_keyword: str,
        strategy_keyword: str,
        *,
        side: Literal["produced", "consumed"] = "produced",
        attributes: Sequence[str] | None = None,
    ) -> dict | None:
        """The one spec file for `(fault_key, fault_keyword, strategy_keyword)`.

        `None` for a missing file (a valid empty result, never a failure); a
        corrupt file raises (O4, the caller degrades to an empty set). With
        `attributes` given, each returned dict is projected onto them."""
        path = self._spec_file(
            project_id, fault_key, fault_keyword, strategy_keyword, side,
        )
        if not path.exists():
            return None
        return self._project(self._read_spec_file(path), attributes)

    def read_specs(
        self,
        project_id: str,
        fault_key: str,
        *,
        sides: Sequence[Literal["produced", "consumed"]] = ("produced", "consumed"),
        statuses: Sequence[str] | None = None,
        attributes: Sequence[str] | None = None,
    ) -> list[dict]:
        """All spec files under `test-specs/<fault_key>/`, in file-name order.

        Read by the config identifier (the `fault_key`); the whole surface
        context is never returned through this store (G3). `sides` selects
        produced/consumed (default both); `statuses` filters on the persisted
        `status`; `attributes` projects each spec onto the given fields. A
        missing project/fault_key yields [] - a valid empty result, never a
        failure. A corrupt file raises (O4)."""
        out: list[dict] = []
        for side in sides:
            self._validate_side(side)
            side_dir = self._spec_dir(project_id, fault_key) / side
            if not side_dir.exists():
                continue
            for path in sorted(side_dir.glob("*.yaml")):
                spec = self._read_spec_file(path)
                if statuses is not None and spec.get("status") not in statuses:
                    continue
                out.append(self._project(spec, attributes))
        return out

    # -- the notes surface (G6) -----------------------------------------------

    @staticmethod
    def note_key(fault_key: str, note_name: str) -> str:
        """The hierarchy key of a note: `fault_key:<note_name>` (G6)."""
        return f"{fault_key}:{note_name}"

    def write_note(
        self,
        project_id: str,
        *,
        action: Literal["append", "update", "delete"] = "append",
        fault_key: str,
        note_name: str,
        kind: str,
        body: str,
        evidence: str | None = None,
        provenance: dict | None = None,
    ) -> str | None:
        """The `notes` body write over the per-project `notes.yaml` (G6).

        `append` adds a new note for the `(fault_key, note_name)` key;
        `update` amends an existing note (replacing its kind/body/evidence/
        provenance); `delete` removes it. Returns the note `key`
        (`fault_key:<note_name>`); an update/delete on a missing key returns
        `None` (a denoted miss, never a failure). Notes keep their natural
        append order - no `_seq`/`_ref` (G11). Raises on write failure (O3)
        and on an unknown `kind` or `action`."""
        if action not in _NOTE_ACTIONS:
            raise ValueError(f"hunter store: unknown note action {action!r}; known: {_NOTE_ACTIONS}")
        if kind not in NOTE_KINDS:
            raise ValueError(
                f"hunter store: unknown note kind {kind!r}; known: {NOTE_KINDS}"
            )
        path = self._notes_file(project_id)
        records = self._read_records(path)
        key = self.note_key(fault_key, note_name)
        if action == "append":
            records.append(
                {
                    "key": key,
                    "fault_key": fault_key,
                    "note_name": note_name,
                    "kind": kind,
                    "body": body,
                    "evidence": evidence,
                    "provenance": provenance or {},
                }
            )
            self._write_records(path, records)
            return key
        for rec in records:
            if rec.get("key") != key:
                continue
            if action == "update":
                rec.update(
                    {
                        "kind": kind,
                        "body": body,
                        "evidence": evidence,
                        "provenance": provenance or {},
                    }
                )
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
        """Grep-match read over the project's notes (G6), read-latest.

        Filters (combinable or singular):
          parent_key  - the fault_key (the config identifier); yields that
                        fault's notes (the note keys embed it).
          key_keyword - case-insensitive substring over the note KEYS.
          body_keyword- case-insensitive substring over the note BODY.
        Returns matching notes latest-first (read-latest - the natural list
        order of the notes file, reversed). Zero matches is a valid empty
        result, never a failure. A corrupt file raises (O4)."""
        records = self._read_records(self._notes_file(project_id))
        parent = parent_key.lower() if parent_key else None
        key_kw = key_keyword.lower() if key_keyword else None
        body_kw = body_keyword.lower() if body_keyword else None
        out: list[dict] = []
        for rec in records:
            key = str(rec.get("key") or "")
            if parent is not None and self._norm(parent) not in self._norm(key):
                continue
            if key_kw is not None and key_kw not in key.lower():
                continue
            if body_kw is not None and body_kw not in str(rec.get("body") or "").lower():
                continue
            out.append(self._project(rec, attributes))
        return list(reversed(out))


__all__ = [
    "HUNTER_MEMORY_ROOT",
    "DuplicateSpecError",
    "HunterMemoryStore",
    "NOTE_KINDS",
]