"""The artifact store: one-way sync rendering and the self-contained trial tree (#273).

Two layers, by design (D7/D12):

- the raw live mirror, `<store>/<instance_id>/live/`, is the secondary target of
  a strictly one-way `lsyncd` (inotify -> rsync) that streams the instance data
  root; nothing ever writes back;
- the authoritative per-trial tree, `<store>/<target_id>/<target_run_id>/<trial_id>/`,
  is assembled by the materializer: `verdicts.yaml`, `diagnoses.yaml`, the copied
  evidence chain preserving its data-root-relative structure, and
  `run-manifest.yaml`, so a finished trial is readable without the live stack.

The store is a sink: every write the materializer performs is guarded to stay
under the store root, and it only ever reads the instance data root. PyYAML is
the one third-party dependency (the repo's existing dependency); import
performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import yaml

from orchestrator import diagnosis, evidence, subagents, verdicts
from orchestrator.files import FileStore
from orchestrator.project_artifacts import (
    ProjectArtifact,
    ProjectArtifactError,
    artifact_manifest,
    collect_project_artifacts,
)
from orchestrator.project_graph import PROJECT_GRAPH_FILENAME
from orchestrator.setup import EvalSetup

LIVE_DIRNAME = "live"
SYNC_DIRNAME = "_sync"
# The materializer's scratch root: `<store>/_staging/<unique-id>`. Never
# projected as a target (see `read_api.projection.SKIP_DIRNAMES`).
STAGING_DIRNAME = "_staging"
RUN_MANIFEST = "run-manifest.yaml"
STORE_SCHEMA_VERSION = 2
# D20: only a success (`identified`) needs no diagnosis entry (the verdict
# vocabulary shared with the diagnosis pair).
DIAGNOSABLE = verdicts.DIAGNOSABLE

# The manifest keys excluded from the stable snapshot fingerprint: the two
# materialization/capture timestamps and the self-referential fingerprint.
_VOLATILE_MANIFEST_KEYS = frozenset({"copied_at", "captured_at", "snapshot_sha256"})
_SAFE_FAILURES = frozenset(
    {
        "artifact_digest_mismatch",
        "artifact_unsafe",
        "artifact_unreadable",
        "project_graph_unavailable",
        "project_graph_invalid",
        "project_snapshot_unavailable",
    }
)


class _AuxiliarySnapshotError(Exception):
    """A late graph/artifact staging or verification failure.

    Raised only by the auxiliary snapshot path; the materializer converts it to
    an unavailable snapshot and rebuilds a core-only tree. The message is a
    stable, path-free failure code.
    """

    def __init__(self, failure: str) -> None:
        super().__init__(failure)
        self.failure = failure


class StoreError(RuntimeError):
    """The store could not be rendered or a trial could not be materialized.

    `failure` is the named code the CLI and the operator act on
    (`record_missing`, `record_invalid`, `verdicts_missing`, `verdicts_invalid`,
    `diagnoses_missing`, `diagnoses_invalid`, `chain_unresolved`,
    `identity_missing`, `escape`, `sync_layout`); the message carries the path
    or verdict that failed.
    """

    def __init__(self, detail: str, *, failure: str = "store_error") -> None:
        super().__init__(f"{failure}: {detail}")
        self.failure = failure
        self.detail = detail


# --- layout -------------------------------------------------------------------


def live_mirror_dir(store: str | Path, instance_id: str) -> Path:
    """`<store>/<instance_id>/live/`: the raw secondary mirror of the data root."""
    return Path(store) / instance_id / LIVE_DIRNAME


def store_trial_dir(
    store: str | Path, target_id: str, target_run_id: str, trial_id: str
) -> Path:
    """`<store>/<target>/<target_run>/<trial>/`: the authoritative trial tree."""
    return Path(store) / target_id / target_run_id / trial_id


def instance_data_root(instances_root: str | Path, instance_id: str) -> Path:
    """`<instances_root>/<instance_id>/data`: the instance worktree's data root (D29)."""
    return Path(instances_root) / instance_id / "data"


def is_within(root: str | Path, path: str | Path) -> bool:
    """True when `path` is the root or a descendant of it (after resolving)."""
    root_resolved = Path(root).resolve()
    candidate = Path(path).resolve()
    return candidate == root_resolved or root_resolved in candidate.parents


# --- sync rendering -----------------------------------------------------------


