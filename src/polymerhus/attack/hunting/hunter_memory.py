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

- `<fault_key>` is the 3-part config key (memory-system G4, ADR #169 Q13's
  `config_id`): the `_`-joined `<unit_id>_<CWE_ID>_<vulnerability_class>`
  form, the config file-name stem, used VERBATIM as the folder name (unit
  ids contain `:` and `-`, so `_` is the one safe separator; `:`, `-`, and
  `::` remain legal path chars - the `::`-joined semantic key
  `hunt_store.semantic_key(...)` round-trips the same 3 parts and is
  accepted too). The 2-part revival key (`<unit_id>::<fault_class>`) is
  NOT the config key and is REJECTED. The `<fault>_<strategy>.yaml` file
  name encodes the concrete fault semantic + testing strategy keywords
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
- The produced->consumed movement is the inbox surfer mover's ownership
  (ADR #169 Q3, tracker #172): the store fixes the topology AND exposes the
  single-owner move primitive `consume_spec` (only the mover renames, #172
  AC); both sides are addressable (`side` on write, `sides` on read),
  `list_fault_keys` / `produced_spec_files` enumerate the produced inbox the
  mover reads per tick.
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

import logging
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import yaml

from .hunt_store import ProjectMemoryStore, parse_config_file_name, semantic_key
from .hunter_state import FAULT_STATUSES

logger = logging.getLogger(__name__)

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

# Per-project write serialisation (the pattern's I2, mirrored from the hunt
# store): `write_spec`'s create-mode novelty gate is check-then-write and the
# mover's produced->consumed rename (tracker #172) is check-then-move, and
# both can run from different threads (the harness offloads sync tool calls to
# worker threads while the mover drives the loop thread). A per-project lock
# covers the whole critical section regardless of which thread calls, so the
# duplicate gate is not TOCTOU and a rename never races a concurrent write.
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


def config_key_from_fault_key(fault_key: str) -> str:
    """The ONE canonical cross-family join key for a `fault_key` (ADR #169
    Q13/G4, identity-based refactor 2026-08-25): return the `::`-joined
    semantic config_key (`hunt_store.semantic_key`) that a `fault_key` folder
    physically carries.

    A `fault_key` may be stored in EITHER form - the `_`-joined
    `<unit_id>_<CWE_ID>_<vulnerability_class>` folder name (the config
    file-name stem), or its round-tripping `::`-joined semantic key
    (`write_spec` accepts both, G4). The inbox surfer's two sides of one
    cross-family join MUST agree on the SAME canonical key - `hunter_inboxes`
    is keyed by the `::` config_key on BOTH the register (hunter dispatch)
    and the lookup (pod dispatch) side - so this is the single source of the
    conversion, home of the physical-folder -> logical-config_key
    normalisation (`_validate_fault_key`'s folder rule, reused here). The
    2-part revival key is NOT a config_key and is refused."""
    if "::" in fault_key:
        # The `::` semantic-key form: must be the full 3-part key (the 2-part
        # revival key is a PREFIX of it, not a config_key - refused).
        parts = fault_key.split("::")
        if len(parts) != 3 or not parts[0] or not parts[1]:
            raise ValueError(
                f"hunter store: fault_key {fault_key!r} is not the 3-part "
                f"config key <unit_id>::<CWE_ID>::<vulnerability_class> (or "
                f"its `_`-joined form); the 2-part revival key is NOT accepted"
            )
        return fault_key
    parsed = parse_config_file_name(f"{fault_key}.yaml")
    if parsed is None:
        raise ValueError(
            f"hunter store: fault_key {fault_key!r} is not the 3-part config "
            f"key <unit_id>::<CWE_ID>::<vulnerability_class> (or its `_`-joined "
            f"form); the 2-part revival key is NOT a config_key"
        )
    return semantic_key(*parsed)


def _validate_spec_file(spec_file: str) -> None:
    """Reject a spec file-name stem that is not one safe filename component
    (G3): the `<fault>_<strategy>` name was sanitised at write time, so a path
    separator, a traversal name, or an empty stem is a caller defect, never a
    legitimate file name. `:`/`-` are legal (they are identity chars)."""
    if not isinstance(spec_file, str) or not spec_file:
        raise ValueError("hunter store: spec_file must be a non-empty string")
    if spec_file in (".", "..") or "/" in spec_file or "\\" in spec_file:
        raise ValueError(
            f"hunter store: spec_file {spec_file!r} is not a safe file-name component"
        )
    if any(ord(ch) < 32 for ch in spec_file):
        raise ValueError(
            f"hunter store: spec_file {spec_file!r} contains a control character"
        )


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
    the `fault_key` is the 3-part config key (`<unit_id>_<CWE_ID>_<
    vulnerability_class>`, G4/ADR Q13 - the 2-part revival key is NOT
    accepted). One YAML file per authored spec (the produced/ file carries
    the status lifecycle), produced/consumed directories, and a per-project
    notes file on the same data contract. A project folder is created lazily
    at the first write; it is never created eagerly.

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
        self._validate_fault_key(fault_key)
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
        are legal (they are the config key's identity chars); a `::`-joined
        semantic key is also a single safe component (its `::` shares the
        unit-id `:` char class). Only path separators, control chars, and
        dot-traversal forms are rejected."""
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

    @staticmethod
    def _validate_fault_key(fault_key: str) -> None:
        """Reject a `fault_key` that is not the 3-part config key (G4/ADR Q13).

        The folder name carries the config's identity: the `_`-joined
        `<unit_id>_<CWE_ID>_<vulnerability_class>` config key (the canonical
        form, matching the config file-name convention - validated through
        the hunt store's own `parse_config_file_name`, so a unit id or class
        containing `_` round-trips) OR the `::`-joined semantic key
        (`hunt_store.semantic_key`); both are safe single path components
        and both carry the full 3 parts (the carried-bare empty class
        round-trips like the hunt store's, G4). The 2-part revival key
        (`<unit_id>::<fault_class>`) is a PREFIX of a semantic key, not a
        config key - a fault_key for the wrong (revival) grain is a caller
        defect and is rejected."""
        HunterMemoryStore._validate_component(fault_key, "fault_key")
        if "::" not in fault_key:
            # The canonical `_`-joined form: parse it as the config file-name
            # convention (the last-two-underscores + `CWE-\\d+` middle), so a
            # 2-part `_`-joined key (no class segment) is rejected too.
            if parse_config_file_name(f"{fault_key}.yaml") is None:
                raise ValueError(
                    f"hunter store: fault_key {fault_key!r} is not the 3-part "
                    f"config key <unit_id>::<CWE_ID>::<vulnerability_class> (or "
                    f"its `_`-joined form); the 2-part revival key is NOT accepted"
                )
            return
        parts = fault_key.split("::")
        if len(parts) != 3 or not parts[0] or not parts[1]:
            raise ValueError(
                f"hunter store: fault_key {fault_key!r} is not the 3-part "
                f"config key <unit_id>::<CWE_ID>::<vulnerability_class> (or "
                f"its `_`-joined form); the 2-part revival key is NOT accepted"
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

        `fault_key` is the 3-part config key (the config's identity, G4):
        the `_`-joined `<unit_id>_<CWE_ID>_<vulnerability_class>` form (the
        config file-name stem, ADR Q13's `config_id`) or its round-tripping
        `::`-joined semantic key - the 2-part revival key is NOT accepted.
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
        # The whole check-then-write critical section runs under the project's
        # lock (I2, mirrored from the hunt store): the create-mode novelty gate
        # is not TOCTOU and a concurrent produced->consumed rename (the mover,
        # #172) can never race the write.
        with _lock_for(project_id):
            if mode == "create" and path.exists():
                raise DuplicateSpecError(
                    f"hunter store: spec file already exists (novelty gate): {path}")
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

        `fault_key` is the 3-part config key (the config's identity, G4) -
        the 2-part revival key is NOT accepted. `None` for a missing file
        (a valid empty result, never a failure); a corrupt file raises (O4,
        the caller degrades to an empty set). With `attributes` given, each
        returned dict is projected onto them."""
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

        Read by the config identifier (`fault_key`): the 3-part config key
        (`<unit_id>_<CWE_ID>_<vulnerability_class>`, G4 - the 2-part revival
        key is NOT accepted); the whole surface context is never returned
        through this store (G3). `sides` selects produced/consumed (default
        both); `statuses` filters on the persisted `status`; `attributes`
        projects each spec onto the given fields. A missing project/fault_key
        yields [] - a valid empty result, never a failure. A corrupt file
        raises (O4)."""
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

    def list_fault_keys(self, project_id: str) -> list[str]:
        """The `test-specs/` fault-key folders in deterministic (sorted)
        order - the config-key envelope the inbox surfer enumerates to read
        the produced spec surface (ADR #169 Q3/#172). Each folder is one
        3-part config key (G4/ADR Q13 `config_id`); the 2-part revival key
        never names a folder. A missing project contributes nothing (a valid
        empty result)."""
        tests_dir = self._project_dir(project_id) / "test-specs"
        if not tests_dir.exists():
            return []
        return sorted(child.name for child in tests_dir.iterdir() if child.is_dir())

    def produced_spec_files(self, project_id: str, fault_key: str) -> list[str]:
        """The PRODUCED-side spec file stems under one fault_key - the
        `<fault>_<strategy>` file names the inbox surfer operates on (ADR
        #169 Q3/#172), in file-name order. `fault_key` is the 3-part config
        key (G4; the 2-part revival key is NOT accepted). `consumed/`
        contributes nothing. A missing side contributes nothing (a valid
        empty result)."""
        side_dir = self._spec_dir(project_id, fault_key) / "produced"
        if not side_dir.exists():
            return []
        return sorted(child.stem for child in side_dir.glob("*.yaml"))

    def consume_spec(self, project_id: str, fault_key: str, spec_file: str) -> bool:
        """Move one produced spec file to consumed/ - the single-owner
        produced->consumed transition of the inbox-surfer protocol
        (ADR #169 Q3/164 spec 6, tracker #172): ONLY the mover calls this
        (the single-owner rename, #172 AC). `spec_file` is the produced spec's
        file-name identity (the `<fault>_<strategy>` stem, G3) under
        `test-specs/<fault_key>/`; `fault_key` is the 3-part config key
        (G4/ADR Q13 `config_id` - the 2-part revival key is NOT accepted).

        True when the spec now lives in consumed/ - renamed NOW, or already
        moved by an earlier tick (at-least-once: the repeated invocation of a
        confirmed move is a no-op success, never an error). False when NO such
        record exists in either side (nothing to move). Raises on a genuine
        storage failure (O3 - the caller warns and counts, never aborting the
        tick) and on an unsafe `spec_file` (a path separator or traversal
        name). Runs under the project's lock (I2, mirroring `write_config`),
        so the rename is not TOCTOU.

        The G4 novelty gate makes produced/ and consumed/ MUTUALLY EXCLUSIVE
        per name; a store where BOTH hold the same name is corrupted, and the
        move refuses to clobber the consumed record (at-least-once: a moved
        message is never lost to a re-write)."""
        _validate_spec_file(spec_file)
        with _lock_for(project_id):
            spec_dir = self._spec_dir(project_id, fault_key)
            produced = spec_dir / "produced" / f"{spec_file}.yaml"
            consumed = spec_dir / "consumed" / f"{spec_file}.yaml"
            if produced.exists() and consumed.exists():
                logger.warning(
                    "hunter store: both produced/ and consumed/ hold %s for "
                    "%s/%s; refusing to clobber the consumed record (fail-open)",
                    spec_file, project_id, fault_key,
                )
                return False
            if not produced.exists():
                return consumed.exists()
            if consumed.exists():
                logger.warning(
                    "hunter store: consume of %s has produced/ and consumed/ "
                    "both on disk; refusing to overwrite (fail-open)",
                    spec_file,
                )
                return False
            consumed.parent.mkdir(parents=True, exist_ok=True)
            os.replace(produced, consumed)
            return True

    # -- the notes surface (G6) -----------------------------------------------

    @staticmethod
    def note_key(fault_key: str, note_name: str) -> str:
        """The hierarchy key of a note: `fault_key:<note_name>` (G6), where
        `fault_key` is the 3-part config key (G4)."""
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

        `append` adds a new note for the `(fault_key, note_name)` key,
        where `fault_key` is the 3-part config key (G4, the config's
        identity - the 2-part revival key is NOT accepted);
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
        self._validate_fault_key(fault_key)
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
          parent_key  - the fault_key (the config identifier, G4); yields that
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
    "config_key_from_fault_key",
]