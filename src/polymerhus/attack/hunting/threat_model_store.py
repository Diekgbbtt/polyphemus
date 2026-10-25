"""The per-project unit threat model store (S2 4, 5, and 10; T1 #374).

One model document per discretely testable L1 unit, plus one threat file per
dispatchable threat, under the project's threat-modeller bucket:

    data/<project_id>/hunting/threat_modeller/
      notes.yaml                       (bounded episodic notes)
      produced/<unit_name>/
        <unit_name>.yaml               (the model document; the commit marker)
        threat-<rank>.yaml               (one per non-`none` threat, at COMPLETED)
      consumed/<unit_name>/            (the mover's target; at-least-once)
      abandoned/<unit_name>/           (a degraded or invalid model)

`<unit_name>` sanitises `:` and `/` to `-`. The store OWNS every derived
symbol (S2 10.2): the unit directory, the model file name, the threat file name,
the threat id, the dispatch id `<unit_name>__<threat_id>`, and the note key prefix.
The model id is the unit id and stays authoritative.

Write contract:

- A write payload carries only values: `{state, sections}` (plus the
  harness-bound `run_id`). The store derives and binds the identity.
- The state is monotonic (S2 5.3): a lower-gate write merges its section but
  never regresses the persisted state.
- Every write parses the merged document as `PartialThreatModel`; an unknown
  field or a malformed section is rejected loudly. No semantic gate runs at an
  intermediate gate.
- The COMPLETED write (S2 4.3, 5.6) normalises the threats, computes the
  `risk_profile`, runs the non-blocking completion checker, writes the threat
  files first, then commits the model document. A gate write below COMPLETED
  deletes stale produced threat files (crash repair); the next COMPLETED write
  rewrites the whole set.
- A move-aware write (S2 4.5): a write whose identity already lives in
  `consumed/` is a no-op success returning the consumed path. The store never
  recreates a consumed file.
- A name collision (S2 4.2): two distinct unit ids that sanitise to the same
  `<unit_name>` are disambiguated with `-<first 8 hex of sha256(unit_id)>` on
  the later name. The store checks the existing directory's model `unit_id`
  before it writes; a readable DIFFERENT id triggers the suffix. An empty
  directory (a crash between the atomic write's parent mkdir and its replace)
  is reused, and an UNREADABLE model document refuses with a coded error -
  never a suffix (which would fork one unit into two directories) and never a
  clobber (the identity is unknown).
- The notes file uses the shared bounded whole-file primitive (`#341`); the
  model and threat files are single-model files and are not bounded records.
- Every whole-file write routes through the shared atomic primitive (`#340`),
  so a killed write leaves the previous complete file.

Fail-open canon: a read failure degrades (a warning, then None/[]), never a
raise into the caller. A write failure raises to the caller (O3). An unknown
`schema_version` refuses to load (a warning records the version) and refuses a
merge; there is no silent migration.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AbstractSet, Any

import yaml

from polymerhus.app.data_root import DATA_ROOT, project_dir
from polymerhus.app.memory.bounds import notes_body_len
from polymerhus.app.memory.store import BoundedRecordStore

from .threat_model import (
    GATE_SECTIONS,
    SCHEMA_VERSION,
    STATE_ORDER,
    Likelihood,
    ModelState,
    PartialThreatModel,
    UnitThreatModel,
    check_completion,
    compute_risk_profile,
    normalise_threats,
    unit_kind_from_unit_id,
)

logger = logging.getLogger(__name__)

# The model directories (S2 4.2). A threat file lives only in produced/ or
# consumed/; abandoned/ holds the whole unit directory the harness archives.
_FAMILIES = ("produced", "consumed", "abandoned")
_READ_FAMILIES = ("produced", "consumed")

# The notes bound (#341): the same shared primitive and a size ceiling that
# matches the other whole-file hunting notes stores.
NOTES_MAX_RECORDS = 2000
NOTES_MAX_BYTES = 4 * 1024 * 1024

# The existing note kinds (the pattern's #137 Q3). `phase_summary` is the
# hunter's kind and is NOT available to the modeller (S1 5.2).
NOTE_KINDS = (
    "hypothesis_refusal",
    "implicit_test_primitive",
    "wellformedness",
    "freeform",
)

_NOTE_ACTIONS = ("append", "update", "delete")


def sanitise_unit_name(unit_id: str) -> str:
    """The unit directory name (S2 4.2): `:` and `/` become `-`.

    The unit id stays authoritative; the name is the derived on-disk symbol.
    An id that cannot form one safe path component is a coded rejection, never
    a silently composed degenerate name.
    """
    name = unit_id.replace(":", "-").replace("/", "-")
    if not name or name in (".", ".."):
        raise ThreatModelIdentityError(
            ["unit_id"],
            f"threat model store: unit id {unit_id!r} derives an unsafe unit "
            f"directory name {name!r}",
        )
    if any(ord(char) < 32 for char in name) or "\\" in name:
        raise ThreatModelIdentityError(
            ["unit_id"],
            f"threat model store: unit id {unit_id!r} contains a control or "
            f"path character the derived name {name!r} cannot carry",
        )
    return name


def collision_suffix(unit_id: str) -> str:
    """The collision disambiguator: the first 8 hex of sha256(unit_id)."""
    return hashlib.sha256(unit_id.encode("utf-8")).hexdigest()[:8]


def dispatch_id(unit_name: str, threat_id: str) -> str:
    """The threat file's dispatch identity: `<unit_name>__<threat_id>` (S2 8.1)."""
    return f"{unit_name}__{threat_id}"