@dataclass(frozen=True)
class SyncSpec:
    """One instance's one-way sync: its data root into the store's live dir."""

    instance_id: str
    data_root: Path
    store: Path

    @property
    def live_dir(self) -> Path:
        return live_mirror_dir(self.store, self.instance_id)

    @property
    def sync_dir(self) -> Path:
        return self.store / SYNC_DIRNAME

    @property
    def config_name(self) -> str:
        return f"eval-store-{self.instance_id}.conf"

    @property
    def unit_name(self) -> str:
        return f"eval-store-{self.instance_id}.service"

    def config_path(self, out_dir: str | Path | None = None) -> Path:
        return (Path(out_dir) if out_dir is not None else self.sync_dir) / self.config_name

    def unit_path(self, out_dir: str | Path | None = None) -> Path:
        return (Path(out_dir) if out_dir is not None else self.sync_dir) / self.unit_name


def render_lsyncd_config(spec: SyncSpec) -> str:
    """The lsyncd config: strictly source (data root) -> target (store live dir).

    `delete = false` keeps the store append-only: a deleted source file never
    removes its mirror copy, and no rule can ever name the store as a source.
    """
    _assert_one_way(spec)
    live = spec.live_dir
    return textwrap.dedent(
        f"""\
        -- Generated by `python -m orchestrator store render-sync` (#273). Do not edit.
        -- One-way mirror (D7/D12): the instance data root streams into the store.
        -- The store is a sink; nothing here writes back into the instance root.
        settings {{
            logfile = "{live}/.lsyncd.log",
            statusFile = "{live}/.lsyncd.status",
            statusInterval = 10,
        }}
        sync {{
            default.rsync,
            source = "{spec.data_root}/",
            target = "{live}/",
            delay = 1,
            delete = false,
            rsync = {{
                archive = true,
                compress = false,
            }},
        }}
        """
    )


def render_unit(spec: SyncSpec, *, out_dir: str | Path | None = None) -> str:
    """The installable systemd unit mirroring `eval/advance/systemd/` conventions."""
    _assert_one_way(spec)
    return textwrap.dedent(
        f"""\
        [Unit]
        Description=polymerhus eval artifact sync: {spec.instance_id} data root -> artifact store (one-way)
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        # One-way only (D7/D12): lsyncd streams {spec.data_root}/ into
        # {spec.live_dir}/. The store is a sink; no write path flows back.
        ExecStart=/usr/bin/lsyncd -nodaemon {spec.config_path(out_dir)}
        Restart=on-failure
        RestartSec=10
        NoNewPrivileges=true

        [Install]
        WantedBy=multi-user.target
        """
    )


@dataclass(frozen=True)
class SyncFile:
    """One rendered deploy file (an lsyncd config or a systemd unit)."""

    path: Path
    content: str


@dataclass(frozen=True)
class SyncPlan:
    """Every deploy file the `render-sync` verb emits."""

    files: tuple[SyncFile, ...]


def plan_sync(
    setup: EvalSetup,
    *,
    instances_root: str | Path,
    out_dir: str | Path | None = None,
    data_root: str | Path | None = None,
) -> SyncPlan:
    """Render one config and one unit per instance of the `EvalSetup`.

    `data_root` overrides the per-instance default
    `<instances_root>/<instance_id>/data` (useful for a single-instance host).
    """
    files: list[SyncFile] = []
    for instance in setup.instances:
        root = (
            Path(data_root)
            if data_root is not None
            else instance_data_root(instances_root, instance.instance_id)
        )
        spec = SyncSpec(
            instance_id=instance.instance_id,
            data_root=root,
            store=Path(setup.artifact_store),
        )
        _assert_one_way(spec)
        directory = Path(out_dir) if out_dir is not None else spec.sync_dir
        files.append(SyncFile(spec.config_path(directory), render_lsyncd_config(spec)))
        files.append(
            SyncFile(spec.unit_path(directory), render_unit(spec, out_dir=directory))
        )
    return SyncPlan(tuple(files))


def write_sync(plan: SyncPlan, *, files: FileStore) -> list[Path]:
    """Write every rendered deploy file atomically; return the paths written."""
    written: list[Path] = []
    for entry in plan.files:
        files.write_text_atomic(entry.path, entry.content)
        written.append(entry.path)
    return written


