"""The BenchmarkDataset: a first-class, keyed benchmark artifact (spec #301).

A benchmark dataset is declared once, in its own YAML (`eval/datasets/<id>.yaml`),
owning the attributes shared by its targets: the source repo, the image registry,
the platform root (where the per-target compose and Dockerfiles live), and the
target list.

The dataset is addressed by its `id`, and every target by the composite key
`<dataset>/<target>`. That one key indexes the target's bring-up configuration
(`eval/targets/<dataset>/<target>.yaml`), its platform bank entry
(`<platform_root>/<target>/`), and its project data dependencies
(`eval/data/<dataset>/<target>/`), so keying is consistent across every domain of
the data.

Parsing is pure (`parse_benchmark_dataset`); `load_benchmark_dataset` is the one
reading wrapper. Every field missing, mistyped, unknown, or duplicated fails loud
and names itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

DATASET_DIRNAME = "datasets"
TARGETS_DIRNAME = "targets"
PLATFORM_DIRNAME = "platform"
DATA_DIRNAME = "data"
TARGET_CONFIG_FILENAME = "target.yaml"
TARGET_KEY_SEP = "/"


class DatasetError(ValueError):
    """A BenchmarkDataset is malformed; the message names the offending field."""


def is_path_safe_id(value: object) -> bool:
    """True when `value` is one safe path segment.

    A key joins these ids into a path, so a separator or a `.`/`..` segment would
    escape its level. Shared with the setup parser so a composite key enforces the
    same rule on each of its two segments.
    """
    return (
        isinstance(value, str)
        and bool(value)
        and value not in (".", "..")
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
    )


def resolve_target_key(key: object) -> tuple[str, str]:
    """Split a `<dataset>/<target>` key into its two path-safe segments."""
    if not isinstance(key, str) or key.count(TARGET_KEY_SEP) != 1:
        raise DatasetError(
            f"target key: expected '<dataset>/<target>', got {key!r}"
        )
    dataset, target = key.split(TARGET_KEY_SEP)
    if not is_path_safe_id(dataset) or not is_path_safe_id(target):
        raise DatasetError(f"target key: expected path-safe segments, got {key!r}")
    return dataset, target


def make_target_key(dataset: str, target: str) -> str:
    """The canonical `<dataset>/<target>` key, validated."""
    return f"{dataset}{TARGET_KEY_SEP}{target}"


@dataclass(frozen=True)
class BenchmarkDataset:
    """One keyed benchmark dataset and where its artifacts live.

    `eval_root` is the `eval/` directory the dataset was loaded from; the bank and
    data-dependency paths are resolved against it. `platform_root` may be absolute
    or `~`-anchored (an external dataset checkout, used in place so its own
    scaffold such as `targetctl` keeps working), or relative to `eval_root` (a
    repo-local bank for an authored dataset).
    """

    id: str
    repo: str
    registry: str = ""
    platform_root: str = ""
    targets: tuple[str, ...] = ()
    # Services every target of this dataset keeps out of its stack (D49: the
    # WebExploitBench `evaluator`, dropped because nothing produces its input).
    # The strategy merges these with any per-target `exclude_services`.
    exclude_services: tuple[str, ...] = ()
    eval_root: Path | None = None

    # --- keying ---------------------------------------------------------------

    def key(self, target: str) -> str:
        return make_target_key(self.id, target)

    def has_target(self, target: str) -> bool:
        return target in self.targets

    def require_target(self, target: str) -> str:
        if not self.has_target(target):
            raise DatasetError(f"dataset {self.id!r} has no target {target!r}")
        return target

    # --- resolved paths -------------------------------------------------------

    def _root(self) -> Path:
        if self.eval_root is None:
            raise DatasetError(f"dataset {self.id!r} has no eval root resolved")
        return Path(self.eval_root)

    def bank_root(self) -> Path:
        """The directory holding the per-target platform bank entries."""
        if not self.platform_root:
            return self._root() / PLATFORM_DIRNAME / self.id
        candidate = Path(self.platform_root).expanduser()
        if candidate.is_absolute() or str(self.platform_root).startswith("~"):
            return candidate
        return self._root() / candidate

    def bank_entry(self, target: str) -> Path:
        return self.bank_root() / self.require_target(target)

    def target_config_path(self, target: str) -> Path:
        return (
            self._root()
            / TARGETS_DIRNAME
            / self.id
            / f"{self.require_target(target)}.yaml"
        )

    def data_dir(self, target: str) -> Path:
        return self._root() / DATA_DIRNAME / self.id / self.require_target(target)

    def target_config_search(self, target: str) -> Path:
        """The target config file, preferring the `<target>.yaml` filename."""
        explicit = self.target_config_path(target)
        if explicit.exists():
            return explicit
        return self._root() / TARGETS_DIRNAME / self.id / target / TARGET_CONFIG_FILENAME


# --- validation helpers -------------------------------------------------------


def _mapping(value: object, where: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise DatasetError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _require(mapping: Mapping, key: str, where: str) -> object:
    if key not in mapping:
        raise DatasetError(f"{where}: missing required field {key!r}")
    return mapping[key]


def _check_keys(mapping: Mapping, allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise DatasetError(f"{where}: unknown field(s): {', '.join(unknown)}")


def _str_field(mapping: Mapping, key: str, where: str, *, required: bool = False):
    if key not in mapping:
        if required:
            raise DatasetError(f"{where}: missing required field {key!r}")
        return None
    value = mapping[key]
    if not isinstance(value, str) or not value:
        raise DatasetError(f"{where}.{key}: expected a non-empty string")
    return value


def _optional_str(mapping: Mapping, key: str, where: str) -> str | None:
    if key not in mapping or mapping[key] is None:
        return None
    value = mapping[key]
    if not isinstance(value, str):
        raise DatasetError(f"{where}.{key}: expected a string or null")
    return value


def _string_tuple(mapping: Mapping, key: str, where: str) -> tuple[str, ...]:
    if key not in mapping or mapping[key] is None:
        return ()
    value = mapping[key]
    if not isinstance(value, list):
        raise DatasetError(f"{where}.{key}: expected a list of strings")
    for item in value:
        if not isinstance(item, str) or not item:
            raise DatasetError(f"{where}.{key}: expected non-empty strings, got {item!r}")
    return tuple(value)


# --- parsing ------------------------------------------------------------------


def parse_benchmark_dataset(
    payload: object, *, eval_root: Path | None = None, where: str = "BenchmarkDataset"
) -> BenchmarkDataset:
    """Validate and build a `BenchmarkDataset` from a decoded mapping."""
    root = _mapping(payload, where)
    _check_keys(
        root,
        ("id", "repo", "registry", "platform_root", "targets", "exclude_services"),
        where,
    )
    dataset_id = _str_field(root, "id", where, required=True)
    if not is_path_safe_id(dataset_id):
        raise DatasetError(f"{where}.id: expected a path-safe identifier, got {dataset_id!r}")
    repo = _str_field(root, "repo", where, required=True)
    registry = _optional_str(root, "registry", where) or ""
    platform_root = _optional_str(root, "platform_root", where) or ""
    targets = _string_tuple(root, "targets", where)
    exclude_services = _string_tuple(root, "exclude_services", where)
    for target in targets:
        if not is_path_safe_id(target):
            raise DatasetError(
                f"{where}.targets: expected path-safe identifiers, got {target!r}"
            )
    duplicates = sorted({t for t in targets if targets.count(t) > 1})
    if duplicates:
        raise DatasetError(f"{where}.targets: duplicate target(s): {', '.join(duplicates)}")
    return BenchmarkDataset(
        id=dataset_id,
        repo=repo,
        registry=registry,
        platform_root=platform_root,
        targets=targets,
        exclude_services=exclude_services,
        eval_root=eval_root,
    )


def load_benchmark_dataset(path: Path, *, eval_root: Path | None = None) -> BenchmarkDataset:
    """Read and parse a dataset YAML; a bad file names itself.

    When `eval_root` is unset it is derived from the conventional location
    `eval/datasets/<id>.yaml` (the datasets dir's parent).
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DatasetError(f"{path}: invalid YAML: {exc}") from exc
    if eval_root is None and path.parent.name == DATASET_DIRNAME:
        eval_root = path.parent.parent
    return parse_benchmark_dataset(payload, eval_root=eval_root, where=str(path))
