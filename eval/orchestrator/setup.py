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

SCHEMA_VERSION = 1

LIFECYCLES = ("targetctl", "image", "compose")
PHASES = ("recon", "analysis", "hunting")
WORK_ITEM_STATUSES = ("complete", "pending", "incomplete")

# Strategy parameters each lifecycle accepts; the required subset is enforced
# below. Keeping this a single constant means validation and the operator
# manual cannot drift.
LIFECYCLE_PARAMS: Mapping[str, tuple[str, ...]] = {
    "targetctl": (
        "target",
        "ssh_host",
        "remote_dir",
        "repo_url",
        "nginx_conf_dir",
        "ready_retries",
        "ready_interval_s",
    ),
    "image": ("image", "port", "internal_port", "name", "ready_path"),
    "compose": ("compose_file", "port", "project", "cwd", "ready_path"),
}
REQUIRED_LIFECYCLE_PARAMS: Mapping[str, tuple[str, ...]] = {
    "targetctl": ("target",),
    "image": ("image", "port"),
    "compose": ("compose_file", "port"),
}


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
class TargetConfig:
    """The linked configuration of a `Target` (lifecycle, seed, KB, auth, L1)."""

    lifecycle: str
    params: Mapping[str, object] = field(default_factory=dict)
    target_seed: str | None = None
    operator_kb: str | None = None
    auth: Mapping[str, object] | None = None
    l1_surface: Mapping[str, object] | None = None


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
class TargetRun:
    """The evaluation of one `Target` on one instance: config, phase, cap, seeds."""

    target_id: str
    target_config: TargetConfig
    start_phase: str = "recon"
    hunt_config_budget: int | None = None
    preloaded_hunting_artifacts: PreloadedArtifacts | None = None
    # #273: the target-run identity (the artifact store's middle level). Unset
    # means the trial record defaults it to the instance id.
    target_run_id: str | None = None


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

    allowed = ("schema_version", "artifact_store", "instances", "work_items", "alignment")
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

    work_items = tuple(_parse_work_item(item, i) for i, item in enumerate(root.get("work_items", []) or []))

    return EvalSetup(
        schema_version=_schema,
        artifact_store=artifact_store,
        instances=instances,
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
            "target_id",
            "target_config",
            "start_phase",
            "hunt_config_budget",
            "preloaded_hunting_artifacts",
            "target_run_id",
        ),
        where,
    )
    target_id = _str_field(mapping, "target_id", where, required=True)
    target_config = _parse_target_config(_require(mapping, "target_config", where), f"{where}.target_config")

    start_phase = mapping.get("start_phase", "recon")
    if start_phase not in PHASES:
        raise SetupError(
            f"{where}.start_phase: expected one of {', '.join(PHASES)}, got {start_phase!r}"
        )

    budget = mapping.get("hunt_config_budget")
    if budget is not None and (not isinstance(budget, int) or isinstance(budget, bool)):
        raise SetupError(f"{where}.hunt_config_budget: expected an integer or null")

    return TargetRun(
        target_id=target_id,
        target_config=target_config,
        start_phase=start_phase,
        hunt_config_budget=budget,
        preloaded_hunting_artifacts=_parse_preloaded_artifacts(
            mapping.get("preloaded_hunting_artifacts"),
            f"{where}.preloaded_hunting_artifacts",
        ),
        target_run_id=_path_safe(mapping, "target_run_id", where),
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
    mapping = _mapping(payload, where)
    _check_keys(
        mapping,
        ("lifecycle", "params", "target_seed", "operator_kb", "auth", "l1_surface"),
        where,
    )
    lifecycle = _require(mapping, "lifecycle", where)
    if lifecycle not in LIFECYCLES:
        raise SetupError(
            f"{where}.lifecycle: expected one of {', '.join(LIFECYCLES)}, got {lifecycle!r}"
        )

    params = mapping.get("params", {}) or {}
    params = _mapping(params, f"{where}.params")
    _check_keys(params, LIFECYCLE_PARAMS[lifecycle], f"{where}.params")
    for required in REQUIRED_LIFECYCLE_PARAMS[lifecycle]:
        if required not in params:
            raise SetupError(
                f"{where}.params: missing required strategy parameter {required!r} "
                f"for lifecycle {lifecycle!r}"
            )

    auth = _maybe_mapping(mapping, "auth", where)
    l1_surface = _maybe_mapping(mapping, "l1_surface", where)
    return TargetConfig(
        lifecycle=lifecycle,
        params=dict(params),
        target_seed=_optional_str(mapping, "target_seed", where),
        operator_kb=_optional_str(mapping, "operator_kb", where),
        auth=auth,
        l1_surface=l1_surface,
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