def _assert_one_way(spec: SyncSpec) -> None:
    """Refuse a layout where the store and the data root overlap.

    Overlap would let the mirror feed back into its own source - the one thing
    D7/D12 forbid. Both come from configuration, so this is a guard on operator
    input, not a runtime race.
    """
    for label, a, b in (
        ("data root inside the store", spec.store, spec.data_root),
        ("store inside the data root", spec.data_root, spec.store),
    ):
        if is_within(a, b) and a != b:
            raise StoreError(
                f"{label}: data_root={spec.data_root} store={spec.store}",
                failure="sync_layout",
            )


# --- materialize --------------------------------------------------------------


@dataclass(frozen=True)
class ProjectSnapshot:
    """The validated auxiliary snapshot: the captured graph plus the inventory.

    The graph and the project-artifact inventory are one unit: both are
    published, or neither is. `graph_bytes` is the exact captured file content.
    """

    available: bool
    project_id: str | None = None
    failure: str | None = None
    captured_at: str | None = None
    graph_sha256: str | None = None
    graph_node_count: int = 0
    graph_link_count: int = 0
    graph_bytes: bytes | None = None
    artifacts: tuple[ProjectArtifact, ...] = ()


def materialize(
    trial_dir: str | Path,
    *,
    store: str | Path,
    data_root: str | Path,
    files: FileStore,
    now: Callable[[], str] | None = None,
) -> Path:
    """Assemble the self-contained trial tree under the store.

    The complete tree is built under `<store>/_staging/<unique-id>` and only
    renamed into place after every applicable check passes, so a reader never
    sees a partial Trial. The first publication is immutable: an equal replay
    returns the existing tree untouched; a changed replay raises a named
    `snapshot_conflict` instead of rewriting historical evidence. Nothing under
    the instance data root is written, and no live API is ever called.
    """
    trial_dir = Path(trial_dir)
    store = Path(store)
    data_root = Path(data_root)

    record = _load_record(trial_dir / "trial.yaml", files)
    target_id = _require_str(record, "target_id", "trial record")
    trial_id = _require_str(record, "trial_id", "trial record")
    instance_id = _require_str(record, "instance_id", "trial record")
    project_id = _require_str(record, "project_id", "trial record")
    target_run_id = str(record.get("target_run_id") or instance_id)
    eval_sha = record.get("eval_sha")
    fingerprint = record.get("stack_fingerprint")
    if not eval_sha or not fingerprint:
        raise StoreError(
            "the trial record carries no eval_sha/stack_fingerprint; the store "
            "record must stay attributable",
            failure="identity_missing",
        )

    dest = store_trial_dir(store, target_id, target_run_id, trial_id)
    _guard_within(store, dest)

    # --- validate the core eval bundle (the existing rules) -------------------
    verdicts_path = trial_dir / verdicts.VERDICTS_FILENAME
    if not files.exists(verdicts_path):
        raise StoreError("verdicts.yaml not found in the trial record", failure="verdicts_missing")
    rows = _load_rows(verdicts_path, files)

    chain_sources = _chain_sources(rows)
    # Validate everything before writing anything, so a missing chain file or a
    # defective diagnosis fails cleanly instead of leaving a half-assembled
    # trial tree behind.
    for relative in chain_sources:
        _validate_chain_source(data_root, relative, files)

    diagnoses_path = trial_dir / diagnosis.DIAGNOSES_FILENAME
    diagnoses_present = files.exists(diagnoses_path)
    if diagnoses_present:
        # Validate the diagnosis before the copy: a defective or unpaired file
        # must fail loudly, never land in the authoritative tree. Pairing is
        # checked here too (load_diagnoses only validates the rows themselves),
        # so a missed/partial verdict with no entry is rejected pre-copy.
        validated = _validated_verdicts(
            rows, data_root, files, eval_sha=eval_sha, stack_fingerprint=fingerprint
        )
        try:
            entries = diagnosis.load_diagnoses(
                diagnoses_path,
                files=files,
                verdicts=validated,
                eval_sha=eval_sha,
                stack_fingerprint=fingerprint,
            )
            diagnosis.check_pairing(validated, entries)
        except (diagnosis.DiagnosisError, OSError) as exc:
            raise StoreError(str(exc), failure="diagnoses_invalid") from exc
    elif _has_diagnosable(rows):
        raise StoreError(
            "diagnoses.yaml is absent but a verdict is missed/partial",
            failure="diagnoses_missing",
        )

    # --- validate (but do not yet stage) the auxiliary project snapshot -------
    snapshot = _validate_project_snapshot(
        record, trial_dir, data_root, files, project_id=project_id
    )

    copied_at = (now or subagents.utcnow)()
    staging_root = store / STAGING_DIRNAME
    _guard_within(store, staging_root)
    staging = files.make_staging_dir(staging_root)
    try:
        try:
            snapshot_sha256 = _write_staged_trial(
                staging,
                record=record,
                chain_sources=chain_sources,
                diagnoses_present=diagnoses_present,
                verdicts_path=verdicts_path,
                diagnoses_path=diagnoses_path,
                data_root=data_root,
                files=files,
                store=store,
                project_id=project_id,
                snapshot=snapshot,
                copied_at=copied_at,
            )
            # The core self-containment check is a core error: never degraded.
            _verify_self_contained(staging, files, eval_sha, fingerprint)
            if snapshot.available:
                _verify_project_snapshot(staging, snapshot, files, project_id)
        except _AuxiliarySnapshotError as exc:
            # A late graph/artifact staging or verification failure. Discard the
            # contaminated staging tree and rebuild a core-only tree with an
            # unavailable snapshot, so the validated core eval still publishes
            # and no partial auxiliary file survives.
            files.remove_tree(staging)
            staging = files.make_staging_dir(staging_root)
            degraded = ProjectSnapshot(
                available=False, project_id=project_id, failure=exc.failure
            )
            snapshot_sha256 = _write_staged_trial(
                staging,
                record=record,
                chain_sources=chain_sources,
                diagnoses_present=diagnoses_present,
                verdicts_path=verdicts_path,
                diagnoses_path=diagnoses_path,
                data_root=data_root,
                files=files,
                store=store,
                project_id=project_id,
                snapshot=degraded,
                copied_at=copied_at,
            )
            _verify_self_contained(staging, files, eval_sha, fingerprint)

        if files.exists(dest):
            existing = _existing_snapshot_sha256(dest, files)
            if existing != snapshot_sha256:
                raise StoreError(
                    "the published trial has different bytes", failure="snapshot_conflict"
                )
            return dest
        files.publish_tree(staging, dest)
        return dest
    finally:
        files.remove_tree(staging)