def threat_file_name(threat_id: str) -> str:
    """The threat file name: `threat-<rank>.yaml` (S2 4.2), derived from the id."""
    return f"{threat_id}.yaml"


# The store-owned threat id form; a caller-supplied key that is not one is a
# coded rejection (the derived-symbol discipline).
_THREAT_ID_RE = re.compile(r"threat-\d+")


def is_threat_id(value: Any) -> bool:
    """True for a store-owned threat id (`threat-<rank>`, S2 10.2). The ONE form
    check: the store's write keys and the mover's dispatch validity predicate
    both read it, so a threat id cannot mean two things."""
    return isinstance(value, str) and _THREAT_ID_RE.fullmatch(value) is not None


def _threat_rank(stem: str) -> int:
    """The numeric rank of a `threat-<rank>` file stem; a non-numeric stem sorts
    first (it can never be a store-written threat file)."""
    suffix = stem.removeprefix("threat-")
    return int(suffix) if suffix.isdigit() else 0


@dataclass(frozen=True)
class _FamilyState:
    """One family directory's read of a derived unit name (S2 4.2)."""

    directory: bool
    model: bool
    unit_id: str | None


class ThreatModelIdentityError(ValueError):
    """A write whose derivation input is missing or malformed (the coded
    teaching rejection of the store-write decisions). `fields` names the
    attribute(s) so the tool can return a field-naming rejection."""

    def __init__(self, fields: list[str], message: str):
        super().__init__(message)
        self.fields = list(fields)


class ThreatModelSchemaVersionError(ValueError):
    """An existing document cannot be read under the reader's schema.

    Either its `schema_version` is not the reader's - there is no silent
    migration (S2 5.8), so the merge refuses and records the version - or the
    body is unreadable/no longer a mapping, in which case merging into it would
    destroy state it still holds."""

    def __init__(self, path: Path, version: Any):
        super().__init__(
            f"threat model store: cannot merge into {path} - unknown "
            f"schema_version {version!r} (this reader knows {SCHEMA_VERSION} "
            f"only) or an unreadable body"
        )
        self.path = path
        self.version = version


class UnitDirectoryCollisionError(ValueError):
    """Both the plain and the collision-suffixed unit names are held by a
    different unit id: writing would clobber another unit's model."""


class ThreatModelDirectoryError(ValueError):
    """A unit directory exists at the derived name and cannot be reused.

    Its model document is unreadable (a truncated or hand-edited file), or the
    produced/consumed/abandoned copies disagree on the unit id. The store
    refuses the write: the collision suffix is reserved for a readable,
    genuinely different unit id, and guessing a second directory would
    silently fork one unit's model."""

    def __init__(self, name: str):
        super().__init__(
            f"threat model store: unit directory {name!r} carries an unreadable "
            f"model document or disagreeing unit ids; refusing to write rather "
            f"than create a second directory for the same unit"
        )
        self.name = name


class ThreatModelDocumentError(ValueError):
    """An existing model document cannot be merged.

    Its persisted `state` is not one of the five workflow gates (a corrupt or
    foreign document). The store refuses with a coded error instead of a raw
    pydantic/enum `ValueError`."""

    def __init__(self, path: Path, state: Any):
        super().__init__(
            f"threat model store: {path} carries unknown state {state!r}; "
            f"known: {tuple(member.value for member in ModelState)}"
        )
        self.path = path
        self.state = state


