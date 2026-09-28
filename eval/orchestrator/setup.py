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
class TargetRun:
    """The evaluation of one `Target` on one instance: config, phase, cap, seeds."""

    target_id: str
    target_config: TargetConfig
    start_phase: str = "recon"
    hunt_config_budget: int | None = None
    preloaded_hunting_artifacts: str | None = None


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

    allowed = ("schema_version", "artifact_store", "instances", "work_items")
    _check_keys(root, allowed, "EvalSetup")

    raw_instances = _require(root, "instances", "EvalSetup")
    if not isinstance(raw_instances, list) or not raw_instances:
        raise SetupError("EvalSetup.instances: expected a non-empty list")

    instances = tuple(_parse_instance(item, i) for i, item in enumerate(raw_instances))
    ids = [i.instance_id for i in instances]
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    if duplicates:
        raise SetupError(f"EvalSetup.instances: duplicate instance_id(s): {', '.join(duplicates)}")

    work_items = tuple(_parse_work_item(item, i) for i, item in enumerate(root.get("work_items", []) or []))

    return EvalSetup(
        schema_version=_schema,
        artifact_store=artifact_store,
        instances=instances,
        work_items=work_items,
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
        ("target_id", "target_config", "start_phase", "hunt_config_budget", "preloaded_hunting_artifacts"),
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
        preloaded_hunting_artifacts=_optional_str(
            mapping, "preloaded_hunting_artifacts", where
        ),
    )


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


def load_eval_setup(path: Path) -> EvalSetup:
    """Read and parse an `EvalSetup` YAML file; a bad file names itself."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")  # FileNotFoundError carries the path
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SetupError(f"{path}: invalid YAML: {exc}") from exc
    return parse_eval_setup(payload)