def build_run_manifest(
    record: Mapping,
    chain_sources: Sequence[str],
    copied_at: str,
    *,
    diagnoses_present: bool,
    project_snapshot: ProjectSnapshot | None = None,
) -> dict:
    """The schema-v2 run manifest: pointers, provenance, and the snapshot state.

    `project_snapshot` defaults to an unavailable auxiliary snapshot, so a
    caller that has not captured a graph (the demo generator) still gets the
    three project-snapshot sections in their stable unavailable shape.
    """
    phases = record.get("phases") or []
    manifest = {
        "schema_version": STORE_SCHEMA_VERSION,
        "trial_id": record.get("trial_id"),
        "target_id": record.get("target_id"),
        "target_run_id": record.get("target_run_id") or record.get("instance_id"),
        "instance_id": record.get("instance_id"),
        "project_id": record.get("project_id"),
        "start_phase": record.get("start_phase"),
        "terminal": record.get("terminal"),
        "phases": [_phase_pointer(phase) for phase in phases if isinstance(phase, Mapping)],
        "eval_sha": record.get("eval_sha"),
        "stack_fingerprint": record.get("stack_fingerprint"),
        "chain_sources": list(chain_sources),
        "diagnoses_present": bool(diagnoses_present),
        "copied_at": copied_at,
    }
    manifest.update(_snapshot_sections(record, project_snapshot))
    return manifest


# --- internals ----------------------------------------------------------------


def _phase_pointer(phase: Mapping) -> dict:
    return {
        "phase": phase.get("phase"),
        "status": phase.get("status"),
        "run_id": phase.get("run_id"),
        # The id the phase's stop verb expects, when it differs from `run_id`
        # (analysis is keyed by the recon run id); a terminate reads it.
        "stop_run_id": phase.get("stop_run_id"),
    }


def _load_record(path: Path, files: FileStore) -> Mapping:
    if not files.exists(path):
        raise StoreError("trial record not found", failure="record_missing")
    try:
        payload = yaml.safe_load(files.read_text(path))
    except yaml.YAMLError as exc:
        raise StoreError("trial record: invalid YAML", failure="record_invalid") from exc
    if not isinstance(payload, Mapping):
        raise StoreError("trial record: expected a mapping", failure="record_invalid")
    return payload


