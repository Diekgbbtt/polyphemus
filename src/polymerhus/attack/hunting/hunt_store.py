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
is another workstream's - #167 - this is the store it binds to). **Sibling
hunter-memory reads (#202):** `read_hunter_specs` / `read_hunter_notes` cross
to the `hunter/` sibling bucket under the same `data/<project_id>/` tree - the
downstream TestImplementationSpecs + the Q16 durable PodExport records that
feed a config's `prior_hunt_insights`, shallow-projected (I3).

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

import json
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
# The CWE token (`CWE-\d+`) anchors the parse: the tri-part name is
# `<unit>_<CWE>_<class>.yaml` and the CWE token whose suffix is the class +
# `.yaml` is the fault-class separator. Splitting on the CWE anchor (instead
# of a greedy last-underscore match) preserves a unit that ITSELF ends in `_` -
# e.g. `AuthenticationMechanism:__singleton__` would otherwise lose its
# trailing underscore and never round-trip its identity (G4). The
# empty-class (carried-bare) degrade keeps the trailing `_` and is tolerated by
# the empty class suffix.
_CONFIG_FILE_RE = re.compile(r"_(CWE-\d+)_")

# The writeable config directories. `consumed` is the inbox-surfer mover's
# target (G13, ADR #169 Q3); the store exposes the produced-side read
# (`read_produced_configs`) and the single-owner move primitive
# (`consume_config`) the mover operates on (tracker #172).
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


def _fault_key_to_config_key(fault_key: str) -> str | None:
    """The hunter-memory bucket folder name -> canonical `::` config_key (G4,
    #202): a `_`-joined `<unit>_<CWE>_<class>` folder round-trips through
    `parse_config_file_name` + `semantic_key`; a folder stored in the `::`
    semantic-key form is returned as-is. None when the folder is not a 3-part
    config key (a 2-part revival key is never a config key)."""
    if "::" in fault_key:
        parts = fault_key.split(KEY_SEPARATOR)
        if len(parts) == 3 and parts[0] and parts[1]:
            return fault_key
        return None
    parsed = parse_config_file_name(f"{fault_key}.yaml")
    if parsed is None:
        return None
    return semantic_key(*parsed)


def _prior_spec_insight(spec: dict) -> dict:
    """The shallow projection of a downstream TestImplementationSpec (#202, I3):
    identity + status + strategy + the spec_ref + the discriminating test
    summary, present-keys only - never the full record, so a config never
    embeds another record's full content (the I3 no-snowball discipline)."""
    out: dict = {"kind": "prior_spec"}
    for key in ("spec_id", "fault_id", "status", "strategy", "spec_ref", "test"):
        if spec.get(key) is not None:
            out[key] = spec[key]
    return out


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
        the project's lock (I2).

        MOVE-AWARE (G4, #192): when the identity ALREADY lives in consumed/ (the
        mover's produced->consumed move landed for it - its at-least-once
        marker), a produced-target write is a NO-OP success returning the
        semantic key. The config is already ratified and durable in consumed/,
        and re-creating a produced/ copy would break the produced/consumed
        mutual exclusivity - the surfer's inbox would never drain, the mover
        would re-dispatch the identity every tick, and the run would hang in
        `running` (the #192 race: the orchestrator's ratify harness write can
        land after the move). A warning logs the race for observability."""
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
            if directory == "produced" and (consumed / name).exists():
                logger.warning(
                    "hunt store: ratify write for %s skipped - the identity "
                    "already lives in consumed/ (post-move write, #192); no "
                    "produced/ copy re-created", name,
                )
                return semantic_key(unit_id, fault_class, vulnerability_class)
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

    def read_produced_configs(self, project_id: str) -> list[tuple[str, str]]:
        """The PRODUCED-side inbox surface (ADR #169 Q3/G13, tracker #172):
        `(semantic_key, config_file_name)` for every produced config, in
        file-name order - what the inbox surfer operates on. `consumed/`
        contributes nothing (its records are already dispatched and moved).

        The identity round-trips from the FILE NAME (G4, first-class) so even
        an unreadable/foreign body is surfaceable by its name; a name outside
        the convention falls back to the body's identity (a file-name-less
        degrade). Fail-open: a missing directory or an unskippable record
        contributes nothing (O4)."""
        with _lock_for(project_id):
            directory = self._produced_dir(project_id)
            if not directory.exists():
                return []
            out: list[tuple[str, str]] = []
            for path in sorted(directory.glob("*.yaml")):
                parsed = parse_config_file_name(path.name)
                if parsed is not None:
                    out.append((semantic_key(*parsed), path.name))
                    continue
                item = self._config_with_key(path)
                if item is not None:
                    out.append((item[0], path.name))
            return out

    def consume_config(self, project_id: str, key: str) -> bool:
        """Move one produced config to consumed/ - the single-owner
        produced->consumed transition of the inbox-surfer protocol
        (ADR #169 Q3/G13, tracker #172): ONLY the mover calls this (the
        single-owner rename, #172 AC). `key` is the config's SEMANTIC key
        (the store's canonical identity, G4); the file name round-trips from
        it, so a produced config at that identity is renamed to consumed/.

        True when the config now lives in consumed/ - renamed NOW, or already
        moved by an earlier tick (at-least-once: the repeated invocation of a
        confirmed move is a no-op success, never an error). False when NO such
        record exists in either side (nothing to move). Raises on a genuine
        storage failure (O3 - the caller warns and counts, never aborting the
        tick) and on a non-3-part key (a revival-key prefix names several
        configs - ambiguous, refused). Runs under the project's lock (I2,
        mirroring `write_config`), so the rename is not TOCTOU.

        The G4 novelty gate makes produced/ and consumed/ MUTUALLY EXCLUSIVE
        per name; a store where BOTH hold the same name is corrupted, and the
        move refuses to clobber the consumed record (at-least-once: a moved
        message is never lost to a re-write)."""
        parts = key.split(KEY_SEPARATOR)
        if len(parts) != 3:
            raise ValueError(
                f"consume_config needs the full 3-part semantic key; "
                f"a {len(parts)}-part key {key!r} names several configs"
            )
        name = config_file_name(*parts)
        with _lock_for(project_id):
            produced = self._produced_dir(project_id) / name
            consumed = self._consumed_dir(project_id) / name
            if produced.exists() and consumed.exists():
                logger.warning(
                    "hunt store: both produced/ and consumed/ hold %s for "
                    "%s; refusing to clobber the consumed record (fail-open)",
                    name, project_id,
                )
                return False
            if not produced.exists():
                return consumed.exists()
            if consumed.exists():
                logger.warning(
                    "hunt store: consume of %s has produced/ and consumed/ "
                    "both on disk; refusing to overwrite (fail-open)",
                    name,
                )
                return False
            consumed.parent.mkdir(parents=True, exist_ok=True)
            os.replace(produced, consumed)
            return True

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

    # --- sibling hunter-memory reads (#202) ------------------------------------

    def read_hunter_specs(self, project_id: str, key: str) -> list[dict]:
        """The downstream TestImplementationSpecs (hunter-memory SIBLING bucket,
        #202): the `hunter/test-specs/<fault_key>/` produced/ + consumed/ spec
        records whose config_key matches `key` (a 3-part semantic config_key or
        a 2-part revival-key prefix), each shallow-projected
        (`_prior_spec_insight`, I3) - the config's `prior_hunt_insights` (G3)
        source. Fail-open per record (O4): a missing sibling, an unreadable
        file, or a non-matching folder contributes nothing; never a raise into
        the caller."""
        out: list[dict] = []
        specs_dir = self._root / str(project_id) / "hunter" / "test-specs"
        if not specs_dir.exists():
            return out
        for fault_dir in sorted(specs_dir.iterdir()):
            if not fault_dir.is_dir():
                continue
            cfg_key = _fault_key_to_config_key(fault_dir.name)
            if cfg_key is None or not _keys_match(cfg_key, key):
                continue
            for directory in (fault_dir / "produced", fault_dir / "consumed"):
                if not directory.exists():
                    continue
                for path in sorted(directory.glob("*.yaml")):
                    body = self._read_yaml(path)
                    if body is None:
                        continue
                    out.append(_prior_spec_insight(body))
        return out

    def read_hunter_notes(self, project_id: str, key: str) -> list[dict]:
        """The Q16 durable PodExport notes (hunter-memory SIBLING bucket, #202):
        the `hunter/notes.yaml` verdict-stub records whose fault_key matches
        `key` (a 3-part config_key or a 2-part revival-key prefix), each
        projected to the export envelope (`verdict` / `terminal_reason` /
        `clean`) plus the source + run_id provenance - shallow (I3), the raw
        evidence trail is never embedded. Fail-open per record (O4): a missing
        sibling, an unreadable file, or a non-matching record contributes
        nothing; never a raise into the caller."""
        out: list[dict] = []
        notes_file = self._root / str(project_id) / "hunter" / "notes.yaml"
        if not notes_file.exists():
            return out
        try:
            loaded = yaml.safe_load(notes_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("hunt store: unreadable hunter notes %s (%s)",
                           notes_file, exc)
            return out
        records = loaded if isinstance(loaded, list) else []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            fault_key = rec.get("fault_key")
            cfg_key = _fault_key_to_config_key(str(fault_key)) if fault_key else None
            if cfg_key is None or not _keys_match(cfg_key, key):
                continue
            prov = rec.get("provenance") or {}
            if not prov.get("verdict_stub"):
                continue
            payload: dict = {"kind": "prior_verdict"}
            for k in ("source", "run_id"):
                if prov.get(k) is not None:
                    payload[k] = prov[k]
            raw = rec.get("body") or ""
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    for k in ("verdict", "terminal_reason", "clean"):
                        if parsed.get(k) is not None:
                            payload[k] = parsed[k]
            except (ValueError, TypeError):
                pass
            out.append(payload)
        return out

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
