"""`EvalSetup`: the root configuration of one evaluation (N1, D4, D14).

The shape follows `docs/design/eval-harness-multi-instance-solution.md`
section 5: schema version, instances (each with a serial target pipeline and a
manually managed `.env`), the durable artifact store, and the eval-wide work
items (D14). Every field missing, mistyped, unknown, or duplicated fails loud
and names itself - a silently empty eval is not an acceptable outcome.

Parsing is pure (`parse_eval_setup`) so the unit tier needs no filesystem;
`load_eval_setup` is the one reading wrapper.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

from orchestrator.dataset import resolve_target_key

SCHEMA_VERSION = 1

PHASES = ("recon", "analysis", "hunting")
WORK_ITEM_STATUSES = ("complete", "pending", "incomplete")


class SetupError(ValueError):
    """The EvalSetup is malformed; the message names the offending field."""


@dataclass(frozen=True)
class DeclaredMigration:
    """A migration command declared for one artifact class (#274, D37).

    The alignment executor never invents a migration: the decider may name an
    artifact class, and the command is resolved from this declaration. No
    declaration for a touched class is a fact the decider sees, and an
    unalignable jump is escalated and held.
    """

    artifact_class: str
    command: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class DeclaredRebuild:
    """A rebuild recipe declared for one artifact class (#274, D37)."""

    artifact_class: str
    image: str
    command: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class AlignmentDeclarations:
    """The per-artifact-class migrations and rebuilds a setup declares (D37)."""

    migrations: tuple[DeclaredMigration, ...] = ()
    rebuilds: tuple[DeclaredRebuild, ...] = ()


@dataclass(frozen=True)
class WorkItem:
    """One eval-wide pre-eval dependency (auth bootstrap, L1 surface, artifacts)."""

    name: str
    status: str = "incomplete"
    required: bool = True


@dataclass(frozen=True)
class PreloadedTestSpec:
    """One pre-mined hunter `TestImplementationSpec` and its fault-key family.

    `path` is a host path (a spec file, or a directory of them); `fault_key` is
    the `<fault_key>/` directory under `hunting/hunter/test-specs/` whose
    produced/ inbox the pipeline's lazy read drains.
    """

    path: str
    fault_key: str


@dataclass(frozen=True)
class PreloadedArtifacts:
    """Operator-supplied pre-mined hunting artifacts (#270 AC4).

    `configs` is the former single-path form: a host path to a hunt config or a
    directory of them, placed into the hunt-config `produced/` inbox. Each
    `test_specs` entry names one spec and its fault key, placed into that
    family's `produced/` inbox. Both are the pipeline's own lazy-read locations,
    so the normal mover consumes them and the cap counts them.
    """

    configs: str | None = None
    test_specs: tuple[PreloadedTestSpec, ...] = ()


@dataclass(frozen=True)
class TargetConfig:
    """The per-trial data configuration of a Target (seed, KB, data dir).

    The bring-up configuration lives separately, in the target's
    `eval/targets/<dataset>/<target>.yaml` (spec #301); this object carries only
    the per-trial data dependencies, which default to the target's
    `eval/data/<dataset>/<target>/` directory when unset.

    `data_dir` is the host directory holding the pre-built data dependencies
    (`auth/overview.yaml`, `auth/credentials.yaml`, `skills/authn/`, and
    `operator_kb.md`); the harness places them through the multipart endpoints.
    It defaults to `operator_kb`'s parent directory when unset. The retired
    inline `auth` / `l1_surface` mappings are no longer accepted.
    """

    target_seed: str | None = None
    operator_kb: str | None = None
    data_dir: str | None = None


@dataclass(frozen=True)
class TargetRun:
    """The evaluation of one `<dataset>/<target>` on one instance (spec #301).

    `target_key` is the composite dataset/target reference; `target_id` is the
    trial identity used by the artifact store and the CLI, defaulting to the
    target segment. The bring-up configuration and the dataset are resolved from
    the key.
    """

    target_key: str
    target_id: str
    target_config: TargetConfig = field(default_factory=TargetConfig)
    start_phase: str = "recon"
    # The per-trial bound on the project's token spend (spec token tracking).
    token_budget: int | None = None
    preloaded_hunting_artifacts: PreloadedArtifacts | None = None
    # #273: the target-run identity (the artifact store's middle level). Unset
    # means the trial record defaults it to the instance id.
    target_run_id: str | None = None
    # #277: reuse a pre-recon'd project (L0/L1 already transferred onto the
    # instance) instead of creating one. Set means the trial enters at hunting;
    # it must be path-safe and unique within the setup.
    existing_project_id: str | None = None

    @property
    def dataset_id(self) -> str:
        return self.target_key.split("/", 1)[0]

    @property
    def target(self) -> str:
        return self.target_key.split("/", 1)[1]


@dataclass(frozen=True)
class Instance:
    """One `PolyphemusInstance`: its identity, `.env`, and serial target pipeline."""

    instance_id: str
    targets: tuple[TargetRun, ...]
    env_file: str | None = None
    systems: str | None = None


@dataclass(frozen=True)
class EvalSetup:
    """One evaluation: instances, their targets, the artifact store, work items."""

    schema_version: int
    artifact_store: str
    instances: tuple[Instance, ...]
    # The benchmark datasets in play, by key (`eval/datasets/<key>.yaml`). Each
    # target's `target_key` names one of these plus its target (spec #301).
    datasets: tuple[str, ...] = ()
    work_items: tuple[WorkItem, ...] = ()
    # #274: declared per-artifact-class migrations/rebuilds the alignment step
    # resolves a decider's action against. Absent means nothing is declared.
    alignment: AlignmentDeclarations | None = None


# --- validation helpers -------------------------------------------------------


def _mapping(value: object, where: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise SetupError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _require(mapping: Mapping, key: str, where: str) -> object:
    if key not in mapping:
        raise SetupError(f"{where}: missing required field {key!r}")
    return mapping[key]


def _check_keys(mapping: Mapping, allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise SetupError(f"{where}: unknown field(s): {', '.join(unknown)}")


def _str_field(mapping: Mapping, key: str, where: str, *, required: bool = False):
    if key not in mapping:
        if required:
            raise SetupError(f"{where}: missing required field {key!r}")
        return None
    value = mapping[key]
    if not isinstance(value, str) or not value:
        raise SetupError(f"{where}.{key}: expected a non-empty string")
    return value


def _optional_str(mapping: Mapping, key: str, where: str) -> str | None:
    if key not in mapping or mapping[key] is None:
        return None
    value = mapping[key]
    if not isinstance(value, str):
        raise SetupError(f"{where}.{key}: expected a string or null")
    return value


def _string_tuple(mapping: Mapping, key: str, where: str) -> tuple[str, ...]:
    """A list of non-empty strings; absent is the empty tuple."""
    if key not in mapping or mapping[key] is None:
        return ()
    value = mapping[key]
    if not isinstance(value, list):
        raise SetupError(f"{where}.{key}: expected a list of strings")
    for item in value:
        if not isinstance(item, str) or not item:
            raise SetupError(f"{where}.{key}: expected non-empty strings, got {item!r}")
    return tuple(value)


def is_path_safe_id(value: object) -> bool:
    """True when `value` is one safe path segment.

    A store/trial directory joins these ids into a path, so a separator or a
    `.`/`..` segment would escape its level. Shared with the CLI so a
    `--target-run-id` override enforces the same rule as the setup file.
    """
    return (
        isinstance(value, str)
        and bool(value)
        and value not in (".", "..")
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
    )


def _path_safe(mapping: Mapping, key: str, where: str) -> str | None:
    value = _optional_str(mapping, key, where)
    if value is not None and not is_path_safe_id(value):
        raise SetupError(f"{where}.{key}: expected a path-safe identifier, got {value!r}")
    return value


# --- parsing ------------------------------------------------------------------


def parse_eval_setup(payload: object) -> EvalSetup:
    """Validate and build an `EvalSetup` from a decoded mapping."""
    root = _mapping(payload, "EvalSetup")

    _schema = _require(root, "schema_version", "EvalSetup")
    if not isinstance(_schema, int) or isinstance(_schema, bool):
        raise SetupError("EvalSetup.schema_version: expected an integer")
    if _schema != SCHEMA_VERSION:
        raise SetupError(
            f"EvalSetup.schema_version: unsupported version {_schema!r} "
            f"(expected {SCHEMA_VERSION})"
        )

    artifact_store = _str_field(root, "artifact_store", "EvalSetup", required=True)

    allowed = (
        "schema_version",
        "artifact_store",
        "datasets",
        "instances",
        "work_items",
        "alignment",
    )
    _check_keys(root, allowed, "EvalSetup")

    raw_instances = _require(root, "instances", "EvalSetup")
    if not isinstance(raw_instances, list) or not raw_instances:
        raise SetupError("EvalSetup.instances: expected a non-empty list")

    instances = tuple(_parse_instance(item, i) for i, item in enumerate(raw_instances))
    ids = [i.instance_id for i in instances]
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    if duplicates:
        raise SetupError(f"EvalSetup.instances: duplicate instance_id(s): {', '.join(duplicates)}")

    # #273: an explicit target-run identity is the artifact store's middle
    # level, so two of them in one setup would merge two target-runs' trees.
    run_ids = [t.target_run_id for i in instances for t in i.targets if t.target_run_id]
    run_duplicates = sorted({x for x in run_ids if run_ids.count(x) > 1})
    if run_duplicates:
        raise SetupError(
            "EvalSetup.instances[].targets: duplicate target_run_id(s): "
            + ", ".join(run_duplicates)
        )

    # #277: two targets reusing the same pre-recon'd project would race on one
    # project and data root; the seeded project is unique within the setup.
    seeded_ids = [
        t.existing_project_id for i in instances for t in i.targets if t.existing_project_id
    ]
    seeded_duplicates = sorted({x for x in seeded_ids if seeded_ids.count(x) > 1})
    if seeded_duplicates:
        raise SetupError(
            "EvalSetup.instances[].targets: duplicate existing_project_id(s): "
            + ", ".join(seeded_duplicates)
        )

    work_items = tuple(_parse_work_item(item, i) for i, item in enumerate(root.get("work_items", []) or []))

    datasets = _string_tuple(root, "datasets", "EvalSetup")
    for dataset in datasets:
        if not is_path_safe_id(dataset):
            raise SetupError(
                f"EvalSetup.datasets: expected path-safe identifiers, got {dataset!r}"
            )

    return EvalSetup(
        schema_version=_schema,
        artifact_store=artifact_store,
        instances=instances,
        datasets=datasets,
        work_items=work_items,
        alignment=_parse_alignment(root.get("alignment"), "EvalSetup.alignment"),
    )


def _parse_instance(payload: object, index: int) -> Instance:
    where = f"EvalSetup.instances[{index}]"
    mapping = _mapping(payload, where)
    _check_keys(mapping, ("instance_id", "env_file", "systems", "targets"), where)
    instance_id = _str_field(mapping, "instance_id", where, required=True)

    raw_targets = _require(mapping, "targets", where)
    if not isinstance(raw_targets, list) or not raw_targets:
        raise SetupError(f"{where}.targets: expected a non-empty list")
    targets = tuple(_parse_target_run(item, f"{where}.targets[{i}]") for i, item in enumerate(raw_targets))
    target_ids = [t.target_id for t in targets]
    duplicates = sorted({x for x in target_ids if target_ids.count(x) > 1})
    if duplicates:
        raise SetupError(f"{where}.targets: duplicate target_id(s): {', '.join(duplicates)}")

    return Instance(
        instance_id=instance_id,
        targets=targets,
        env_file=_optional_str(mapping, "env_file", where),
        systems=_optional_str(mapping, "systems", where),
    )


def _parse_target_run(payload: object, where: str) -> TargetRun:
    mapping = _mapping(payload, where)
    _check_keys(
        mapping,
        (
            "target_key",
            "target_id",
            "target_config",
            "start_phase",
            "token_budget",
            "preloaded_hunting_artifacts",
            "target_run_id",
            "existing_project_id",
        ),
        where,
    )
    target_key = _str_field(mapping, "target_key", where, required=True)
    dataset_id, target = resolve_target_key(target_key)
    target_id = _optional_str(mapping, "target_id", where) or target
    if not is_path_safe_id(target_id):
        raise SetupError(f"{where}.target_id: expected a path-safe identifier, got {target_id!r}")
    target_config = _parse_target_config(mapping.get("target_config"), f"{where}.target_config")

    existing_project_id = _path_safe(mapping, "existing_project_id", where)
    raw_start_phase = mapping.get("start_phase")
    if existing_project_id is not None:
        # #277: reusing a project starts at hunting by construction; an explicit
        # contradictory phase is refused, never silently overridden.
        if raw_start_phase is not None and raw_start_phase != "hunting":
            raise SetupError(
                f"{where}.start_phase: a target reusing an existing project must "
                f"start at 'hunting', got {raw_start_phase!r}"
            )
        start_phase = "hunting"
    else:
        start_phase = raw_start_phase if raw_start_phase is not None else "recon"
        if start_phase not in PHASES:
            raise SetupError(
                f"{where}.start_phase: expected one of {', '.join(PHASES)}, got {start_phase!r}"
            )

    token_budget = mapping.get("token_budget")
    if token_budget is not None and (
        not isinstance(token_budget, int) or isinstance(token_budget, bool)
    ):
        raise SetupError(f"{where}.token_budget: expected an integer or null")

    return TargetRun(
        target_key=target_key,
        target_id=target_id,
        target_config=target_config,
        start_phase=start_phase,
        token_budget=token_budget,
        preloaded_hunting_artifacts=_parse_preloaded_artifacts(
            mapping.get("preloaded_hunting_artifacts"),
            f"{where}.preloaded_hunting_artifacts",
        ),
        target_run_id=_path_safe(mapping, "target_run_id", where),
        existing_project_id=existing_project_id,
    )


def _parse_preloaded_artifacts(payload: object, where: str) -> PreloadedArtifacts | None:
    """Validate the pre-mined artifact configuration (#270 AC4).

    A bare string is the legacy configs-only form. The mapping form carries
    `configs` and/or `test_specs`; every test-spec entry names its `fault_key`
    so the spec lands in the right `<fault_key>/produced/` inbox. A missing or
    unknown field, a missing fault key, or an unsafe fault key fails loud.
    """
    if payload is None:
        return None
    if isinstance(payload, str):
        if not payload:
            raise SetupError(f"{where}: expected a non-empty string")
        return PreloadedArtifacts(configs=payload)

    mapping = _mapping(payload, where)
    _check_keys(mapping, ("configs", "test_specs"), where)
    configs = _optional_str(mapping, "configs", where)
    raw_specs = mapping.get("test_specs") or []
    if not isinstance(raw_specs, list):
        raise SetupError(f"{where}.test_specs: expected a list")
    test_specs = tuple(
        _parse_preloaded_test_spec(item, f"{where}.test_specs[{i}]")
        for i, item in enumerate(raw_specs)
    )
    if configs is None and not test_specs:
        raise SetupError(f"{where}: expected at least one of 'configs' or 'test_specs'")
    return PreloadedArtifacts(configs=configs, test_specs=test_specs)


def _parse_preloaded_test_spec(payload: object, where: str) -> PreloadedTestSpec:
    mapping = _mapping(payload, where)
    _check_keys(mapping, ("path", "fault_key"), where)
    path = _str_field(mapping, "path", where, required=True)
    fault_key = _str_field(mapping, "fault_key", where, required=True)
    if not is_path_safe_id(fault_key):
        raise SetupError(
            f"{where}.fault_key: expected a path-safe identifier, got {fault_key!r}"
        )
    return PreloadedTestSpec(path=path, fault_key=fault_key)


def _parse_target_config(payload: object, where: str) -> TargetConfig:
    """The per-trial data configuration (spec #301); all fields optional.

    The bring-up configuration is not here: it lives in the target's
    `eval/targets/<dataset>/<target>.yaml`. This object carries only per-trial
    data dependencies, which default to the target's data directory.
    """
    if payload is None:
        return TargetConfig()
    mapping = _mapping(payload, where)
    _check_keys(mapping, ("target_seed", "operator_kb", "data_dir"), where)
    return TargetConfig(
        target_seed=_optional_str(mapping, "target_seed", where),
        operator_kb=_optional_str(mapping, "operator_kb", where),
        data_dir=_optional_str(mapping, "data_dir", where),
    )


def _maybe_mapping(mapping: Mapping, key: str, where: str):
    value = mapping.get(key)
    if value is None:
        return None
    return dict(_mapping(value, f"{where}.{key}"))


def _parse_work_item(payload: object, index: int) -> WorkItem:
    where = f"EvalSetup.work_items[{index}]"
    mapping = _mapping(payload, where)
    _check_keys(mapping, ("name", "status", "required"), where)
    name = _str_field(mapping, "name", where, required=True)

    status = mapping.get("status", "incomplete")
    if status not in WORK_ITEM_STATUSES:
        raise SetupError(
            f"{where}.status: expected one of {', '.join(WORK_ITEM_STATUSES)}, got {status!r}"
        )
    required = mapping.get("required", True)
    if not isinstance(required, bool):
        raise SetupError(f"{where}.required: expected a boolean")
    return WorkItem(name=name, status=status, required=required)


def _command_list(mapping: Mapping, where: str) -> tuple[str, ...]:
    """A non-empty list of non-empty strings: the declared command argv."""
    raw = _require(mapping, "command", where)
    if not isinstance(raw, list) or not raw:
        raise SetupError(f"{where}.command: expected a non-empty list")
    parts: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise SetupError(f"{where}.command: every element must be a non-empty string")
        parts.append(item)
    return tuple(parts)


def _parse_alignment(payload: object, where: str) -> AlignmentDeclarations | None:
    """Validate the per-artifact-class migration/rebuild declarations (#274)."""
    if payload is None:
        return None
    mapping = _mapping(payload, where)
    _check_keys(mapping, ("migrations", "rebuilds"), where)

    raw_migrations = mapping.get("migrations") or []
    if not isinstance(raw_migrations, list):
        raise SetupError(f"{where}.migrations: expected a list")
    migrations = tuple(
        _parse_declared_migration(item, f"{where}.migrations[{i}]")
        for i, item in enumerate(raw_migrations)
    )

    raw_rebuilds = mapping.get("rebuilds") or []
    if not isinstance(raw_rebuilds, list):
        raise SetupError(f"{where}.rebuilds: expected a list")
    rebuilds = tuple(
        _parse_declared_rebuild(item, f"{where}.rebuilds[{i}]")
        for i, item in enumerate(raw_rebuilds)
    )

    if not migrations and not rebuilds:
        raise SetupError(f"{where}: expected at least one of 'migrations' or 'rebuilds'")
    return AlignmentDeclarations(migrations=migrations, rebuilds=rebuilds)


def _parse_declared_migration(payload: object, where: str) -> DeclaredMigration:
    mapping = _mapping(payload, where)
    _check_keys(mapping, ("artifact_class", "command", "reason"), where)
    artifact_class = _str_field(mapping, "artifact_class", where, required=True)
    return DeclaredMigration(
        artifact_class=artifact_class,
        command=_command_list(mapping, where),
        reason=_optional_str(mapping, "reason", where) or "",
    )


def _parse_declared_rebuild(payload: object, where: str) -> DeclaredRebuild:
    mapping = _mapping(payload, where)
    _check_keys(mapping, ("artifact_class", "image", "command", "reason"), where)
    artifact_class = _str_field(mapping, "artifact_class", where, required=True)
    image = _str_field(mapping, "image", where, required=True)
    return DeclaredRebuild(
        artifact_class=artifact_class,
        image=image,
        command=_command_list(mapping, where),
        reason=_optional_str(mapping, "reason", where) or "",
    )


def load_eval_setup(path: Path) -> EvalSetup:
    """Read and parse an `EvalSetup` YAML file; a bad file names itself."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")  # FileNotFoundError carries the path
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SetupError(f"{path}: invalid YAML: {exc}") from exc
    return parse_eval_setup(payload)