class ThreatModelStore(BoundedRecordStore):
    """The per-project unit threat model store (S2 10.1)."""

    def __init__(
        self,
        root_dir: str | Path | None = None,
        *,
        class_names: AbstractSet[str] | None = None,
    ):
        """Rooted under `root_dir` (default: the app-owned `DATA_ROOT`); the
        per-project bucket is `<root>/<project_id>/hunting/threat_modeller/`,
        resolved through the ONE `data_root.project_dir` layout owner. The
        explicit-root constructor is kept for the tests' temp stores (the
        retired bounded-store precedent).

        `class_names` is the optional web-vulnerability suite index used by the
        class-binding completion findings. Its findings never reject a write."""
        self._root = Path(root_dir) if root_dir is not None else DATA_ROOT
        self._class_names = frozenset(class_names) if class_names is not None else None

    def set_class_names(self, class_names: AbstractSet[str] | None) -> None:
        """Bind the suite class index after construction.

        The runtime builds the store before the per-unit suite seam exists, so
        the tool surface calls this once the suite classes are known. The
        findings stay non-blocking."""
        self._class_names = frozenset(class_names) if class_names else None

    # --- path helpers ----------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return project_dir(project_id, "hunting/threat_modeller", root=self._root)

    def _family_dir(self, project_id: str, family: str) -> Path:
        return self._project_dir(project_id) / family

    def _unit_dir(self, project_id: str, unit_name: str, family: str) -> Path:
        return self._family_dir(project_id, family) / unit_name

    def _model_path(self, project_id: str, unit_name: str, family: str) -> Path:
        return self._unit_dir(project_id, unit_name, family) / f"{unit_name}.yaml"

    def _notes_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "notes.yaml"

    # --- document reads ---------------------------------------------------------

    def _load_raw(self, path: Path) -> dict | None:
        """One YAML mapping, fail-open: a missing file, an unreadable YAML, or
        a non-mapping body warns and degrades to None (O4)."""
        if not path.exists():
            return None
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("threat model store: unreadable document %s (%s)", path, exc)
            return None
        return loaded if isinstance(loaded, dict) else None

    def _load_document(self, path: Path) -> dict | None:
        """A document under the reader's schema version; an unknown version is
        refused and logged, never migrated (S2 5.8)."""
        raw = self._load_raw(path)
        if raw is None:
            return None
        if raw.get("schema_version") != SCHEMA_VERSION:
            logger.error(
                "threat model store: refusing %s - unknown schema_version %r "
                "(this reader knows %s only)",
                path, raw.get("schema_version"), SCHEMA_VERSION,
            )
            return None
        return raw

    # --- derived unit names (S2 4.2) -------------------------------------------

    def _family_holder(self, project_id: str, name: str, family: str) -> _FamilyState:
        """The ONE family-level read of a derived unit name (S2 4.2): whether
        the directory exists, whether its model document exists, and the unit
        id the document carries (`None` when unreadable or absent). Every name
        scan and the archive both build on this primitive."""
        directory = self._unit_dir(project_id, name, family)
        if not directory.exists():
            return _FamilyState(directory=False, model=False, unit_id=None)
        path = directory / f"{name}.yaml"
        if not path.exists():
            return _FamilyState(directory=True, model=False, unit_id=None)
        raw = self._load_raw(path)
        unit_id = raw.get("unit_id") if raw is not None else None
        if not isinstance(unit_id, str) or not unit_id:
            return _FamilyState(directory=True, model=True, unit_id=None)
        return _FamilyState(directory=True, model=True, unit_id=unit_id)

    def _classify_name(self, project_id: str, name: str) -> tuple[str, str | None]:
        """Classify one candidate name across all three families.

        - `("free", None)`: no directory anywhere.
        - `("empty", None)`: a directory exists but NO model document does (the
          crash window between the atomic write's parent mkdir and its
          `os.replace`): the name is reusable.
        - `("held", unit_id)`: every existing model document carries the SAME
          unit id - that unit owns the name.
        - `("unreadable", None)`: a model document exists but is unreadable, or
          the families disagree on the unit id: the identity is unknown, and
          the caller must refuse rather than guess.
        """
        present = False
        model_present = False
        found: set[str] = set()
        for family in _FAMILIES:
            state = self._family_holder(project_id, name, family)
            present = present or state.directory
            model_present = model_present or state.model
            if state.unit_id is not None:
                found.add(state.unit_id)
        if not present:
            return "free", None
        if not model_present:
            return "empty", None
        if len(found) != 1:
            return "unreadable", None
        return "held", next(iter(found))

    def _candidate_names(self, unit_id: str) -> tuple[str, str]:
        base = sanitise_unit_name(unit_id)
        return base, f"{base}-{collision_suffix(unit_id)}"

    def _unit_name_for_write(self, project_id: str, unit_id: str) -> str:
        """The unit directory name for a write.

        A name already held by THIS unit is reused (a retried write, a unit
        whose earlier copy lives in abandoned/ or consumed/); otherwise the
        first free or empty candidate is taken; a name held by another unit
        triggers the hash suffix. An unreadable holder refuses with a coded
        error - never a suffix (that would fork the unit's directory) and never
        a clobber (the identity is unknown).
        """
        plain, suffixed = self._candidate_names(unit_id)
        classified = {
            name: self._classify_name(project_id, name) for name in (plain, suffixed)
        }
        for name, (kind, _) in classified.items():
            if kind == "unreadable":
                raise ThreatModelDirectoryError(name)
        for name, (kind, holder) in classified.items():
            if kind == "held" and holder == unit_id:
                return name
        for name, (kind, _) in classified.items():
            if kind in ("free", "empty"):
                return name
        raise UnitDirectoryCollisionError(
            f"threat model store: both candidate directories {plain!r} and "
            f"{suffixed!r} are held by another unit; refusing to clobber"
        )

    def _find_model_path(
        self, project_id: str, unit_id: str, family: str
    ) -> Path | None:
        """The model path for `unit_id` in one family, name- and identity-checked.

        Both the plain and the collision-suffixed candidate are tried; the
        identity check on the model's `unit_id` keeps a colliding sibling's
        document from being returned.
        """
        for name in self._candidate_names(unit_id):
            path = self._model_path(project_id, name, family)
            raw = self._load_document(path)
            if raw is not None and raw.get("unit_id") == unit_id:
                return path
        return None

    def read_model(self, project_id: str, unit_id: str) -> dict | None:
        """The unit's model document (produced/ first, then consumed/), or
        None. An unknown `schema_version` refuses to load (a version error is
        logged). A read failure degrades to None, never a raise (O4)."""
        with self._lock_for(project_id):
            path = self._find_model_path(project_id, unit_id, "produced")
            if path is None:
                path = self._find_model_path(project_id, unit_id, "consumed")
            return self._load_document(path) if path is not None else None

    def read_section(self, project_id: str, unit_id: str, section: str) -> Any:
        """One section of the unit's model, or None when the model or the
        section is absent. Read-only."""
        model = self.read_model(project_id, unit_id)
        return model.get(section) if model is not None else None

    def read_threat_files(self, project_id: str, unit_id: str) -> list[dict]:
        """The unit's threat files in rank order: produced/ first, then
        consumed/. Returns [] unless the model is `COMPLETED` AND
        `validation.valid` - S2 4.3: a threat file is never read for a model
        whose state is not COMPLETED, so the crash window (threat files written,
        the model document not yet committed) never surfaces as work. The
        invalidity gate repeats the one consumability predicate (S2 10.5), so
        an invalid COMPLETED model's files are never dispatched. A missing unit
        or a zero-threat model yields [] - a valid empty result, never a failure.
        A malformed threat record is skipped fail-open (T4 owns the dispatch
        refuse-and-log rule)."""
        with self._lock_for(project_id):
            for family in _READ_FAMILIES:
                path = self._find_model_path(project_id, unit_id, family)
                if path is None:
                    continue
                raw = self._load_document(path)
                if raw is None or not self._consumable(raw):
                    return []
                directory = path.parent
                records: list[dict] = []
                for threat_path in sorted(
                    directory.glob("threat-*.yaml"), key=lambda item: _threat_rank(item.stem)
                ):
                    record = self._load_raw(threat_path)
                    if record is not None:
                        records.append(record)
                return records
            return []

    # --- consumption (the mover primitives, S2 8.4) -----------------------------

    @staticmethod
    def _consumable(raw: dict) -> bool:
        """The ONE consumability predicate (S2 5.7, 10.5): the model is
        COMPLETED and its completion validation is valid."""
        validation = raw.get("validation")
        return (
            raw.get("state") == ModelState.COMPLETED.value
            and isinstance(validation, dict)
            and validation.get("valid") is True
        )

    def consume_threat(self, project_id: str, unit_id: str, threat_id: str) -> bool:
        """Move one produced threat file to consumed/ - the single-owner
        produced-to-consumed transition of the mover (S2 8.4). True when the
        threat file now lives in consumed/ (moved now, or already moved by an
        earlier tick - at-least-once). False when no such threat file exists in
        either side. The model document moves with its LAST threat file: when no
        produced threat file remains, a consumable model document is moved too.
        The move refuses to clobber an existing consumed file (fail-open)."""
        if not is_threat_id(threat_id):
            raise ThreatModelIdentityError(
                ["threat_id"],
                f"threat model store: {threat_id!r} is not a threat id of the "
                f"`threat-<rank>` form",
            )
        with self._lock_for(project_id):
            model_path = self._find_model_path(project_id, unit_id, "produced")
            if model_path is None:
                consumed = self._find_model_path(project_id, unit_id, "consumed")
                if consumed is None:
                    return False
                return (consumed.parent / threat_file_name(threat_id)).exists()
            name = model_path.parent.name
            produced_threat = model_path.parent / threat_file_name(threat_id)
            consumed_threat = (
                self._unit_dir(project_id, name, "consumed")
                / threat_file_name(threat_id)
            )
            if not produced_threat.exists():
                return consumed_threat.exists()
            if consumed_threat.exists():
                logger.warning(
                    "threat model store: both produced/ and consumed/ hold %s "
                    "for %s; refusing to clobber the consumed record (fail-open)",
                    produced_threat.name, name,
                )
                return False
            consumed_threat.parent.mkdir(parents=True, exist_ok=True)
            os.replace(produced_threat, consumed_threat)
            if not any(model_path.parent.glob("threat-*.yaml")):
                self._move_model_if_ready(project_id, name)
            return True

    def consume_model_if_done(
        self,
        project_id: str,
        unit_id: str,
        *,
        refused_threats: Sequence[str] = (),
    ) -> bool:
        """Move the unit's model document to consumed/ when it is complete,
        valid, and has no PENDING threat file left (S2 8.4). A zero-threat model is
        consumed here without a dispatch; a model with produced threats stays until
        its last threat file is consumed (by `consume_threat`). True when the model
        now lives in consumed/ (moved now, or already moved).

        `refused_threats` names the produced threat files the mover REFUSED (a
        malformed body it can neither dispatch nor consume as a threat record,
        S2 10.5). Those are not pending threats: counting them would leave the
        model in produced/ forever, so the run could never quiesce (T4a review
        F1). A refused file is left in place - it is debugging evidence, never
        silently deleted - and the model document moves as the ONE consumption
        marker."""
        refused = frozenset(str(threat_id) for threat_id in refused_threats)
        with self._lock_for(project_id):
            model_path = self._find_model_path(project_id, unit_id, "produced")
            if model_path is None:
                consumed = self._find_model_path(project_id, unit_id, "consumed")
                if consumed is None:
                    return False
                raw = self._load_document(consumed)
                return bool(raw is not None and self._consumable(raw))
            raw = self._load_document(model_path)
            if raw is None or not self._consumable(raw):
                return False
            if self._pending_threat_files(model_path.parent, refused):
                return False
            return self._move_model_if_ready(project_id, model_path.parent.name)

    @staticmethod
    def _pending_threat_files(directory: Path, refused: frozenset[str]) -> list[Path]:
        """The produced `threat-*.yaml` files that are still PENDING work: every
        one except the mover-refused stems (S2 8.4/10.5)."""
        return [
            path for path in directory.glob("threat-*.yaml")
            if path.stem not in refused
        ]

    def _move_model_if_ready(self, project_id: str, unit_name: str) -> bool:
        """Move one produced model document to consumed/ when it is consumable;
        the now-empty produced unit directory is removed best-effort. The
        caller has already established that no produced threat file remains."""
        model_path = self._model_path(project_id, unit_name, "produced")
        raw = self._load_document(model_path)
        if raw is None or not self._consumable(raw):
            return False
        consumed_model = self._model_path(project_id, unit_name, "consumed")
        if consumed_model.exists():
            logger.warning(
                "threat model store: both produced/ and consumed/ hold the "
                "model document for %s; refusing to clobber (fail-open)", unit_name,
            )
            return False
        consumed_model.parent.mkdir(parents=True, exist_ok=True)
        os.replace(model_path, consumed_model)
        try:
            model_path.parent.rmdir()
        except OSError:
            pass
        return True

    def read_completed_units(self, project_id: str) -> list[str]:
        """The unit ids whose COMPLETED, valid model lives in consumed/ - the
        intake exclusion surface (S2 9.3). Sorted and deduplicated; an
        unreadable, unknown-version, or invalid document contributes nothing."""
        with self._lock_for(project_id):
            consumed = self._family_dir(project_id, "consumed")
            if not consumed.exists():
                return []
            found: set[str] = set()
            for directory in sorted(consumed.iterdir()):
                if not directory.is_dir():
                    continue
                raw = self._load_document(directory / f"{directory.name}.yaml")
                if raw is None or not self._consumable(raw):
                    continue
                unit_id = raw.get("unit_id")
                if isinstance(unit_id, str) and unit_id:
                    found.add(unit_id)
            return sorted(found)

    def _read_threat_file(self, path: Path) -> tuple[str, dict | None]:
        """One threat file's state (T4a review F1): `("record", body)` when the
        file parses to a mapping, else `("unreadable" | "not-a-mapping", None)`.

        The read is QUIET (unlike `_load_raw`): the produced read reports the
        malformed file to its caller, which refuses it once - a per-read warning
        here would re-log one line per tick for as long as the file lives
        (S2 10.5's log-once discipline)."""
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return "unreadable", None
        if not isinstance(loaded, dict):
            return "not-a-mapping", None
        return "record", loaded

    def _read_family_threats(self, project_id: str, family: str) -> list[dict]:
        """One family's consumable units and their threat files.

        The mover reads BOTH families (F-022): produced/ is the dispatch
        inbox, and consumed/ is the recovery inbox. A consumed threat whose
        hunter wrote no terminal spec set is work again after a provider pause
        - the produced->consumed move is the admission marker, never the
        completion marker. The model document rides the entry so the recovery
        dispatch needs no second read and never re-models the unit.

        A malformed file is REPORTED, never dropped (T4a review F1): dropping
        it would read as "the unit holds no threat file", the mover would consume
        the model, and the store would refuse while the `threat-*.yaml` remains -
        the run would never quiesce (S2 10.5). The mover refuses it once and
        never counts it as a pending threat.
        """
        with self._lock_for(project_id):
            root = self._family_dir(project_id, family)
            if not root.exists():
                return []
            entries: list[dict] = []
            for directory in sorted(root.iterdir()):
                if not directory.is_dir():
                    continue
                raw = self._load_document(directory / f"{directory.name}.yaml")
                if raw is None and family == "consumed":
                    # The model moves with its LAST threat file (S2 8.4), so a
                    # consumed threat from a multi-threat unit still has its model
                    # in produced/. Read that same original document: the
                    # recovery never re-models the unit.
                    raw = self._load_document(
                        self._model_path(project_id, directory.name, "produced"))
                if raw is None or not self._consumable(raw):
                    continue
                unit_id = raw.get("unit_id")
                if not isinstance(unit_id, str) or not unit_id:
                    continue
                threats: list[dict] = []
                malformed: list[dict] = []
                for threat_path in sorted(
                    directory.glob("threat-*.yaml"),
                    key=lambda item: _threat_rank(item.stem),
                ):
                    state, record = self._read_threat_file(threat_path)
                    if state != "record":
                        malformed.append({
                            "threat_id": threat_path.stem,
                            "reason": state,
                        })
                        continue
                    threats.append({"threat_id": threat_path.stem, "record": record})
                entries.append({
                    "unit_id": unit_id,
                    "unit_name": directory.name,
                    "run_id": raw.get("run_id") if isinstance(raw.get("run_id"), str) else "",
                    "threats": threats,
                    "malformed_threats": malformed,
                    # the document this read already parsed: the mover's payload
                    # materialisation reads it (S2 8.2) without a second read
                    "model": raw,
                })
            return entries

    def read_produced_threats(self, project_id: str) -> list[dict]:
        """The mover's dispatch inbox read (S2 8.1/8.4, T4 #377): one entry per
        PRODUCED, consumable unit - `{unit_id, unit_name, run_id, threats,
        malformed_threats, model}` - with `threats` the unit's produced threat file
        records in rank order, each as `{threat_id, record}` (the file stem plus the
        record verbatim, so the mover's validity predicate can check the two
        agree), `malformed_threats` the file stems whose body is unreadable or not a
        mapping, each as `{threat_id, reason}`, and `model` the document this read
        already parsed (the mover's payload context, S2 8.2: the threat file does
        not duplicate the model).

        A zero-threat consumable model IS an entry with no threats and no malformed
        files - the mover consumes it without a dispatch. A model below
        COMPLETED or invalid is never dispatch input (S2 4.3, 5.7)."""
        return self._read_family_threats(project_id, "produced")

    def read_consumed_threats(self, project_id: str) -> list[dict]:
        """The mover's recovery inbox read (F-022): one entry per CONSUMED,
        consumable unit, in the same shape as `read_produced_threats`.

        The consumed family is not "decided and never re-dispatched": the
        produced->consumed move is admission, and the hunter's terminal spec
        set is completion. After a provider pause a consumed threat can have no
        terminal set, so the mover recovers it from here.

        The model dependency is the ORIGINAL model document, never a re-model.
        The model moves to consumed/ with the unit's LAST threat file, so for a
        multi-threat unit the consumed threat still finds its model in produced/;
        the read falls back to it. A zero-threat consumed unit is not work and
        carries no recovery entry (its threats list is empty)."""
        return self._read_family_threats(project_id, "consumed")

    def read_produced_units(self, project_id: str) -> list[dict]:
        """Every produced model's `{unit_id, run_id, state}` (S2 9.3).

        The intake freeze reads the produced family to tell an in-flight model
        (its producing run is live or resumable) from a stale one. Ordered by
        unit directory name; a document without a readable unit id or run id
        contributes nothing (the freeze never guesses an identity it cannot
        attribute).
        """
        with self._lock_for(project_id):
            produced = self._family_dir(project_id, "produced")
            if not produced.exists():
                return []
            found: list[dict] = []
            for directory in sorted(produced.iterdir()):
                if not directory.is_dir():
                    continue
                raw = self._load_document(directory / f"{directory.name}.yaml")
                if raw is None:
                    continue
                unit_id = raw.get("unit_id")
                run_id = raw.get("run_id")
                if not isinstance(unit_id, str) or not unit_id:
                    continue
                found.append({
                    "unit_id": unit_id,
                    "run_id": run_id if isinstance(run_id, str) else "",
                    "state": raw.get("state"),
                })
            return found

    def archive_unit(self, project_id: str, unit_id: str, reason: str) -> Path | None:
        """Move the unit's produced directory to abandoned/ (S2 7.7).

        The harness calls this for a degraded unit or a COMPLETED model whose
        validation failed; the intake and the mover ignore abandoned/. A unit
        whose earlier attempt is already abandoned is REPLACED by the newest
        degraded copy - abandoned/ is a graveyard for debugging, not a history
        log, and it never carries two models for one unit. A consumed model is
        never touched (it is decided).

        Returns the abandoned unit directory when one exists after the call
        (moved now, or already archived); None when there is nothing to archive
        or the unit's model is already decided in consumed/.

        `reason` is the harness-recorded degradation reason; it is logged here
        (the run record is the durable home of the degraded-unit findings).
        """
        with self._lock_for(project_id):
            produced_path = self._find_model_path(project_id, unit_id, "produced")
            if produced_path is None:
                for name in self._candidate_names(unit_id):
                    state = self._family_holder(project_id, name, "abandoned")
                    if state.directory and state.unit_id == unit_id:
                        return self._unit_dir(project_id, name, "abandoned")
                if self._find_model_path(project_id, unit_id, "consumed") is not None:
                    logger.warning(
                        "threat model store: archive of %s skipped - its model "
                        "already lives in consumed/ (decided)", unit_id,
                    )
                    return None
                logger.warning(
                    "threat model store: archive of %s skipped - no produced "
                    "model to archive (%s)", unit_id, reason,
                )
                return None
            produced_name = produced_path.parent.name
            destination_name = None
            for name in (produced_name, *self._candidate_names(unit_id)):
                state = self._family_holder(project_id, name, "abandoned")
                if not state.directory or state.unit_id == unit_id:
                    destination_name = name
                    break
            if destination_name is None:
                raise UnitDirectoryCollisionError(
                    f"threat model store: no abandoned name is free for "
                    f"{unit_id!r}; refusing to clobber another unit's archive"
                )
            destination = self._unit_dir(project_id, destination_name, "abandoned")
            if destination.exists():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(produced_path.parent, destination)
            logger.warning(
                "threat model store: archived %s to abandoned/ (%s)",
                produced_name, reason,
            )
            return destination

    def read_abandoned_units(self, project_id: str) -> list[str]:
        """The unit ids with an abandoned model - the retry surface (S2 9.3:
        abandoned units are ignored and retried, never excluded). Sorted and
        deduplicated; an unreadable or unknown-version document contributes
        nothing."""
        with self._lock_for(project_id):
            abandoned = self._family_dir(project_id, "abandoned")
            if not abandoned.exists():
                return []
            found: set[str] = set()
            for directory in sorted(abandoned.iterdir()):
                if not directory.is_dir():
                    continue
                raw = self._load_document(directory / f"{directory.name}.yaml")
                if raw is None:
                    continue
                unit_id = raw.get("unit_id")
                if isinstance(unit_id, str) and unit_id:
                    found.add(unit_id)
            return sorted(found)

    # --- the gate write (S2 5.4) -----------------------------------------------

    @staticmethod
    def _section_value(value: Any) -> Any:
        """The JSON-safe section content.

        A typed section object (or a list of them) renders through
        `model_dump(mode="json")`; a plain mapping or list payload passes
        through for pydantic to validate, so T2 may send either form.
        """
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, (list, tuple)):
            return [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in value
            ]
        return value

    def write_sections(
        self,
        project_id: str,
        unit_id: str,
        state: str | ModelState,
        sections: Mapping[str, Any],
        *,
        run_id: str,
    ) -> Path:
        """Merge one gate write into the unit's model and persist it.

        `state` selects the allowed `sections` keys (S2 5.4); a key outside the
        gate's set is a coded rejection. The state is monotonic: a lower-gate
        write updates content but leaves the persisted state unchanged. The
        COMPLETED write normalises the threats, computes the risk profile, runs
        the checker, emits the threat files, and commits the document last
        (S2 4.3). A gate write below COMPLETED deletes stale produced threat
        files. A write whose identity already lives in consumed/ is a no-op
        success returning the consumed path (S2 4.5).

        `run_id` is the harness-held run identity, bound on the first write;
        a later write preserves the document's recorded run id.
        """
        try:
            gate = ModelState(state)
        except ValueError as exc:
            raise ThreatModelIdentityError(
                ["state"],
                f"threat model store: unknown state {state!r}; known: "
                f"{tuple(gate.value for gate in ModelState)}",
            ) from exc
        allowed = GATE_SECTIONS[gate]
        unexpected = [key for key in sections if key not in allowed]
        if unexpected:
            raise ThreatModelIdentityError(
                unexpected,
                f"threat model store: state {gate.value} accepts only "
                f"{allowed}; got {tuple(unexpected)}",
            )
        unit_id = unit_id if isinstance(unit_id, str) else str(unit_id or "")
        if not unit_id:
            raise ThreatModelIdentityError(
                ["unit_id"],
                "threat model store: write needs a non-empty harness-bound unit id",
            )
        if not run_id:
            raise ThreatModelIdentityError(
                ["run_id"],
                "threat model store: write needs a non-empty harness-bound run id",
            )
        with self._lock_for(project_id):
            unit_name = self._unit_name_for_write(project_id, unit_id)
            consumed_path = self._model_path(project_id, unit_name, "consumed")
            if consumed_path.exists():
                logger.warning(
                    "threat model store: write for %s skipped - the identity "
                    "already lives in consumed/ (post-move write); no produced/ "
                    "copy re-created", unit_name,
                )
                return consumed_path
            model_path = self._model_path(project_id, unit_name, "produced")
            existing = self._load_document(model_path)
            if existing is None and model_path.exists():
                # Present but refused (an unknown schema_version or an
                # unreadable body): never merge into a document we cannot read.
                raise ThreatModelSchemaVersionError(model_path, self._raw_version(model_path))
            now = datetime.now(timezone.utc)
            doc = self._merged_document(existing, unit_id, run_id, gate, sections, now, model_path)
            self._commit(project_id, unit_name, doc, gate, now)
            return model_path

    @staticmethod
    def _raw_version(path: Path) -> Any:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return None
        return loaded.get("schema_version") if isinstance(loaded, dict) else None

    def _merged_document(
        self,
        existing: dict | None,
        unit_id: str,
        run_id: str,
        gate: ModelState,
        sections: Mapping[str, Any],
        now: datetime,
        path: Path,
    ) -> PartialThreatModel:
        """The merged, parsed document: identity bound, sections applied, the
        state kept monotonic, and - at COMPLETED - the threats normalised and
        the risk profile computed."""
        if existing is None:
            doc: dict = {
                "schema_version": SCHEMA_VERSION,
                "unit_id": unit_id,
                "unit_kind": unit_kind_from_unit_id(unit_id).value,
                "run_id": run_id,
                "created_at": now,
                "updated_at": now,
                "state": gate.value,
            }
        else:
            doc = {key: value for key, value in existing.items()}
            doc["updated_at"] = now
            try:
                persisted = ModelState(doc["state"])
            except (KeyError, ValueError) as exc:
                raise ThreatModelDocumentError(path, doc.get("state")) from exc
            doc["state"] = max(persisted, gate, key=STATE_ORDER.__getitem__).value
        for key, value in sections.items():
            doc[key] = self._section_value(value)
        model = PartialThreatModel.model_validate(doc)
        if gate is ModelState.COMPLETED:
            model.threats = normalise_threats(model.threats)
            model.risk_profile = compute_risk_profile(model.threats)
            model.validation = check_completion(
                UnitThreatModel.model_validate(model.model_dump()),
                class_names=self._class_names,
            )
        return model

    def _commit(
        self,
        project_id: str,
        unit_name: str,
        model: PartialThreatModel,
        gate: ModelState,
        now: datetime,
    ) -> None:
        """Persist the document under the commit protocol (S2 4.3).

        A COMPLETED gate write lands the threat files first (atomically,
        replacing the whole set), then the model document as the commit
        marker. A gate write below COMPLETED whose EFFECTIVE state is also
        below COMPLETED deletes the stale produced threat files (crash repair).
        A late lower-gate write on an already COMPLETED model leaves the
        committed threat set untouched: the state never regresses, so deleting
        its dispatch files would corrupt a published model.
        """
        produced_dir = self._unit_dir(project_id, unit_name, "produced")
        model_path = self._model_path(project_id, unit_name, "produced")
        if gate is ModelState.COMPLETED:
            self._write_threat_files(project_id, unit_name, model, now)
        elif ModelState(model.state) is not ModelState.COMPLETED:
            self._delete_threat_files(produced_dir)
        self._dump_yaml_atomic(model_path, model.model_dump(mode="json"))

    def _write_threat_files(
        self,
        project_id: str,
        unit_name: str,
        model: PartialThreatModel,
        now: datetime,
    ) -> None:
        produced_dir = self._unit_dir(project_id, unit_name, "produced")
        written: set[str] = set()
        for threat in model.threats:
            # A threat with zero combined risk is stored in the model but never
            # dispatched: the impact axis can zero a high-likelihood direction.
            if threat.risk <= 0:
                continue
            record = {
                "threat_id": threat.id,
                "unit_id": model.unit_id,
                "unit_kind": model.unit_kind.value,
                "run_id": model.run_id,
                "dispatch_id": dispatch_id(unit_name, threat.id),
                "likelihood": threat.likelihood.value,
                "threat": threat.model_dump(mode="json"),
                "created_at": now,
            }
            name = threat_file_name(threat.id)
            written.add(name)
            self._dump_yaml_atomic(produced_dir / name, record)
        for path in produced_dir.glob("threat-*.yaml"):
            if path.name not in written:
                try:
                    path.unlink()
                except OSError as exc:
                    logger.warning(
                        "threat model store: could not delete stale threat file %s (%s)",
                        path, exc,
                    )

    def _delete_threat_files(self, produced_dir: Path) -> None:
        if not produced_dir.exists():
            return
        for path in produced_dir.glob("threat-*.yaml"):
            try:
                path.unlink()
            except OSError as exc:
                logger.warning(
                    "threat model store: could not delete stale threat file %s (%s)",
                    path, exc,
                )

    # --- the notes store (#341, S1 5.2) -----------------------------------------

    def _load_notes(self, project_id: str) -> list[dict]:
        """The notes list in natural append order; a missing file or an
        unreadable `notes.yaml` degrades to [] (warned, never a raise)."""
        loaded = self._load_raw(self._notes_file(project_id))
        notes = loaded.get("notes") if loaded is not None else None
        if not isinstance(notes, list):
            return []
        return [note for note in notes if isinstance(note, dict)]

    def _save_notes(self, project_id: str, notes: list[dict]) -> None:
        """Rewrite `notes.yaml` under the shared bound (#341); a failure raises
        to the caller (O3). Atomic through the shared primitive."""
        kept = self._bounded(
            notes,
            max_records=NOTES_MAX_RECORDS,
            max_bytes=NOTES_MAX_BYTES,
            render=notes_body_len,
        )
        self._dump_yaml_atomic(self._notes_file(project_id), {"notes": kept})

    def write_note(
        self,
        project_id: str,
        unit_id: str,
        *,
        action: str = "append",
        note_name: str,
        kind: str,
        body: str,
        evidence: str | None = None,
        provenance: dict | None = None,
    ) -> str | None:
        """The `notes` body write over the per-project `notes.yaml`.

        The key is the store-owned `<unit_name>:<note_name>` (S2 10.2);
        `append` adds a note, `update` amends it, `delete` removes it. Returns
        the key; an update/delete on a missing key returns None (a denoted
        miss, never a failure). `phase_summary` is the hunter's kind and is
        NOT available here. Notes keep their natural append order and are
        bounded by the shared whole-file primitive."""
        if action not in _NOTE_ACTIONS:
            raise ValueError(f"threat model store: unknown note action {action!r}; known: {_NOTE_ACTIONS}")
        if kind not in NOTE_KINDS:
            raise ValueError(f"threat model store: unknown note kind {kind!r}; known: {NOTE_KINDS}")
        if not isinstance(note_name, str) or not note_name:
            raise ThreatModelIdentityError(
                ["note_name"], "threat model store: note_name must be a non-empty string"
            )
        if not isinstance(unit_id, str) or not unit_id:
            raise ThreatModelIdentityError(
                ["unit_id"], "threat model store: note needs a non-empty unit id"
            )
        with self._lock_for(project_id):
            key = f"{self._unit_name_for_write(project_id, unit_id)}:{note_name}"
            notes = self._load_notes(project_id)
            if action == "append":
                notes.append({
                    "key": key,
                    "unit_id": unit_id,
                    "note_name": note_name,
                    "kind": kind,
                    "body": body,
                    "evidence": evidence,
                    "provenance": provenance or {},
                })
                self._save_notes(project_id, notes)
                return key
            for record in notes:
                if record.get("key") != key:
                    continue
                if action == "update":
                    record.update({
                        "kind": kind,
                        "body": body,
                        "evidence": evidence,
                        "provenance": provenance or {},
                    })
                else:  # delete
                    notes.remove(record)
                self._save_notes(project_id, notes)
                return key
            return None

    def read_notes(self, project_id: str, key: str | None = None) -> list[dict]:
        """The notes for a `<unit_name>:<note_name>` key (a `<unit_name>`
        prefix reads the unit's notes), latest-first; `key=None` returns every
        note. Fail-open: an unreadable file degrades to [] (O4)."""
        with self._lock_for(project_id):
            notes = self._load_notes(project_id)
            if key is not None:
                notes = [
                    note for note in notes
                    if str(note.get("key") or "") == key
                    or str(note.get("key") or "").startswith(f"{key}:")
                ]
            return list(reversed(notes))
