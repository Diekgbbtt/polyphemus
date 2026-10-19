"""The residual hunt-store vocabulary and the orchestrator notes surface.

The hunt-config dispatch family retired in T4b (#387) and its config I/O retired
in T6 (#379) with no live consumer left: the mover no longer reads produced
configs, the surfer no longer dispatches them, and the API path is a loud 410.
The module stays for the TWO things still imported elsewhere:

- the config-key helpers (`semantic_key`, `split_semantic_key`,
  `config_file_name`, `parse_config_file_name`) that the legacy identity tests
  and the eval translation still use;
- `ProjectMemoryStore.NOTE_KINDS`, the closed hunter note-kind vocabulary the
  hunter memory reuses verbatim.

`HuntStore`'s per-project `memory.yaml` notes surface remains as the
orchestrator's (now unused) notes store; the retired config topology
(`hunt_configs/produced`, `hunt_configs/consumed`) is not written by this
module any more. The produced config data still on disk is T10's disposition
(the eval translation owns the retired family).

Writes are atomic (a temp file in the same directory, then `os.replace` - a
crash mid-dump leaves the previous file content intact) and serialised per
project (a `threading.Lock` per `project_id` covers the whole check-then-write
and read-modify-write critical section, whatever thread calls - the async
caller offloads reads to worker threads while writes stay on the loop).

Fail-open canon unchanged: a read failure degrades to an empty set (O4) - a
missing file, an unreadable YAML, or a malformed record degrades per-record
with a warning, never a raise into the turn; a write failure raises to the
caller, which warns and counts `store_write_failures` (O3). Never a silent
corruption.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

import yaml

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import DATA_ROOT, project_dir
from polymerhus.app.memory.bounds import notes_body_len, retain_bounded_records
from polymerhus.app.memory.store import BoundedRecordStore

logger = logging.getLogger(__name__)

# The semantic-key separator (single-sourced, M1): the revival key
# (`<unit_id>::<fault_class>`) is the 2-part prefix of a semantic key, so
# both MUST use the same separator or the prefix matching drifts. `::` is
# safe - it appears in neither unit ids nor fault/class ids.
KEY_SEPARATOR = "::"

# The config file-name convention (G4): <unit_id>_<CWE_ID>_<vulnerability_class>.yaml.
# The CWE token (`CWE-\d+`) anchors the parse: the tri-part name is
# `<unit>_<CWE>_<class>.yaml` and the CWE token whose suffix is the class +
# `.yaml` is the fault-class separator. Splitting on the CWE anchor (instead
# of a greedy last-underscore match) preserves a unit that ITSELF ends in `_` -
# e.g. `AuthenticationMechanism:__singleton__` would otherwise lose its
# trailing underscore and never round-trip its identity (G4). The
# empty-class (carried-bare) degrade keeps the trailing `_` and is tolerated by
# the empty class suffix.
_CONFIG_FILE_RE = re.compile(r"_(CWE-\d+)_")

MEMORY_NOTES_MAX_RECORDS = 2000
MEMORY_NOTES_MAX_BYTES = 4 * 1024 * 1024


def config_file_name(unit_id: str, fault_class: str, vulnerability_class: str) -> str:
    """The config file name (G4): `_`-separated
    `<unit_id>_<CWE_ID>_<vulnerability_class>.yaml`. Unit ids contain `:` and
    `-`, so those are poisoned as separators; `_` is the one safe character."""
    return f"{unit_id}_{fault_class}_{vulnerability_class}.yaml"


def semantic_key(unit_id: str, fault_class: str, vulnerability_class: str) -> str:
    """The store's ONE canonical internal config identity (documented choice):
    `<unit_id>::<CWE_ID>::<vulnerability_class>` (`KEY_SEPARATOR`). Round-trips
    with the file name (`config_file_name` / `parse_config_file_name`); a
    revival key (`<unit_id>::<fault_class>`) is its 2-part prefix and reads
    every class at the locus."""
    return KEY_SEPARATOR.join((unit_id, fault_class, vulnerability_class))


# The semantic key's CWE anchor: the same discipline as the file name's
# (`_CONFIG_FILE_RE`). A unit id is a kind-qualified identity and MAY itself
# contain `::` (a System's `kind::discriminator`, e.g.
# `System:AuthorizationSystem::__singleton__`), so the split is anchored on
# the CWE token, never a naive 3-way split.
_SEMANTIC_KEY_RE = re.compile(r"::(CWE-\d+)::")
_CWE_TOKEN_RE = re.compile(r"CWE-\d+")


def split_semantic_key(key: str) -> tuple[str, str, str] | None:
    """Parse a `::` semantic key back to
    `(unit_id, fault_class, vulnerability_class)`. A CWE fault class is
    anchored on its token, so a unit id containing `::` (a System's
    `kind::discriminator`) round-trips with MORE than three segments; a
    non-CWE fault class keeps the plain 3-part split (the historical form).
    The empty-class (carried-bare) degrade is tolerated. None when the key is
    not the 3-part form (e.g. a 2-part revival key)."""
    match = _SEMANTIC_KEY_RE.search(key)
    if match is not None:
        unit_id = key[: match.start()]
        if not unit_id:
            return None
        return unit_id, match.group(1), key[match.end():]
    parts = key.split(KEY_SEPARATOR)
    if len(parts) == 3 and parts[0] and parts[1] and not _CWE_TOKEN_RE.fullmatch(parts[2]):
        return parts[0], parts[1], parts[2]
    return None


def parse_config_file_name(name: str) -> tuple[str, str, str] | None:
    """Parse a config file name back to
    `(unit_id, fault_class, vulnerability_class)`. The CWE token anchors the
    parse (G4): the fault class is the `CWE-\\d+` token whose suffix is the
    vulnerability class + `.yaml`, so a unit whose identity ends in `_` (e.g.
    `AuthenticationMechanism:__singleton__`) round-trips its full identity.
    None when the name does not follow the convention (e.g. a non-CWE
    fault_class - the store's content rebuild is the read-side fallback)."""
    if not name.endswith(".yaml"):
        return None
    parsed = None
    for match in _CONFIG_FILE_RE.finditer(name):
        unit, cwe, tail = name[: match.start()], match.group(1), name[match.end():]
        if tail.endswith(".yaml"):
            parsed = unit, cwe, tail[: -len(".yaml")]
    return parsed


def _keys_match(record_key: str, query_key: str) -> bool:
    """The key match rule: an exact semantic key, or a `KEY_SEPARATOR`-bounded
    prefix in either direction. A 2-part revival key (`unit::cwe`) reads every
    class at the locus; a 3-part semantic key reads exactly its config; a note
    keyed by the revival key is found by either."""
    return (record_key == query_key
            or record_key.startswith(query_key + KEY_SEPARATOR)
            or query_key.startswith(record_key + KEY_SEPARATOR))


class HuntStore(BoundedRecordStore):
    """The per-project `memory.yaml` notes store (memory-system spec).

    The config I/O surface retired in T6 (#379); only the notes primitives
    remain, and no live dispatch path reads them."""

    def __init__(self, root_dir: str | Path | None = None):
        """Rooted under `root_dir` (default: the app-owned `DATA_ROOT`); the
        per-project bucket is `<root>/<project_id>/hunting/orchestration/`,
        resolved through the ONE `data_root.project_dir` layout owner. The
        explicit-root constructor is kept for the tests' temp stores."""
        self._root = Path(root_dir) if root_dir is not None else DATA_ROOT

    # --- path helpers ----------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return project_dir(project_id, "hunting/orchestration", root=self._root)

    def _memory_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "memory.yaml"

    # --- notes surface (memory.yaml) ----------------------------------------------

    def _load_notes(self, project_id: str) -> list[dict]:
        """The notes list in natural append order; a missing file or an
        unreadable `memory.yaml` degrades to [] (warned, never a raise)."""
        path = self._memory_file(project_id)
        if not path.exists():
            return []
        try:
            body = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("hunt store: unreadable memory.yaml %s (%s)", path, exc)
            return []
        notes = body.get("notes") if isinstance(body, dict) else None
        if not isinstance(notes, list):
            return []
        return [n for n in notes if isinstance(n, dict)]

    def _save_notes(self, project_id: str, notes: list[dict]) -> None:
        """Rewrite `memory.yaml` (the whole-file notes write; a failure raises
        to the caller, which warns and counts - O3). Atomic: the previous file
        content survives a crash mid-dump (I1). Bounded (#341): the oldest
        notes are evicted so the file cannot grow without limit."""
        retained = retain_bounded_records(
            notes, max_records=MEMORY_NOTES_MAX_RECORDS,
            max_bytes=MEMORY_NOTES_MAX_BYTES, render=notes_body_len,
        )
        self._dump_yaml_atomic(self._memory_file(project_id), {"notes": retained})

    def read_notes(self, project_id: str, key: str | None = None) -> list[dict]:
        """The notes for a key (a 2-part revival key or a 3-part semantic key)
        in natural append order; `key=None` returns every note. Fail-open
        (O4)."""
        with self._lock_for(project_id):
            notes = self._load_notes(project_id)
            if key is None:
                return notes
            return [n for n in notes
                    if _keys_match(str(n.get("revival_key") or ""), key)]

    def append_note(self, project_id: str, key: str, note: str) -> dict:
        """Append one note for `key`; the record keeps the natural append
        order (no `_seq`, G11). Returns the stored record - its `note_id`
        identifies it for update/delete. The load-append-rewrite runs under
        the project's lock, so concurrent appends never lose a note (I2)."""
        with self._lock_for(project_id):
            record = {"note_id": uuid.uuid4().hex[:12], "revival_key": key, "note": note}
            notes = self._load_notes(project_id)
            notes.append(record)
            self._save_notes(project_id, notes)
            return record

    def update_note(self, project_id: str, note_id: str, note: str) -> bool:
        """Amend the note with `note_id`; False when no such note exists."""
        with self._lock_for(project_id):
            notes = self._load_notes(project_id)
            for record in notes:
                if record.get("note_id") == note_id:
                    record["note"] = note
                    self._save_notes(project_id, notes)
                    return True
            return False

    def delete_note(self, project_id: str, note_id: str) -> bool:
        """Remove the note with `note_id`; False when no such note exists."""
        with self._lock_for(project_id):
            notes = self._load_notes(project_id)
            kept = [n for n in notes if n.get("note_id") != note_id]
            if len(kept) == len(notes):
                return False
            self._save_notes(project_id, kept)
            return True


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
        write_text_atomic(path, yaml.safe_dump(records, sort_keys=False))

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
