"""The hunter-owned per-project spec-set store (S3 8.6-8.8, T6 #379).

The hunter's durable memory, replicating the hunt-config memory store patterns
(`docs/design/hunting-memory-system-spec.md`, the pattern document) and adapted
to the loop-driven hunter by the ratified redesign (S3 8.6-8.8). The store is
per-project (a folder keyed by `project_id`, created lazily at the first
write), one YAML file per spec, produced/consumed directories, and a
per-project notes file.

Topology under the app-owned `DATA_ROOT` (no env var; the explicit-root
constructor is kept for tests). The store shares the ONE per-project sibling
scheme, resolved through the single `data_root.project_dir` layout owner, with
the threat-model store (`<project_id>/hunting/threat_modeller/`) and the pod
memory (`<project_id>/hunting/test-executor-pod/`): the hunter memory is the
`hunting/hunter/` bucket under the SAME `<project_id>/` tree:

    <project_id>/hunting/hunter/test-specs/<hunt_key>/produced/<spec_id>.yaml
    <project_id>/hunting/hunter/test-specs/<hunt_key>/consumed/<spec_id>.yaml
    <project_id>/hunting/hunter/notes.yaml

- `<hunt_key>` is the loop dispatch id `<unit_name>__<loop_id>` (S3 8.9): the
  loop file IS the dispatch grain, so the spec folder is the loop's own
  identity - never a config key or a `fault_key`. The key is bound at tool
  construction and is never a request field.
- `<spec_id>` is the DERIVED file-name stem `<fault_keyword>_<strategy_keyword>`
  (S3 8.6): the payload carries no `spec_id`, and the store derives it from the
  sanitised keywords. `_` is the one safe separator, so `_`, `:`, path
  separators and control chars are replaced with `-` in a keyword (a keyword
  that sanitises to an unsafe/empty component is rejected, never mangled).
- The spec body is the reduced D4 at EVERY status (S3 8.6/8.9); there is no
  `FaultItem` draft body and no `specified` body distinction. The file carries
  the spec's `status` verbatim: `hypothesised` is the GENERATE draft set,
  `ratified` the surviving spec at the terminal write, `dropped` the declassed
  unfeasible spec (`hunter_state.SPEC_STATUSES` is the one live vocabulary).
- A `specs` list write carries the WHOLE set in one call (S3 8.7): the
  GENERATE write is all-`hypothesised`, the terminal write promotes the
  survivors to `ratified` and declasses the unfeasible to `dropped`. A
  duplicate identity inside one write is the denoted deduplication signal
  (`DuplicateSpecError`); a re-author of an existing identity updates it in
  place (the hypothesised write creates, a later status upserts).
- MOVE-AWARE (the #205 rule, carried onto the set): when an identity ALREADY
  lives in consumed/ (the mover's at-least-once marker landed), a
  produced-target write for it is a NO-OP success returning the durable
  consumed path - it never re-creates a produced/ copy, so produced/ and
  consumed/ stay mutually exclusive per name and the surfer's spec inbox keeps
  draining.
- The produced->consumed movement is the inbox surfer mover's ownership (ADR
  #169 Q3, tracker #172): the store fixes the topology AND exposes the
  single-owner move primitive `consume_spec` (only the mover renames, #172
  AC); both sides are addressable (`side` on write, `sides` on read),
  `list_hunt_keys` / `produced_spec_files` enumerate the produced inbox the
  mover reads per tick.
- The notes file follows the SAME data contract as the spec body (G6):
  read/write, write options append/update/delete, grep-match read,
  read-latest. The hunter-only `phase_summary` kind is the interposed pass
  exit (S4 14.8): the note name is `phase:<state>` and a loop re-iteration
  updates the same note. Notes keep their natural append order - no
  `_seq`/`_ref` bookkeeping.

Degradation (unchanged canon, spec 9): a read failure raises (O4, the caller
degrades to an empty set and keeps serving), a write failure raises (O3, the
caller warns and keeps serving), and a corrupt/unparseable file raises rather
than silently returning [] - the rewrite-on-write paths would otherwise
destroy history. Never a silent corruption. Every file write is atomic (#340):
the body is rendered in memory and landed through the shared `app.atomic_write`
primitive (same-directory temp + fsync + `os.replace`), so a kill or abort
mid-write never leaves a malformed `notes.yaml` and a reader always sees either
the previous or the new complete file.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import DATA_ROOT, project_dir
from polymerhus.app.memory.store import BoundedRecordStore

from .hunt_store import ProjectMemoryStore
from .hunter_state import PHASE_SUMMARY_KIND, SPEC_STATUSES
from .spec_contract import (
    SKILL_CONCRETISED_PROCEDURE_MAX_CHARS,
    SkillConcretisedProcedure,
    spec_identifier,
)

logger = logging.getLogger(__name__)

# The per-project bucket is resolved through the ONE `data_root.project_dir`
# layout owner (the `hunting/hunter/` bucket under `DATA_ROOT`); no env var.
# The explicit-root constructor is kept for the tests' temp stores.

# The produced/consumed sides and the write/note operation enums (G7, G6).
_SPEC_SIDES = ("produced", "consumed")
_NOTE_ACTIONS = ("append", "update", "delete")

# The closed enum of note kinds (the pattern's #137 Q3), reused verbatim on
# the hunter's notes so the data contract is the SAME as the pattern's store -
# plus the hunter-only `phase_summary` kind (S4 14.8/Q51a): the interposed
# phase-exit note whose name is `phase:<state>`. The hunt-store and pod enums
# do NOT gain it and the modeller's `notes` tool refuses it.
NOTE_KINDS = tuple(ProjectMemoryStore.NOTE_KINDS) + (PHASE_SUMMARY_KIND,)

HUNTER_NOTES_MAX_RECORDS = 1000
HUNTER_NOTES_MAX_BYTES = 4 * 1024 * 1024




def _is_durable_prior_insight(record: dict) -> bool:
    """The durable prior-insight marker (G3/#202): a Q16 pod-export stub
    (`provenance.verdict_stub`) is the durable pod-completion record the surfer
    writes for a parent hunt key, so it is protected from the ordinary-notes
    eviction of the `notes.yaml` bound (#341). The old
    `HuntStore` consumer retired with the config family; the
    record stays the durable trail a later verdict/insight reader can use."""
    provenance = record.get("provenance")
    return bool(isinstance(provenance, dict) and provenance.get("verdict_stub"))


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


def _require_discriminators(spec: dict) -> list[Any]:
    """The spec's ordered discriminators, validated as a 2..4 item list.

    A missing, too-short, too-long, duplicate-axis, or unsafe tuple is a
    `ValueError` the tool turns into a coded teaching rejection naming the
    field; the store never composes a degenerate file name."""
    if not isinstance(spec, dict):
        raise ValueError("hunter store: each spec must be a mapping")
    raw = spec.get("discriminators")
    if not isinstance(raw, list):
        raise ValueError(
            "hunter store: the spec payload must carry `discriminators` as a "
            "list of {axis, value} entries (two to four), in DISCRIMINATE order")
    # `spec_identifier` owns the count, axis, and value checks so the tool and
    # the store cannot disagree about a legal identity.
    return raw


def validate_skill_concretised_procedure(raw: Any) -> None:
    """Validate a spec's typed `skill_concretised_procedure`.

    When present it must parse and its total length must stay under
    `SKILL_CONCRETISED_PROCEDURE_MAX_CHARS`. A malformed or over-long object is
    a coded teaching rejection (never a silent truncation). An absent object is
    legal: the model may author a spec before a class skill is loaded, and the
    triager then records the gap and uses its fallback."""
    if raw is None:
        return
    try:
        procedure = (
            raw if isinstance(raw, SkillConcretisedProcedure)
            else SkillConcretisedProcedure.model_validate(raw)
        )
    except Exception as exc:  # noqa: BLE001 - a coded rejection, not a crash
        raise ValueError(
            "hunter store: skill_concretised_procedure must be the typed "
            "nine-field SkillConcretisedProcedure "
            "(recon_action, bypass_technique, advanced_technique, "
            "preliminary_chaining, payload_vector, technology_misconfiguration, "
            f"technology_grounding, pro_tips, interpretation_pitfalls): {exc}"
        ) from exc
    if procedure.excerpt_length() > SKILL_CONCRETISED_PROCEDURE_MAX_CHARS:
        raise ValueError(
            "hunter store: skill_concretised_procedure exceeds the "
            f"{SKILL_CONCRETISED_PROCEDURE_MAX_CHARS}-character bound; shorten "
            "the target-specific concretisation")


class DuplicateSpecError(Exception):
    """The denoted deduplication signal (G4, S3 8.7).

    A `specs` write that carries the same derived identity twice raises this -
    the enforced novelty gate inside the batch, the dedup signal the model
    interprets (it reflects on overlap and merges or refreshes instead of
    duplicating). A re-author of an EXISTING identity is not a duplicate: the
    hypothesised write creates and a later status upserts in place.
    """


class IncompleteSpecSetError(ValueError):
    """A terminal spec-set write omitted a previously authored draft.

    The terminal VERIFY-CLAIMS write carries the WHOLE set: every earlier
    hypothesised spec must be promoted (`ratified`) or explicitly declassed
    (`dropped`). Silently omitting one drops it from the pod path without any
    recorded decision (the comfyui-003 `/view` SVG draft was lost exactly this
    way). The error names the missing derived identities so the hunter can
    close the set instead of forgetting a branch.
    """

    def __init__(self, missing: Sequence[str], hunt_key: str):
        self.missing = list(missing)
        self.hunt_key = hunt_key
        super().__init__(
            "hunter store: the terminal spec-set write for "
            f"{hunt_key!r} omits {len(self.missing)} previously authored "
            f"draft(s): {', '.join(self.missing)}. The terminal write carries "
            "the WHOLE set: promote each survivor to `ratified` or declass "
            "each unfeasible spec to `dropped`; do not silently omit a draft."
        )


class HunterMemoryStore(BoundedRecordStore):
    """The hunter-owned per-project spec-set store (S3 8.8/T6).

    Per-project, per-`hunt_key` durable memory of the loop-driven hunter: the
    `hunt_key` is the loop dispatch id `<unit_name>__<loop_id>` (S3 8.9). One
    YAML file per authored spec (the produced/ file carries the status
    lifecycle), produced/consumed directories, and a per-project notes file on
    the same data contract. A project folder is created lazily at the first
    write; it is never created eagerly.

    Determinism + fail-open: writes raise on failure (the caller degrades to a
    warning and keeps serving - O3), reads raise on failure (the harness
    degrades to an empty set and keeps serving - O4). A corrupt file raises
    rather than returning [] - the rewrite-on-write paths would otherwise
    destroy history. Never a silent corruption.
    """

    def __init__(self, root_dir: str | Path | None = None):
        """The hunter memory store rooted under `root_dir` (default: the
        app-owned `DATA_ROOT`), with the per-project `hunting/hunter/` bucket
        resolved through the ONE `data_root.project_dir` layout owner."""
        self._root = Path(root_dir) if root_dir is not None else DATA_ROOT

    # -- paths -------------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return project_dir(project_id, "hunting/hunter", root=self._root)

    def _spec_dir(self, project_id: str, hunt_key: str) -> Path:
        self._validate_hunt_key(hunt_key)
        return self._project_dir(project_id) / "test-specs" / hunt_key

    def _spec_file(
        self,
        project_id: str,
        hunt_key: str,
        spec_id: str,
        side: str,
    ) -> Path:
        self._validate_side(side)
        _validate_spec_file(spec_id)
        return self._spec_dir(project_id, hunt_key) / side / f"{spec_id}.yaml"

    def _terminal_file(self, project_id: str, hunt_key: str) -> Path:
        return self._spec_dir(project_id, hunt_key) / "terminal.yaml"

    def _notes_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "notes.yaml"

    # -- validation + sanitisation (G3) --------------------------------------

    @staticmethod
    def _validate_component(value: str, what: str) -> None:
        """Reject a `project_id`/`hunt_key` that is not one safe path component.

        The loop dispatch id is used verbatim as the folder name, so `:` and
        `-` are legal (they are identity chars of the unit name and loop id);
        only path separators, control chars, and dot-traversal forms are
        rejected."""
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
    def _validate_hunt_key(hunt_key: str) -> None:
        """Reject a `hunt_key` that is not one safe folder component (S3 8.9).

        The key is the loop dispatch id `<unit_name>__<loop_id>`; `__` is the
        separator between its two store-owned parts. The store validates the
        PATH component only: the key is bound at tool construction from the
        dispatched loop, never authored as a request field."""
        HunterMemoryStore._validate_component(hunt_key, "hunt_key")

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

    def _write_records(self, path: Path, records: list[dict]) -> None:
        # Destination safety net only: the app scaffold owns the fixed topology
        # (ensure_project); a store rooted outside it still needs its own file's
        # parent to exist. Atomic (#340): render first, then temp + fsync +
        # os.replace, so an aborted write leaves the previous notes.yaml intact
        # - never a truncated file every later read rejects.
        self._dump_yaml_atomic(
            path,
            self._bounded(
                records,
                max_records=HUNTER_NOTES_MAX_RECORDS,
                max_bytes=HUNTER_NOTES_MAX_BYTES,
                protected=_is_durable_prior_insight,
            ),
        )

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

    # -- the spec-set surface (the `hunts_store` seam, S3 8.7) ---------------

    def write_specs(
        self,
        project_id: str,
        hunt_key: str,
        specs: Sequence[dict],
        *,
        side: Literal["produced", "consumed"] = "produced",
        enforce_complete: bool = True,
    ) -> list[tuple[str, Path]]:
        """Write the spec set under `test-specs/<hunt_key>/<side>/`.

        `specs` is the batch the caller holds: every entry carries a `status`
        in `hunter_state.SPEC_STATUSES` and the two file-name identity
        attributes `fault_keyword` / `strategy_keyword`. The store DERIVES each
        `spec_id` (and therefore the file name) from the keywords and persists
        the body verbatim - the reduced D4 at every status (S3 8.6).

        The GENERATE write is all-`hypothesised` and creates the set; the
        terminal write carries the whole set with the survivors `ratified` and
        the unfeasible `dropped`, UPSERTING each identity in place (S3 8.7).
        F-025: the hunter tool writes ONE spec per call, so its store calls
        pass `enforce_complete=False`; the whole-set omission check moves to
        `finalize_specs`, the one durable terminal gate. Internal whole-set
        writers keep the default and the original F-017 guarantee.
        A duplicate derived identity INSIDE the batch raises
        `DuplicateSpecError` (the dedup signal); the whole batch is validated
        before any file is written, so a rejected write never leaves a partial
        set. An identity a spec payload tries to author explicitly
        (`spec_id`) is refused: the store owns that derived symbol.

        MOVE-AWARE (the #205 rule): when an identity ALREADY lives in
        consumed/, a produced-target write is a NO-OP success returning the
        durable consumed Path. The spec is already ratified and durable there,
        and re-creating a produced/ copy would break the produced/consumed
        mutual exclusivity - the surfer's inbox would never drain and the mover
        would re-dispatch the identity every tick. A warning logs the race.

        Returns `(spec_id, written_path)` per entry, in the input order. Raises
        on a write failure - the caller degrades to a warning and keeps serving
        (O3). The whole validate-then-write runs under the project's lock (I2),
        so the duplicate/novelty checks are not TOCTOU."""
        if not isinstance(specs, Sequence) or isinstance(specs, (str, bytes)) or not specs:
            raise ValueError(
                "hunter store: a spec write needs a non-empty `specs` list "
                "(a single spec is a set of one)"
            )
        self._validate_side(side)
        self._validate_hunt_key(hunt_key)
        # S3 8.7 defines exactly two set shapes: the GENERATE write (all
        # `hypothesised`) and the terminal write (survivors `ratified`,
        # unfeasible `dropped`). A mixed set is neither exit the harness
        # tracks - it would persist while the hunt stalls - so it is refused.
        statuses = {
            spec.get("status") for spec in specs
            if isinstance(spec, dict)
        }
        if "hypothesised" in statuses and statuses & {"ratified", "dropped"}:
            raise ValueError(
                "hunter store: a spec set is either the GENERATE write (all "
                "`hypothesised`) or the terminal write (survivors `ratified`, "
                "unfeasible `dropped`); a set mixing `hypothesised` with a "
                "terminal status is not a lifecycle shape"
            )
        # Validate the WHOLE batch first: a rejected write never leaves a
        # partial set on disk.
        prepared: list[tuple[str, dict]] = []
        seen: set[str] = set()
        for spec in specs:
            if not isinstance(spec, dict):
                raise ValueError("hunter store: each spec must be a mapping")
            if spec.get("spec_id"):
                raise ValueError(
                    "hunter store: `spec_id` is a DERIVED symbol (the "
                    "<fault_keyword>_<strategy_keyword> stem); the payload must "
                    "not author it"
                )
            status = spec.get("status")
            if status not in SPEC_STATUSES:
                raise ValueError(
                    f"hunter store: each spec must carry a status in "
                    f"{SPEC_STATUSES}; got {status!r}"
                )
            discriminators = _require_discriminators(spec)
            validate_skill_concretised_procedure(
                spec.get("skill_concretised_procedure"))
            provenance = spec.get("provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            class_name = str(
                provenance.get("web_vulnerability_class")
                or provenance.get("canonical_class")
                or "")
            try:
                spec_id = spec_identifier(class_name, discriminators)
            except ValueError as exc:
                raise ValueError(f"hunter store: {exc}") from exc
            if spec_id in seen:
                raise DuplicateSpecError(
                    f"hunter store: the identity {spec_id!r} appears twice in "
                    "the spec set; the write is the deduplication signal - "
                    "merge or refresh the spec instead of duplicating it"
                )
            seen.add(spec_id)
            prepared.append((spec_id, spec))
        written: list[tuple[str, Path]] = []
        with self._lock_for(project_id):
            # The terminal set is COMPLETE: every earlier hypothesised draft is
            # either promoted or explicitly dropped. A silent omission would
            # remove a branch from the pod path with no recorded decision, which
            # is the comfyui-003 defect. The check reads the produced side
            # under the same lock as the write, so a concurrent move cannot
            # race it.
            terminal = bool(statuses) and all(
                status in ("ratified", "dropped") for status in statuses)
            if side == "produced" and terminal and enforce_complete:
                batch_runs = {
                    str((spec.get("provenance") or {}).get("run_id") or "")
                    for spec in specs
                    if isinstance(spec.get("provenance"), dict)
                }
                batch_run = (
                    next(iter(batch_runs))
                    if len(batch_runs) == 1 and next(iter(batch_runs))
                    else ""
                )
                missing: list[str] = []
                for existing in self.produced_spec_files(project_id, hunt_key):
                    if existing in seen:
                        continue
                    try:
                        body = self.read_spec(
                            project_id, hunt_key, existing, side="produced")
                    except Exception:  # noqa: BLE001 - a corrupt draft is not silently ignored
                        missing.append(existing)
                        continue
                    if not body or body.get("status") != "hypothesised":
                        continue
                    existing_run = str(
                        (body.get("provenance") or {}).get("run_id") or ""
                    )
                    if batch_run and existing_run != batch_run:
                        # a draft of another run (or a legacy draft) is not this
                        # terminal set's responsibility
                        continue
                    missing.append(existing)
                if missing:
                    raise IncompleteSpecSetError(missing, hunt_key)
            for spec_id, spec in prepared:
                path = self._spec_file(project_id, hunt_key, spec_id, side)
                consumed_path = self._spec_file(
                    project_id, hunt_key, spec_id, "consumed")
                existing_path = self._spec_file(
                    project_id, hunt_key, spec_id, "produced")
                if (side == "produced"
                        and spec.get("status") == "ratified"
                        and not existing_path.exists()
                        and not consumed_path.exists()):
                    # Identity stability: a `ratified` write may only address a
                    # slot the hunter already declared. A changed discriminator
                    # value is a new sub-slice, which must be written as
                    # `hypothesised` first - never a silent rename into a
                    # dispatchable spec. A new `dropped` identity is legal: it
                    # records a slot the hunter decided not to test.
                    raise ValueError(
                        "hunter store: the terminal status write for "
                        f"{spec_id!r} addresses no hypothesised spec; write the "
                        "new sub-slice as `hypothesised` first, or keep the "
                        "discriminator values stable")
                if side == "produced" and consumed_path.exists():
                    logger.warning(
                        "hunter store: produced write for %s skipped - the "
                        "identity already lives in consumed/ (post-move write, "
                        "#205); no produced/ copy re-created", path.name,
                    )
                    written.append((spec_id, consumed_path))
                    continue
                write_text_atomic(path, yaml.safe_dump(spec, sort_keys=False))
                written.append((spec_id, path))
        return written

    def finalize_specs(
        self,
        project_id: str,
        hunt_key: str,
        *,
        run_id: str = "",
    ) -> dict:
        """Close the hunt's spec set with a durable terminal record.

        F-025/F-022: the hunter writes one spec per call, so the whole-set
        omission check cannot live on a terminal batch write. This is the one
        gate: every produced spec must already be `ratified` or `dropped`
        (consumed specs are terminal by dispatch), then the store writes
        `test-specs/<hunt_key>/terminal.yaml` carrying the run id, the sorted
        terminal identities, and their statuses. A zero-spec hunt is a valid
        terminal set: it still needs the record, or its consumed loop would be
        recovered forever.

        Idempotent for the same run. A different run may finalize the same
        hunt key (the loop dispatch id is not globally unique across runs);
        its record replaces the stale one, and recovery compares the run id.
        """
        self._validate_hunt_key(hunt_key)
        missing: list[str] = []
        statuses: dict[str, str] = {}
        with self._lock_for(project_id):
            existing = self.read_terminal_set(project_id, hunt_key)
            if existing is not None and str(existing.get("run_id") or "") == str(
                    run_id or ""):
                return existing
            for side in _SPEC_SIDES:
                side_dir = self._spec_dir(project_id, hunt_key) / side
                if not side_dir.exists():
                    continue
                for path in sorted(side_dir.glob("*.yaml")):
                    body = self._read_spec_file(path)
                    status = str(body.get("status") or "")
                    statuses[path.stem] = status
                    if side == "produced" and status == "hypothesised":
                        missing.append(path.stem)
            if missing:
                raise IncompleteSpecSetError(missing, hunt_key)
            marker = {
                "schema_version": 1,
                "hunt_key": hunt_key,
                "run_id": str(run_id or ""),
                "status": "terminal",
                "spec_ids": sorted(statuses),
                "spec_statuses": dict(sorted(statuses.items())),
                "finalized_at": datetime.now(timezone.utc).isoformat(),
            }
            write_text_atomic(
                self._terminal_file(project_id, hunt_key),
                yaml.safe_dump(marker, sort_keys=False),
            )
            return marker

    def settle_hypothesised(
        self,
        project_id: str,
        hunt_key: str,
        *,
        run_id: str = "",
    ) -> dict:
        """Close a COMPLETE hunt: declass leftover drafts and finalize.

        The hunter's symbolic graph reaching COMPLETE is the authoritative
        end-of-work signal. Any spec still `hypothesised` at that point was
        never promoted or explicitly dropped; leaving it in produced would
        make the serial gate fail closed on a hunt the tracker has already
        completed. Declass each such spec to `dropped` with a durable reason,
        then write the terminal marker. A spec that is already `ratified` or
        `dropped` is untouched. A malformed spec raises (the gate blocks and
        the upstream write-gate ticket owns repair); no partial terminal is
        written.
        """
        self._validate_hunt_key(hunt_key)
        with self._lock_for(project_id):
            existing = self.read_terminal_set(project_id, hunt_key)
            if existing is not None and str(
                    existing.get("run_id") or "") == str(run_id or ""):
                return existing
            produced = self._spec_dir(project_id, hunt_key) / "produced"
            if produced.exists():
                for path in sorted(produced.glob("*.yaml")):
                    body = self._read_spec_file(path)
                    if str(body.get("status") or "") != "hypothesised":
                        continue
                    body["status"] = "dropped"
                    body["declassified"] = "hunter-complete"
                    write_text_atomic(path, yaml.safe_dump(body, sort_keys=False))
        return self.finalize_specs(project_id, hunt_key, run_id=run_id)

    def read_terminal_set(self, project_id: str, hunt_key: str) -> dict | None:
        """The durable terminal-set record for the hunt key, or None.

        A corrupt record raises (O4) rather than reading as absent: a false
        absence would recover a completed loop."""
        path = self._terminal_file(project_id, hunt_key)
        if not path.exists():
            return None
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(
                f"hunter store: unreadable terminal-set file {path}: {exc}"
            ) from exc
        if not isinstance(loaded, dict):
            raise OSError(
                f"hunter store: terminal-set file {path} is not a YAML mapping")
        return loaded

    def has_terminal_set(self, project_id: str, hunt_key: str) -> bool:
        return self.read_terminal_set(project_id, hunt_key) is not None

    def read_spec(
        self,
        project_id: str,
        hunt_key: str,
        spec_id: str,
        *,
        side: Literal["produced", "consumed"] = "produced",
        attributes: Sequence[str] | None = None,
    ) -> dict | None:
        """The one spec file for `(hunt_key, spec_id)`.

        `hunt_key` is the loop dispatch id (S3 8.9). `None` for a missing file
        (a valid empty result, never a failure); a corrupt file raises (O4,
        the caller degrades to an empty set). With `attributes` given, the
        returned dict is projected onto them."""
        path = self._spec_file(project_id, hunt_key, spec_id, side)
        if not path.exists():
            return None
        return self._project(self._read_spec_file(path), attributes)

    def read_spec_lenient(
        self,
        project_id: str,
        hunt_key: str,
        spec_id: str,
        *,
        side: Literal["produced", "consumed"] = "produced",
    ) -> tuple[dict | None, str]:
        """The one spec file, with a parse error instead of a raise.

        The malformed fail-safe needs the mover to ADDRESS a spec whose body it
        cannot parse, so the pod can render what is parsable and still write a
        PodExport. A missing file is `(None, "no spec file")`; a corrupt file
        is `(None, <error>)`. The caller records the anomaly and dispatches a
        degraded pod instead of halting the queue."""
        try:
            body = self.read_spec(
                project_id, hunt_key, spec_id, side=side)
        except Exception as exc:  # noqa: BLE001 - the anomaly is the result
            return None, str(exc)
        if body is None:
            return None, "no spec file"
        if not isinstance(body, dict):
            return None, f"the spec body is {type(body).__name__}, not a mapping"
        return body, ""

    def read_specs(
        self,
        project_id: str,
        hunt_key: str,
        *,
        sides: Sequence[Literal["produced", "consumed"]] = ("produced", "consumed"),
        statuses: Sequence[str] | None = None,
        attributes: Sequence[str] | None = None,
    ) -> list[dict]:
        """All spec files under `test-specs/<hunt_key>/`, in file-name order.

        `hunt_key` is the loop dispatch id (S3 8.9); the whole surface context
        is never returned through this store. `sides` selects produced/consumed
        (default both); `statuses` filters on the persisted `status`;
        `attributes` projects each spec onto the given fields. A missing
        project/hunt_key yields [] - a valid empty result, never a failure. A
        corrupt file raises (O4)."""
        out: list[dict] = []
        for side in sides:
            self._validate_side(side)
            side_dir = self._spec_dir(project_id, hunt_key) / side
            if not side_dir.exists():
                continue
            for path in sorted(side_dir.glob("*.yaml")):
                spec = self._read_spec_file(path)
                if statuses is not None and spec.get("status") not in statuses:
                    continue
                out.append(self._project(spec, attributes))
        return out

    def list_hunt_keys(self, project_id: str) -> list[str]:
        """The `test-specs/` hunt-key folders in deterministic (sorted) order -
        the loop dispatch ids the inbox surfer enumerates to read the produced
        spec surface (ADR #169 Q3/#172). A missing project contributes nothing
        (a valid empty result)."""
        tests_dir = self._project_dir(project_id) / "test-specs"
        if not tests_dir.exists():
            return []
        return sorted(child.name for child in tests_dir.iterdir() if child.is_dir())

    def produced_spec_files(self, project_id: str, hunt_key: str) -> list[str]:
        """The PRODUCED-side spec file stems under one hunt key - the
        `<fault>_<strategy>` file names the inbox surfer operates on (ADR
        #169 Q3/#172), in file-name order. `hunt_key` is the loop dispatch id
        (S3 8.9). `consumed/` contributes nothing. A missing side contributes
        nothing (a valid empty result)."""
        side_dir = self._spec_dir(project_id, hunt_key) / "produced"
        if not side_dir.exists():
            return []
        return sorted(child.stem for child in side_dir.glob("*.yaml"))

    def consumed_spec_files(self, project_id: str, hunt_key: str) -> list[str]:
        """The CONSUMED-side spec file stems under one hunt key, in file-name
        order. F-017: the mover reconciles this inventory against terminal
        PodExports on resume, so a spec admitted before a provider pause is
        re-dispatched instead of being lost. A missing side contributes
        nothing (a valid empty result)."""
        side_dir = self._spec_dir(project_id, hunt_key) / "consumed"
        if not side_dir.exists():
            return []
        return sorted(child.stem for child in side_dir.glob("*.yaml"))

    def consume_spec(self, project_id: str, hunt_key: str, spec_file: str) -> bool:
        """Move one produced spec file to consumed/ - the single-owner
        produced->consumed transition of the inbox-surfer protocol
        (ADR #169 Q3/164 spec 6, tracker #172): ONLY the mover calls this
        (the single-owner rename, #172 AC). `spec_file` is the produced spec's
        file-name identity (the `<fault>_<strategy>` stem, G3) under
        `test-specs/<hunt_key>/`; `hunt_key` is the loop dispatch id (S3 8.9).

        True when the spec now lives in consumed/ - renamed NOW, or already
        moved by an earlier tick (at-least-once: the repeated invocation of a
        confirmed move is a no-op success, never an error). False when NO such
        record exists in either side (nothing to move). Raises on a genuine
        storage failure (O3 - the caller warns and counts, never aborting the
        tick) and on an unsafe `spec_file` (a path separator or traversal
        name). Runs under the project's lock (I2), so the rename is not
        TOCTOU.

        The G4 novelty gate makes produced/ and consumed/ MUTUALLY EXCLUSIVE
        per name; a store where BOTH hold the same name is corrupted, and the
        move refuses to clobber the consumed record (at-least-once: a moved
        message is never lost to a re-write)."""
        _validate_spec_file(spec_file)
        with self._lock_for(project_id):
            spec_dir = self._spec_dir(project_id, hunt_key)
            produced = spec_dir / "produced" / f"{spec_file}.yaml"
            consumed = spec_dir / "consumed" / f"{spec_file}.yaml"
            if produced.exists() and consumed.exists():
                logger.warning(
                    "hunter store: both produced/ and consumed/ hold %s for "
                    "%s/%s; refusing to clobber the consumed record (fail-open)",
                    spec_file, project_id, hunt_key,
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
    def note_key(hunt_key: str, note_name: str) -> str:
        """The hierarchy key of a note: `hunt_key:<note_name>` (G6), where
        `hunt_key` is the loop dispatch id (S3 8.9)."""
        return f"{hunt_key}:{note_name}"

    def write_note(
        self,
        project_id: str,
        *,
        action: Literal["append", "update", "delete"] = "append",
        hunt_key: str,
        note_name: str,
        kind: str,
        body: str,
        evidence: str | None = None,
        provenance: dict | None = None,
    ) -> str | None:
        """The `notes` body write over the per-project `notes.yaml` (G6).

        `append` adds a new note for the `(hunt_key, note_name)` key, where
        `hunt_key` is the loop dispatch id (S3 8.9); `update` amends an
        existing note (replacing its kind/body/evidence/provenance); `delete`
        removes it. Returns the note `key` (`hunt_key:<note_name>`); an
        update/delete on a missing key returns `None` (a denoted miss, never a
        failure). Notes keep their natural append order - no `_seq`/`_ref`
        (G11). Raises on write failure (O3) and on an unknown `kind` or
        `action`."""
        if action not in _NOTE_ACTIONS:
            raise ValueError(f"hunter store: unknown note action {action!r}; known: {_NOTE_ACTIONS}")
        if kind not in NOTE_KINDS:
            raise ValueError(
                f"hunter store: unknown note kind {kind!r}; known: {NOTE_KINDS}"
            )
        self._validate_hunt_key(hunt_key)
        path = self._notes_file(project_id)
        records = self._read_records(path)
        key = self.note_key(hunt_key, note_name)
        if action == "append":
            records.append(
                {
                    "key": key,
                    "hunt_key": hunt_key,
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
          parent_key  - the hunt key (S3 8.9); yields that hunt's notes (the
                        note keys embed it).
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
    "DuplicateSpecError",
    "HunterMemoryStore",
    "IncompleteSpecSetError",
    "NOTE_KINDS",
    "spec_identifier",
]
