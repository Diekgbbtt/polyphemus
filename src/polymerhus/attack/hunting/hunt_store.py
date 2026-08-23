"""The per-project hunt-config + notes memory store (memory-system spec, #166).

Topology (spec section 3), one folder per project, lazily created at the
first write:

    data/<project_id>/orchestration/
      hunt_configs/
        produced/<unit_id>_<CWE_ID>_<vulnerability_class>.yaml
        consumed/<unit_id>_<CWE_ID>_<vulnerability_class>.yaml
      memory.yaml                                  (notes; append/update/delete)

One YAML file per hunt config; the file name IS the config's identity (G4):
`_` is the separator (unit ids contain `:` and `-`, so those are poisoned as
separators), and the last-two-underscores convention - `<unit>_<CWE-ID>_<class>`
with the CWE id (`CWE-\\d+`) disambiguating the middle segment - is the robust
parse. The store's ONE canonical internal representation is the semantic key
`<unit_id>::<CWE_ID>::<vulnerability_class>` (`semantic_key`), which
round-trips with the file name via `config_file_name` / `parse_config_file_name`.

A duplicate-id write - a file name that already exists in produced/ OR
consumed/ - FAILS with `DuplicateConfigError`: the enforced novelty gate at
the storage layer (G4), a deduplication signal the model interprets (it
reflects on overlap and merges or refreshes instead of duplicating). `dropped`
configs stay on disk statused `dropped`, never deleted (G6). `memory.yaml`
keeps its natural append order (no `_seq`, G11); the notes surface exposes
read / append / update / delete primitives (spec 6.2; the notes TOOL contract
is another workstream's - #167 - this is the store it binds to).

Writes are atomic (a temp file in the same directory, then `os.replace` - a
crash mid-dump leaves the previous file content intact) and serialised per
project (a `threading.Lock` per `project_id` covers the whole check-then-write
and read-modify-write critical section, whatever thread calls - the async
caller offloads reads to worker threads while writes stay on the loop).

Fail-open canon unchanged: a read failure degrades to an empty set (O4) - a
missing file, an unreadable YAML, or a malformed record degrades per-record
with a warning, never a raise into the turn; a write failure raises to the
caller, which warns and counts `store_write_failures` (O3). Never a silent
corruption. Configs serialise via `model_dump` -> YAML; reads return plain
dicts (round-trip fidelity over strict model parsing, so legacy or foreign
yaml stays readable).

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# The FIXED store root (seam contract 3.4, #110): the per-project memory store
# lives under `src/polymerhus/attack/hunting/data/` - no env var. The
# explicit-root constructor is kept for the tests/the module tests' temp
# stores.
HUNT_STORE_ROOT = Path(__file__).resolve().parent / "data"

# The semantic-key separator (single-sourced, M1): the revival key
# (`<unit_id>::<fault_class>`, hunt_orchestrator.revival_key) is the 2-part
# prefix of a semantic key, so both MUST use the same separator or the
# prefix matching drifts. `::` is safe - it appears in neither unit ids nor
# fault/class ids.
KEY_SEPARATOR = "::"

# The config file-name convention (G4): <unit_id>_<CWE_ID>_<vulnerability_class>.yaml.
# The regex parses on the LAST two underscores: `CWE-\d+` disambiguates the
# middle segment, so a unit_id (or vulnerability class) containing `_`
# round-trips; the empty-class (carried-bare) degrade keeps the trailing
# underscore and is tolerated by `(?P<cls>.*)`.
_CONFIG_FILE_RE = re.compile(
    r"^(?P<unit>.+)_(?P<cwe>CWE-\d+)_(?P<cls>.*)\.yaml$"
)

# The writeable config directories. `consumed` is the inbox surfer's target
# (G13, another workstream); the store exposes the primitive so the substrate
# exists.
_CONFIG_DIRECTORIES = ("produced", "consumed")

# Per-project write serialisation (I2): write_config is check-then-write and
# the notes surface is read-modify-write, and the async caller offloads reads
# to worker threads while writes stay on the loop. A per-project lock covers
# the whole critical section regardless of which thread calls, so the
# duplicate gate is not TOCTOU and concurrent note appends never lose a note.
_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


def _lock_for(project_id: str) -> threading.Lock:
    """The per-project lock, created once (the registry itself is guarded
    against concurrent creation)."""
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(project_id)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_LOCKS[project_id] = lock
        return lock


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


def parse_config_file_name(name: str) -> tuple[str, str, str] | None:
    """Parse a config file name back to
    `(unit_id, fault_class, vulnerability_class)`. The last-two-underscores
    convention; `CWE-\\d+` disambiguates the middle segment, so unit_ids (and
    classes) containing `_` round-trip. None when the name does not follow the
    convention (e.g. a non-CWE fault_class - the store's content rebuild is
    the read-side fallback)."""
    match = _CONFIG_FILE_RE.match(name)
    if match is None:
        return None
    return match["unit"], match["cwe"], match["cls"]


def _keys_match(record_key: str, query_key: str) -> bool:
    """The key match rule: an exact semantic key, or a `KEY_SEPARATOR`-bounded
    prefix in either direction. A 2-part revival key (`unit::cwe`) reads every
    class at the locus; a 3-part semantic key reads exactly its config; a note
    keyed by the revival key is found by either."""
    return (record_key == query_key
            or record_key.startswith(query_key + KEY_SEPARATOR)
            or query_key.startswith(record_key + KEY_SEPARATOR))


class DuplicateConfigError(ValueError):
    """A config write whose file name already exists in produced/ or consumed/
    (G4): the enforced novelty gate at the storage layer. The callers degrade
    fail-open (warn + count), never a silent duplicate."""


class HuntStore:
    """The per-project hunt-config + notes memory store (memory-system spec)."""

    def __init__(self, root_dir: str | Path | None = None):
        """Rooted under `root_dir` (default: the FIXED seam root
        `src/polymerhus/attack/hunting/data/`)."""
        self._root = Path(root_dir) if root_dir is not None else HUNT_STORE_ROOT

    # --- path helpers ----------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return self._root / project_id / "orchestration"

    def _produced_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "hunt_configs" / "produced"

    def _consumed_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "hunt_configs" / "consumed"

    def _memory_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "memory.yaml"

    # --- atomic write primitive (I1) --------------------------------------------

    @staticmethod
    def _dump_yaml_atomic(path: Path, body) -> None:
        """Write `body` as YAML atomically: dump to a temp file in the SAME
        directory, then `os.replace` onto the target. A crash mid-dump leaves
        the previous file content intact (the old store's documented "append
        is atomic per file" guarantee) and never a partial target; the leftover
        temp is cleaned up best-effort."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(body, fh, sort_keys=False)
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    # --- config surface ----------------------------------------------------------

    def write_config(self, project_id: str, config, *, directory: str = "produced") -> str:
        """Persist one hunt config's YAML serialisation (the hypothesise /
        ratify write; `status` rides the config object). `config` is a
        `HuntConfig` or a dict. The file name IS the identity: a file that
        already exists in produced/ OR consumed/ fails with
        `DuplicateConfigError` - the deduplication signal (G4). A `dropped`
        config stays on disk statused `dropped`, never deleted (G6). Returns
        the config's semantic key. Raises on write failure - the caller warns
        and counts (O3). The whole check-then-write runs under the project's
        lock, so the duplicate gate is not TOCTOU (I2)."""
        if directory not in _CONFIG_DIRECTORIES:
            raise ValueError(
                f"unknown config directory {directory!r}; known: {_CONFIG_DIRECTORIES}")
        with _lock_for(project_id):
            data = config.model_dump() if not isinstance(config, dict) else dict(config)
            unit_id = str(data.get("unit_id") or "")
            fault_class = str(data.get("fault_class") or "")
            vulnerability_class = str(data.get("vulnerability_class") or "")
            name = config_file_name(unit_id, fault_class, vulnerability_class)
            produced = self._produced_dir(project_id) / name
            consumed = self._consumed_dir(project_id) / name
            if produced.exists() or consumed.exists():
                raise DuplicateConfigError(
                    f"a config for {semantic_key(unit_id, fault_class, vulnerability_class)} "
                    "already exists in produced/ or consumed/; the write is the "
                    "deduplication signal, not a second file"
                )
            target = produced if directory == "produced" else consumed
            # The topology is created lazily at the first write: both config
            # directories (and the orchestration/ parent for memory.yaml) land
            # together, so the produced/consumed substrate exists for the inbox
            # surfer to operate on.
            produced.parent.mkdir(parents=True, exist_ok=True)
            consumed.parent.mkdir(parents=True, exist_ok=True)
            self._dump_yaml_atomic(target, data)
            return semantic_key(unit_id, fault_class, vulnerability_class)

    def update_config(self, project_id: str, config, *, directory: str = "produced") -> str:
        """Persist one hunt config's YAML serialisation, UPSERTING at its
        identity (the ratify-phase write; `status` rides the config object): an
        existing file at the identity is OVERWRITTEN in place - the ratification
        amends the hypothesised draft, and a `dropped` config is marked by
        rewriting its file statused `dropped` (G6: it stays on disk, never
        deleted) - and an absent identity CREATES the file (the ratify phase may
        create additional configs). The G4 novelty gate does NOT apply here: the
        write is an explicit in-place amendment of a known identity, not a
        re-elicitation. Returns the config's semantic key. Raises on write
        failure - the caller warns and counts (O3). The whole write runs under
        the project's lock (I2)."""
        if directory not in _CONFIG_DIRECTORIES:
            raise ValueError(
                f"unknown config directory {directory!r}; known: {_CONFIG_DIRECTORIES}")
        with _lock_for(project_id):
            data = config.model_dump() if not isinstance(config, dict) else dict(config)
            unit_id = str(data.get("unit_id") or "")
            fault_class = str(data.get("fault_class") or "")
            vulnerability_class = str(data.get("vulnerability_class") or "")
            name = config_file_name(unit_id, fault_class, vulnerability_class)
            produced = self._produced_dir(project_id)
            consumed = self._consumed_dir(project_id)
            produced.parent.mkdir(parents=True, exist_ok=True)
            consumed.parent.mkdir(parents=True, exist_ok=True)
            target = produced if directory == "produced" else consumed
            self._dump_yaml_atomic(target / name, data)
            return semantic_key(unit_id, fault_class, vulnerability_class)

    @staticmethod
    def _read_yaml(path: Path) -> dict | None:
        """One config file's dict, fail-open per record: a read/YAML error or
        a non-dict body warns and degrades to None (the record is skipped, the
        caller keeps serving - O4)."""
        try:
            body = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("hunt store: unreadable config %s (%s)", path, exc)
            return None
        return body if isinstance(body, dict) else None

    def _config_with_key(self, path: Path) -> tuple[str, dict] | None:
        """One config file's `(semantic key, body)`: the file-name identity
        first (the convention, G4), the content rebuild as the fallback (a
        non-CWE fault_class or foreign yaml with the identity fields). The body
        is loaded ONCE and shared, so a keyed read never double-reads the file
        (M7)."""
        body = self._read_yaml(path)
        if body is None:
            return None
        parsed = parse_config_file_name(path.name)
        if parsed is not None:
            return semantic_key(*parsed), body
        unit_id = body.get("unit_id")
        if unit_id is None:
            return None
        return (semantic_key(
            str(unit_id),
            str(body.get("fault_class") or ""),
            str(body.get("vulnerability_class") or ""),
        ), body)

    def _config_paths(self, project_id: str) -> list[Path]:
        """Every config file path, produced/ then consumed/, in file-name
        order (deterministic; a missing directory contributes nothing)."""
        paths: list[Path] = []
        for directory in (self._produced_dir(project_id), self._consumed_dir(project_id)):
            if directory.exists():
                paths.extend(sorted(directory.glob("*.yaml")))
        return paths

    def read_configs_by_key(self, project_id: str, key: str) -> list[dict]:
        """The prior configs for a semantic key (`unit::cwe::class`) or a
        2-part revival-key prefix (`unit::cwe`): produced/ then consumed/, in
        file-name order. A missing store or a failing read degrades to an
        empty set - the caller keeps serving (O4)."""
        with _lock_for(project_id):
            out: list[dict] = []
            for path in self._config_paths(project_id):
                item = self._config_with_key(path)
                if item is None:
                    continue
                record_key, body = item
                if not _keys_match(record_key, key):
                    continue
                out.append(body)
            return out

    def read_configs(self, project_id: str) -> list[dict]:
        """Every persisted config (produced + consumed), in deterministic
        order. Fail-open per record (O4)."""
        with _lock_for(project_id):
            out: list[dict] = []
            for path in self._config_paths(project_id):
                body = self._read_yaml(path)
                if body is not None:
                    out.append(body)
            return out

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
        content survives a crash mid-dump (I1)."""
        self._dump_yaml_atomic(self._memory_file(project_id), {"notes": notes})

    def read_notes(self, project_id: str, key: str | None = None) -> list[dict]:
        """The notes for a key (a 2-part revival key or a 3-part semantic key)
        in natural append order; `key=None` returns every note. Fail-open
        (O4)."""
        with _lock_for(project_id):
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
        with _lock_for(project_id):
            record = {"note_id": uuid.uuid4().hex[:12], "revival_key": key, "note": note}
            notes = self._load_notes(project_id)
            notes.append(record)
            self._save_notes(project_id, notes)
            return record

    def update_note(self, project_id: str, note_id: str, note: str) -> bool:
        """Amend the note with `note_id`; False when no such note exists."""
        with _lock_for(project_id):
            notes = self._load_notes(project_id)
            for record in notes:
                if record.get("note_id") == note_id:
                    record["note"] = note
                    self._save_notes(project_id, notes)
                    return True
            return False

    def delete_note(self, project_id: str, note_id: str) -> bool:
        """Remove the note with `note_id`; False when no such note exists."""
        with _lock_for(project_id):
            notes = self._load_notes(project_id)
            kept = [n for n in notes if n.get("note_id") != note_id]
            if len(kept) == len(notes):
                return False
            self._save_notes(project_id, kept)
            return True