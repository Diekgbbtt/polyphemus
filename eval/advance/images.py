"""images.py - the running-image digest collector for the stack manifest.

One thin, injectable seam: `collect_image_digests` runs `docker inspect` per
container and returns `{component: image digest}`. The command runner is a
parameter, so this module performs no I/O at import (CODING_STANDARD section 6)
and the unit tier never needs Docker.

The digest is the container's image ID (`{{.Image}}`), a `sha256:` content
address that identifies the image actually running regardless of its tag -
including locally rebuilt images that carry no `RepoDigests` entry.

A missing container or unparseable output is fail-closed (D37): the daemon
must not compute a manifest from a stack it cannot observe.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

from advance.effects import CommandResult, CommandRunner, run_process

# The documented running components (D39): one digest each in the manifest.
COMPONENTS: tuple[str, ...] = (
    "postgres",
    "neo4j",
    "lightrag",
    "kali",
    "litellm",
    "agent",
)

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ImageDigestError(RuntimeError):
    """A running container's image digest could not be resolved."""


def default_run(args: Sequence[str]) -> CommandResult:
    """Run `docker <args>` and capture its output."""
    return run_process(["docker", *args])


def default_containers(compose_project: str) -> dict[str, str]:
    """The stack's containers by component, named `<project>-<service>-1`.

    The eval instance compose project is `ph-<short>` (D1), so the daemon needs
    the project to name the running containers. `litellm` is not a compose
    service: it is the gateway process inside the `agent` container (D10), so it
    shares that container's running image.
    """
    containers = {
        component: f"{compose_project}-{component}-1" for component in COMPONENTS
    }
    # litellm is the gateway process inside the agent container (D10).
    containers["litellm"] = f"{compose_project}-agent-1"
    return containers


def parse_container_map(value: str | None) -> dict[str, str] | None:
    """Parse `component=container,...` into a map; `None`/empty means "use defaults"."""
    if not value:
        return None
    mapping: dict[str, str] = {}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        component, separator, container = item.partition("=")
        if not separator or not component.strip() or not container.strip():
            raise ValueError(f"invalid image-container mapping: {item!r}")
        mapping[component.strip()] = container.strip()
    return mapping or None


def collect_image_digests(
    containers: Mapping[str, str],
    *,
    run: CommandRunner = default_run,
) -> dict[str, str]:
    """Resolve each component's running image digest via `docker inspect`.

    `containers` maps a component name to the actual container name (the
    caller knows the compose project prefix). Raises `ImageDigestError` when a
    container is missing or its output is not a `sha256:` image ID.
    """
    digests: dict[str, str] = {}
    for component, container in containers.items():
        result = run(["inspect", "--format", "{{.Image}}", container])
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ImageDigestError(
                f"docker inspect failed for {component!r} ({container!r}): {detail}"
            )
        digest = result.stdout.strip()
        if not _DIGEST_RE.match(digest):
            raise ImageDigestError(
                f"unparseable image digest for {component!r} ({container!r}): "
                f"{result.stdout!r}"
            )
        digests[component] = digest
    return digests


def merge_instance_digests(
    per_instance: Mapping[str, Mapping[str, str]]
) -> dict[str, str]:
    """Merge per-instance component digests into one manifest map (I1).

    With one instance the component names stay unqualified, backward compatible
    with the single-instance manifest and fingerprint. With more than one, every
    key is `<instance_id>:<component>` so two instances' same-named components
    never collide; the sorted canonical lines then cover both stacks
    deterministically.
    """
    if len(per_instance) <= 1:
        only = next(iter(per_instance.values()), {})
        return dict(only)
    merged: dict[str, str] = {}
    for instance_id in sorted(per_instance):
        for component, digest in per_instance[instance_id].items():
            merged[f"{instance_id}:{component}"] = digest
    return merged
