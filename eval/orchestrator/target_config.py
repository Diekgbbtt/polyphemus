"""The TargetConfiguration: everything needed to bring one target up (spec #301).

One file per target, `eval/targets/<dataset>/<target>.yaml`, owning the bring-up
attributes: the compose file (relative to the target's platform bank entry), the
canonical image tags, the registry pull references, the optional named readiness
checker, and the `reclaimable` opt-in. The image set may be omitted and derived
from the compose by the dataset helper.

Parsing is pure (`parse_target_configuration`); `load_target_configuration` is the
one reading wrapper. Every field missing, mistyped, unknown, or duplicated fails
loud and names itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

from orchestrator.dataset import DatasetError, is_path_safe_id

RUNNERS = ("targetctl", "compose", "image")
# Per-runner required fields; the union is validated against the runner.
REQUIRED_FIELDS: Mapping[str, tuple[str, ...]] = {
    "targetctl": ("compose",),
    "compose": ("compose", "port"),
    "image": ("image", "port"),
}
KNOWN_FIELDS = (
    "target",
    "runner",
    "compose",
    "image",
    "port",
    "internal_port",
    "ready_path",
    "platform",
    "project",
    "cwd",
    "name",
    "images",
    "pull",
    "checker",
    "ready_retries",
    "ready_interval_s",
    "reclaimable",
    "exclude_services",
)


class TargetConfigError(DatasetError):
    """A TargetConfiguration is malformed; the message names the offending field."""


@dataclass(frozen=True)
class TargetConfiguration:
    """The bring-up configuration of one target, keyed by `<dataset>/<target>`."""

    target: str
    runner: str = "compose"
    compose: str | None = None
    image: str | None = None
    port: int | None = None
    internal_port: int = 80
    ready_path: str = "/"
    platform: str = ""
    project: str | None = None
    cwd: str | None = None
    name: str | None = None
    # The target's own canonical image tags (`ph/<dataset>/<target>[:<service>]`).
    # Empty means the dataset helper derives them from the compose.
    images: tuple[str, ...] = ()
    # canonical tag -> registry reference, for the pre-pull fallback.
    pull: Mapping[str, str] = field(default_factory=dict)
    # A named readiness checker in the dataset helper; None defaults to the
    # compose's own healthchecks, read non-blockingly.
    checker: str | None = None
    # Per-target readiness window overrides; None keeps the orchestrator default
    # (60 retries x 5s). A slow target (a JVM under emulation, a large stack)
    # raises these so its own healthcheck has time to pass (D48).
    ready_retries: int | None = None
    ready_interval_s: float | None = None
    # Opt-in removal of the target's own canonical-tagged images after teardown
    # (and after a failed up). Default false: images persist.
    reclaimable: bool = False
    # Services kept out of the target's stack (D49: the WebExploitBench
    # `evaluator`). The targetctl strategy renders these behind a Compose
    # `profiles` gate, so `up` never starts them without editing the frozen
    # upstream compose. Empty means every service starts.
    exclude_services: tuple[str, ...] = ()


def _mapping(value: object, where: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise TargetConfigError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _require(mapping: Mapping, key: str, where: str) -> object:
    if key not in mapping:
        raise TargetConfigError(f"{where}: missing required field {key!r}")
    return mapping[key]


def _check_keys(mapping: Mapping, allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise TargetConfigError(f"{where}: unknown field(s): {', '.join(unknown)}")


def _str_field(mapping: Mapping, key: str, where: str, *, required: bool = False):
    if key not in mapping:
        if required:
            raise TargetConfigError(f"{where}: missing required field {key!r}")
        return None
    value = mapping[key]
    if not isinstance(value, str) or not value:
        raise TargetConfigError(f"{where}.{key}: expected a non-empty string")
    return value


def _optional_str(mapping: Mapping, key: str, where: str) -> str | None:
    if key not in mapping or mapping[key] is None:
        return None
    value = mapping[key]
    if not isinstance(value, str):
        raise TargetConfigError(f"{where}.{key}: expected a string or null")
    return value


def _int_field(mapping: Mapping, key: str, where: str, *, default=None):
    if key not in mapping or mapping[key] is None:
        return default
    value = mapping[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TargetConfigError(f"{where}.{key}: expected an integer")
    return value


def _float_field(mapping: Mapping, key: str, where: str, *, default=None):
    if key not in mapping or mapping[key] is None:
        return default
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TargetConfigError(f"{where}.{key}: expected a number")
    return float(value)


def _bool_field(mapping: Mapping, key: str, where: str, *, default: bool = False) -> bool:
    if key not in mapping or mapping[key] is None:
        return default
    value = mapping[key]
    if not isinstance(value, bool):
        raise TargetConfigError(f"{where}.{key}: expected a boolean")
    return value


def _string_tuple(mapping: Mapping, key: str, where: str) -> tuple[str, ...]:
    if key not in mapping or mapping[key] is None:
        return ()
    value = mapping[key]
    if not isinstance(value, list):
        raise TargetConfigError(f"{where}.{key}: expected a list of strings")
    for item in value:
        if not isinstance(item, str) or not item:
            raise TargetConfigError(f"{where}.{key}: expected non-empty strings, got {item!r}")
    return tuple(value)


def _string_map(mapping: Mapping, key: str, where: str) -> Mapping[str, str]:
    if key not in mapping or mapping[key] is None:
        return {}
    value = mapping[key]
    if not isinstance(value, Mapping):
        raise TargetConfigError(f"{where}.{key}: expected a mapping of tag -> reference")
    result: dict[str, str] = {}
    for tag, ref in value.items():
        if not isinstance(tag, str) or not tag or not isinstance(ref, str) or not ref:
            raise TargetConfigError(
                f"{where}.{key}: every entry must map a non-empty tag to a non-empty reference"
            )
        result[tag] = ref
    return result


def parse_target_configuration(
    payload: object, *, where: str = "TargetConfiguration"
) -> TargetConfiguration:
    """Validate and build a `TargetConfiguration` from a decoded mapping."""
    root = _mapping(payload, where)
    _check_keys(root, KNOWN_FIELDS, where)

    target = _str_field(root, "target", where, required=True)
    if not is_path_safe_id(target):
        raise TargetConfigError(f"{where}.target: expected a path-safe identifier, got {target!r}")

    runner = _str_field(root, "runner", where) or "compose"
    if runner not in RUNNERS:
        raise TargetConfigError(
            f"{where}.runner: expected one of {', '.join(RUNNERS)}, got {runner!r}"
        )
    for required in REQUIRED_FIELDS[runner]:
        if root.get(required) is None:
            raise TargetConfigError(
                f"{where}: runner {runner!r} requires field {required!r}"
            )

    config = TargetConfiguration(
        target=target,
        runner=runner,
        compose=_optional_str(root, "compose", where),
        image=_optional_str(root, "image", where),
        port=_int_field(root, "port", where),
        internal_port=_int_field(root, "internal_port", where, default=80),
        ready_path=_optional_str(root, "ready_path", where) or "/",
        platform=_optional_str(root, "platform", where) or "",
        project=_optional_str(root, "project", where),
        cwd=_optional_str(root, "cwd", where),
        name=_optional_str(root, "name", where),
        images=_string_tuple(root, "images", where),
        pull=_string_map(root, "pull", where),
        checker=_optional_str(root, "checker", where),
        ready_retries=_int_field(root, "ready_retries", where),
        ready_interval_s=_float_field(root, "ready_interval_s", where),
        reclaimable=_bool_field(root, "reclaimable", where, default=False),
        exclude_services=_string_tuple(root, "exclude_services", where),
    )
    return config


def load_target_configuration(path: Path) -> TargetConfiguration:
    """Read and parse a target config YAML; a bad file names itself."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TargetConfigError(f"{path}: invalid YAML: {exc}") from exc
    return parse_target_configuration(payload, where=str(path))