def _load_rows(path: Path, files: FileStore) -> list:
    try:
        payload = yaml.safe_load(files.read_text(path))
    except yaml.YAMLError as exc:
        raise StoreError("verdicts.yaml: invalid YAML", failure="verdicts_invalid") from exc
    if not isinstance(payload, list):
        raise StoreError(
            "verdicts.yaml: expected a list of verdict rows", failure="verdicts_invalid"
        )
    return payload


def _validated_verdicts(
    rows: Sequence,
    data_root: Path,
    files: FileStore,
    *,
    eval_sha: str,
    stack_fingerprint: str,
) -> tuple[verdicts.Verdict, ...]:
    """Build the verdict models the diagnosis pairing validates against."""
    try:
        return verdicts.validate_verdicts(
            rows,
            data_root=data_root,
            files=files,
            eval_sha=eval_sha,
            stack_fingerprint=stack_fingerprint,
        )
    except verdicts.VerdictError as exc:
        raise StoreError(str(exc), failure="verdicts_invalid") from exc


def _chain_sources(rows: Sequence) -> list[str]:
    """Every data-root-relative chain path a set of verdict rows references."""
    paths: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise StoreError("verdict row is not a mapping", failure="chain_unresolved")
        chain = row.get("evidence_chain")
        if chain is None:
            continue
        if not isinstance(chain, Mapping):
            raise StoreError("evidence_chain is not a mapping", failure="chain_unresolved")
        for key in ("hunt_config", "spec_dir", "pod_export"):
            value = chain.get(key)
            if value:
                paths.add(str(value))
        logs = chain.get("experiment_logs") or []
        if not isinstance(logs, list):
            raise StoreError(
                "evidence_chain.experiment_logs is not a list", failure="chain_unresolved"
            )
        for log in logs:
            if log:
                paths.add(str(log))
    return sorted(paths)


def _has_diagnosable(rows: Sequence) -> bool:
    return any(
        isinstance(row, Mapping) and row.get("identified") in DIAGNOSABLE for row in rows
    )


def _validate_chain_source(data_root: Path, relative: str, files: FileStore) -> None:
    source = data_root / relative
    if Path(relative).is_absolute() or not is_within(data_root, source):
        raise StoreError(
            f"chain path {relative!r} escapes the data root", failure="chain_unresolved"
        )
    if not files.is_file(source) and not files.is_dir(source):
        raise StoreError(
            f"chain path {relative!r} does not resolve under the data root",
            failure="chain_unresolved",
        )


def _stage_chain(
    data_root: Path,
    staging: Path,
    relative: str,
    files: FileStore,
    store: Path,
    staged: set[str],
    core_paths: set[str],
) -> None:
    """Copy one evidence-chain source into staging, preserving its structure."""
    normalized = Path(relative).as_posix()
    source = data_root / normalized
    if files.is_dir(source):
        for path in files.walk_files(source):
            sub = path.relative_to(source).as_posix()
            staged_relative = f"{normalized}/{sub}"
            _stage_bytes(
                staging,
                staged_relative,
                files.read_bytes(path),
                files,
                store,
                staged,
            )
            core_paths.add(staged_relative)
        return
    _stage_bytes(staging, normalized, files.read_bytes(source), files, store, staged)
    core_paths.add(normalized)


def _verify_self_contained(dest: Path, files: FileStore, eval_sha: str, fingerprint: str) -> None:
    """Every relative path inside the copied verdicts resolves within the trial dir."""
    try:
        verdicts.load_verdicts(
            dest / verdicts.VERDICTS_FILENAME,
            files=files,
            data_root=dest,
            eval_sha=eval_sha,
            stack_fingerprint=fingerprint,
        )
    except (verdicts.VerdictError, evidence.EvidenceError) as exc:
        raise StoreError(str(exc), failure="chain_unresolved") from exc


