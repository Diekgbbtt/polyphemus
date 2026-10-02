"""The per-dataset helper: the one authority that turns a target's compose into
its images, and that owns the dataset's named readiness checkers (spec #301).

The generic helper derives the target's own images from the services that declare
both `build:` and `image:` in the compose - the same rule `targetctl` uses - so the
image set can never drift from what the target actually builds. Each derived image
is bound to a canonical tag `ph/<dataset>/<target>:<service>`, which is the
symbolic key the store check and reclaim use.

A dataset may supply its own helper module (`orchestrator/datasets/<id>.py`) to add
named readiness checkers; otherwise the generic helper applies.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from orchestrator.commands import Command
from orchestrator.dataset import BenchmarkDataset
from orchestrator.readiness import ReadinessPlan, plan_compose_health
from orchestrator.target_config import TargetConfiguration

DEFAULT_READY_RETRIES = 60
DEFAULT_READY_INTERVAL_S = 5.0


@dataclass(frozen=True)
class BuiltImage:
    """One image a target's compose builds: its service and its compose tag."""

    service: str
    reference: str


def parse_built_images(compose_text: str) -> tuple[BuiltImage, ...]:
    """The services declaring both `build:` and `image:`, mirroring `targetctl`.

    The parse is deliberately shallow (a compose-service block is a two-space key
    under `services:`), so it reads the same shape `targetctl`'s `build_images`
    awk reads and needs no YAML dependency.
    """
    images: list[BuiltImage] = []
    service: str | None = None
    has_build = False
    image: str | None = None

    def flush() -> None:
        if service and has_build and image:
            images.append(BuiltImage(service=service, reference=image))

    for raw in compose_text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 2 and stripped.endswith(":") and " " not in stripped[:-1]:
            flush()
            service = stripped[:-1]
            has_build = False
            image = None
            continue
        if service is None:
            continue
        if indent == 4 and stripped.startswith("build:"):
            has_build = True
        elif indent == 4 and stripped.startswith("image:"):
            image = stripped[len("image:"):].strip().strip("\"'")
    flush()
    seen: list[BuiltImage] = []
    for item in images:
        if item not in seen:
            seen.append(item)
    return tuple(seen)


def canonical_tag(dataset_id: str, target: str, service: str) -> str:
    """`ph/<dataset>/<target>:<service>`, the symbolic image key for a target."""
    return f"ph/{dataset_id}/{target}:{service}"


class DatasetHelper:
    """The generic, compose-derived helper for a benchmark dataset."""

    def __init__(self, dataset: BenchmarkDataset) -> None:
        self.dataset = dataset

    # --- paths ----------------------------------------------------------------

    def bank_entry(self, target: str) -> Path:
        return self.dataset.bank_entry(target)

    def compose_path(self, target: str, config: TargetConfiguration) -> Path:
        """The compose file, resolved against the target's bank entry."""
        if not config.compose:
            raise ValueError(f"target {target!r} declares no compose file")
        return self.bank_entry(target) / config.compose

    # --- images ---------------------------------------------------------------

    def built_images(self, target: str, config: TargetConfiguration) -> tuple[BuiltImage, ...]:
        path = self.compose_path(target, config)
        built = parse_built_images(path.read_text(encoding="utf-8"))
        # D49: a service kept out of the stack is not a built image of the target,
        # so it is never tagged, pulled, or reclaimed. The dataset's exclusions
        # (the `evaluator`) merge with any the target itself declares.
        excluded = set(self.dataset.exclude_services) | set(config.exclude_services)
        if not excluded:
            return built
        return tuple(item for item in built if item.service not in excluded)

    def canonical_tags(self, target: str, config: TargetConfiguration) -> tuple[str, ...]:
        """The target's own canonical tags; config.images overrides the derivation."""
        if config.images:
            return tuple(config.images)
        built = self.built_images(target, config)
        return tuple(
            canonical_tag(self.dataset.id, target, item.service) for item in built
        )

    # --- readiness ------------------------------------------------------------

    def readiness_plan(
        self,
        target: str,
        config: TargetConfiguration,
        *,
        project: str,
        port: int | str | None = None,
        host: str | None = None,
        retries: int = DEFAULT_READY_RETRIES,
        interval_s: float = DEFAULT_READY_INTERVAL_S,
    ) -> ReadinessPlan:
        """The bounded readiness plan; compose health by default.

        A named `checker` is resolved to this dataset's own checker when it
        defines one; otherwise the default compose-health poll applies.
        """
        named = self._named_checker(config.checker) if config.checker else None
        if named is not None:
            return named(
                target, config, project=project, port=port, host=host,
                retries=retries, interval_s=interval_s,
            )
        if config.runner in ("targetctl", "compose") and config.compose:
            compose_file = str(self.compose_path(target, config))
            return ReadinessPlan(
                probe=plan_compose_health(compose_file, project),
                retries=retries,
                interval_s=interval_s,
                kind="compose",
            )
        # The image runner (and any target with no compose) probes its port.
        probe = Command(
            argv=(
                "curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                "--max-time", "10", f"http://127.0.0.1:{port}{config.ready_path}",
            ),
            description=f"probe {host or target}",
        )
        return ReadinessPlan(probe=probe, retries=retries, interval_s=interval_s, kind="http")

    def _named_checker(self, name: str):
        checker = getattr(self, f"checker_{name}", None)
        return checker if callable(checker) else None


def helper_for(dataset: BenchmarkDataset) -> DatasetHelper:
    """The helper for a dataset: its own module when present, else the generic one."""
    try:
        module = importlib.import_module(f"orchestrator.datasets.{dataset.id}")
    except ModuleNotFoundError:
        return DatasetHelper(dataset)
    factory = getattr(module, "helper", None)
    return factory(dataset) if callable(factory) else DatasetHelper(dataset)