def _require_str(record: Mapping, key: str, where: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise StoreError(f"{where}: missing required field {key!r}", failure="verdicts_missing")
    return value


def _stage_bytes(
    staging: Path,
    relative: str,
    data: bytes,
    files: FileStore,
    store: Path,
    staged: set[str],
) -> None:
    target = staging / relative
    _guard_within(store, target)
    files.write_bytes_atomic(target, data)
    staged.add(Path(relative).as_posix())


def _stage_text(staging: Path, relative: str, text: str, files: FileStore, store: Path) -> None:
    target = staging / relative
    _guard_within(store, target)
    files.write_text_atomic(target, text)


def _write_staged_trial(
    staging: Path,
    *,
    record: Mapping,
    chain_sources: Sequence[str],
    diagnoses_present: bool,
    verdicts_path: Path,
    diagnoses_path: Path,
    data_root: Path,
    files: FileStore,
    store: Path,
    project_id: str,
    snapshot: ProjectSnapshot,
    copied_at: str,
) -> str:
    """Stage one complete tree (core plus the given snapshot) and write its manifest.

    The core staging reads are not auxiliary: an OSError here propagates as a
    core failure. Only `_stage_project_snapshot`/`_verify_project_snapshot`
    raise `_AuxiliarySnapshotError`, which the caller degrades.
    """
    staged: set[str] = set()
    # Core paths and exclusively-auxiliary paths are tracked separately so a
    # fingerprint read failure can be degraded only for the latter.
    core_paths: set[str] = set()
    auxiliary_paths: set[str] = set()
    for relative in chain_sources:
        _stage_chain(data_root, staging, relative, files, store, staged, core_paths)
    _stage_bytes(
        staging,
        verdicts.VERDICTS_FILENAME,
        files.read_bytes(verdicts_path),
        files,
        store,
        staged,
    )
    core_paths.add(verdicts.VERDICTS_FILENAME)
    if diagnoses_present:
        _stage_bytes(
            staging,
            diagnosis.DIAGNOSES_FILENAME,
            files.read_bytes(diagnoses_path),
            files,
            store,
            staged,
        )
        core_paths.add(diagnosis.DIAGNOSES_FILENAME)
    if snapshot.available:
        _stage_project_snapshot(
            staging,
            snapshot,
            data_root,
            files,
            store,
            project_id,
            staged,
            auxiliary_paths,
        )

    manifest = build_run_manifest(
        record,
        chain_sources,
        copied_at,
        diagnoses_present=diagnoses_present,
        project_snapshot=snapshot,
    )
    snapshot_sha256 = _snapshot_sha256(
        staging,
        manifest,
        files,
        core_paths=core_paths,
        auxiliary_paths=auxiliary_paths,
    )
    manifest["project_snapshot"]["snapshot_sha256"] = snapshot_sha256
    manifest["project_artifacts"]["snapshot_sha256"] = snapshot_sha256
    _stage_text(
        staging, RUN_MANIFEST, yaml.safe_dump(manifest, sort_keys=False), files, store
    )
    return snapshot_sha256


def _stage_project_snapshot(
    staging: Path,
    snapshot: ProjectSnapshot,
    data_root: Path,
    files: FileStore,
    store: Path,
    project_id: str,
    staged: set[str],
    auxiliary_paths: set[str],
) -> None:
    """Stage the validated captured graph and the artifact union (deduplicated)."""
    try:
        _stage_bytes(
            staging,
            PROJECT_GRAPH_FILENAME,
            snapshot.graph_bytes or b"",
            files,
            store,
            staged,
        )
    except OSError as exc:
        raise _AuxiliarySnapshotError("project_graph_unavailable") from exc
    auxiliary_paths.add(PROJECT_GRAPH_FILENAME)
    for artifact in snapshot.artifacts:
        relative = f"{project_id}/{artifact.relative_path}"
        if relative in staged:
            # The evidence chain already copied this path; copy once.
            continue
        _stage_artifact(staging, relative, artifact, data_root, files, store, staged)
        auxiliary_paths.add(relative)


def _stage_artifact(
    staging: Path,
    relative: str,
    artifact: ProjectArtifact,
    data_root: Path,
    files: FileStore,
    store: Path,
    staged: set[str],
) -> None:
    """Copy one cataloged artifact, re-validated and digest-checked at staging time.

    The catalog read is not trusted at face value: containment, symlink status,
    and regular-file status are re-checked before the bytes are read, the read
    bytes must match the catalog digest, and the staged bytes are re-hashed.
    Every failure maps to a stable, path-free auxiliary code.
    """
    source = Path(artifact.source_path)
    if (
        not is_within(data_root, source)
        or files.is_symlink(source)
        or not files.is_file(source)
    ):
        raise _AuxiliarySnapshotError("artifact_unsafe")
    try:
        data = files.read_bytes(source)
    except OSError as exc:
        raise _AuxiliarySnapshotError("artifact_unreadable") from exc
    if hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise _AuxiliarySnapshotError("artifact_digest_mismatch")

    target = staging / relative
    if not is_within(store, target):
        raise _AuxiliarySnapshotError("artifact_unsafe")
    try:
        _stage_bytes(staging, relative, data, files, store, staged)
        staged_digest = hashlib.sha256(files.read_bytes(target)).hexdigest()
    except OSError as exc:
        raise _AuxiliarySnapshotError("artifact_unreadable") from exc
    if staged_digest != artifact.sha256:
        raise _AuxiliarySnapshotError("artifact_digest_mismatch")


# --- auxiliary project snapshot -----------------------------------------------


def _snapshot_sections(record: Mapping, snapshot: ProjectSnapshot | None) -> dict:
    """The three project-snapshot manifest sections.

    Available only when the graph capture and the artifact inventory are both
    valid and share one `captured_at`; otherwise all three are unavailable and
    carry one stable, path-free failure code.
    """
    project_id = record.get("project_id")
    if snapshot is not None and snapshot.available:
        return {
            "project_snapshot": {
                "status": "available",
                "project_id": project_id,
                "captured_at": snapshot.captured_at,
                "snapshot_sha256": None,
            },
            "project_artifacts": artifact_manifest(
                snapshot.artifacts,
                project_id=project_id,
                captured_at=snapshot.captured_at,
                snapshot_sha256=None,
            ),
            "project_graph": {
                "status": "available",
                "project_id": project_id,
                "captured_at": snapshot.captured_at,
                "sha256": snapshot.graph_sha256,
                "node_count": snapshot.graph_node_count,
                "link_count": snapshot.graph_link_count,
            },
        }
    failure = (
        snapshot.failure if snapshot is not None and snapshot.failure else None
    ) or "project_snapshot_unavailable"
    return {
        "project_snapshot": {
            "status": "unavailable",
            "project_id": project_id,
            "failure": failure,
        },
        "project_artifacts": {
            "status": "unavailable",
            "project_id": project_id,
            "failure": failure,
            "entries": [],
        },
        "project_graph": {
            "status": "unavailable",
            "project_id": project_id,
            "failure": failure,
        },
    }


def _validate_project_snapshot(
    record: Mapping,
    trial_dir: Path,
    data_root: Path,
    files: FileStore,
    *,
    project_id: str,
) -> ProjectSnapshot:
    """Validate the recorded graph capture plus the artifact allowlist.

    The graph and the artifact inventory are one unit: a graph problem or an
    unsafe artifact tree yields an unavailable snapshot, never a partial graph
    or a usable inventory. No live API is consulted.
    """
    graph_meta = record.get("project_graph")
    if not isinstance(graph_meta, Mapping) or graph_meta.get("status") != "available":
        recorded = graph_meta.get("failure") if isinstance(graph_meta, Mapping) else None
        failure = _safe_failure(recorded) or "project_graph_unavailable"
        return ProjectSnapshot(available=False, project_id=project_id, failure=failure)

    captured_at = graph_meta.get("captured_at")
    recorded_sha = graph_meta.get("sha256")
    if not isinstance(captured_at, str) or not captured_at:
        return ProjectSnapshot(
            available=False, project_id=project_id, failure="project_graph_invalid"
        )
    if not isinstance(recorded_sha, str) or not recorded_sha:
        return ProjectSnapshot(
            available=False, project_id=project_id, failure="project_graph_invalid"
        )

    graph_path = trial_dir / PROJECT_GRAPH_FILENAME
    if files.is_symlink(graph_path) or not files.is_file(graph_path):
        return ProjectSnapshot(
            available=False, project_id=project_id, failure="project_graph_invalid"
        )
    try:
        graph_bytes = files.read_bytes(graph_path)
    except OSError:
        return ProjectSnapshot(
            available=False, project_id=project_id, failure="project_graph_unavailable"
        )
    if hashlib.sha256(graph_bytes).hexdigest() != recorded_sha:
        return ProjectSnapshot(
            available=False, project_id=project_id, failure="project_graph_invalid"
        )
    try:
        graph = json.loads(graph_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ProjectSnapshot(
            available=False, project_id=project_id, failure="project_graph_invalid"
        )
    if not isinstance(graph, Mapping) or graph.get("project_id") != project_id:
        return ProjectSnapshot(
            available=False, project_id=project_id, failure="project_graph_invalid"
        )

    try:
        artifacts = collect_project_artifacts(data_root, project_id, files=files)
    except ProjectArtifactError as exc:
        failure = _safe_failure(exc.failure) or "artifact_unsafe"
        return ProjectSnapshot(available=False, project_id=project_id, failure=failure)
    except OSError:
        return ProjectSnapshot(
            available=False, project_id=project_id, failure="artifact_unreadable"
        )

    nodes = graph.get("nodes")
    links = graph.get("links")
    return ProjectSnapshot(
        available=True,
        project_id=project_id,
        captured_at=captured_at,
        graph_sha256=recorded_sha,
        graph_node_count=len(nodes) if isinstance(nodes, list) else 0,
        graph_link_count=len(links) if isinstance(links, list) else 0,
        graph_bytes=graph_bytes,
        artifacts=artifacts,
    )


def _verify_project_snapshot(
    staging: Path, snapshot: ProjectSnapshot, files: FileStore, project_id: str
) -> None:
    """Re-check the staged graph and artifact digests before publication."""
    graph_target = staging / PROJECT_GRAPH_FILENAME
    if files.is_symlink(graph_target) or not files.is_file(graph_target):
        raise _AuxiliarySnapshotError("project_graph_invalid")
    try:
        graph_digest = hashlib.sha256(files.read_bytes(graph_target)).hexdigest()
    except OSError as exc:
        raise _AuxiliarySnapshotError("project_graph_unavailable") from exc
    if graph_digest != snapshot.graph_sha256:
        raise _AuxiliarySnapshotError("project_graph_invalid")
    for artifact in snapshot.artifacts:
        relative = f"{project_id}/{artifact.relative_path}"
        target = staging / relative
        if not files.is_file(target):
            raise _AuxiliarySnapshotError("artifact_unsafe")
        try:
            staged_digest = hashlib.sha256(files.read_bytes(target)).hexdigest()
        except OSError as exc:
            raise _AuxiliarySnapshotError("artifact_unreadable") from exc
        if staged_digest != artifact.sha256:
            raise _AuxiliarySnapshotError("artifact_digest_mismatch")


# --- the stable snapshot fingerprint ------------------------------------------


def _snapshot_sha256(
    staging: Path,
    manifest: Mapping,
    files: FileStore,
    *,
    core_paths: set[str] | frozenset[str] = frozenset(),
    auxiliary_paths: set[str] | frozenset[str] = frozenset(),
) -> str:
    """The time-independent fingerprint of the complete staged Trial payload.

    Sorted relative path + content digest of every non-manifest file, plus the
    canonical manifest payload with `copied_at`, `captured_at`, and
    `snapshot_sha256` removed, so identical inputs fingerprint equally across
    rematerializations and there is no self-referential digest.

    A read failure is degraded to an auxiliary failure only when the path is
    exclusively auxiliary (the captured graph or a non-evidence artifact). A
    core path - including one shared with the evidence chain - re-raises, so a
    core read failure is never mistaken for a degraded snapshot.
    """
    staged_files: list[list[str]] = []
    for path in sorted(Path(staging).rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(staging).as_posix()
        if relative == RUN_MANIFEST:
            continue
        try:
            data = files.read_bytes(path)
        except OSError as exc:
            if relative in auxiliary_paths and relative not in core_paths:
                code = (
                    "project_graph_unavailable"
                    if relative == PROJECT_GRAPH_FILENAME
                    else "artifact_unreadable"
                )
                raise _AuxiliarySnapshotError(code) from exc
            raise
        staged_files.append([relative, hashlib.sha256(data).hexdigest()])
    payload = {"files": staged_files, "manifest": _strip_volatile(manifest)}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strip_volatile(value: object) -> object:
    """Recursively drop the manifest keys excluded from the fingerprint."""
    if isinstance(value, Mapping):
        return {
            key: _strip_volatile(item)
            for key, item in value.items()
            if key not in _VOLATILE_MANIFEST_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _existing_snapshot_sha256(dest: Path, files: FileStore) -> str | None:
    """The published tree's schema-v2 fingerprint, or None when it has none."""
    manifest_path = dest / RUN_MANIFEST
    if not files.is_file(manifest_path):
        return None
    try:
        payload = yaml.safe_load(files.read_text(manifest_path))
    except (OSError, yaml.YAMLError):
        return None
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != STORE_SCHEMA_VERSION
    ):
        return None
    section = payload.get("project_snapshot")
    if not isinstance(section, Mapping):
        return None
    value = section.get("snapshot_sha256")
    return value if isinstance(value, str) and value else None


def _safe_failure(code: object) -> str | None:
    """A recognized, path-free failure code, or None."""
    return code if isinstance(code, str) and code in _SAFE_FAILURES else None


def _guard_within(store: Path, path: Path) -> None:
    if not is_within(store, path):
        raise StoreError("refusing to write outside the store root", failure="escape")
