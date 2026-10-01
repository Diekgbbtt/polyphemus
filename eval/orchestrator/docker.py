"""Docker image primitives: build, pull, present, remove.

The chain provisions each target's image before it starts and removes the
previous target's image when the next target begins, so peak disk is one target
at a time. Provisioning follows a strict precedence (`provision_images`):

1. **build** - a Dockerfile declared in the target's configuration builds the
   app image, overwriting any pull; the Dockerfile's `FROM` supplies its base;
2. **pull** - a configured dataset registry pulls the image (qualified by the
   registry host + URL path prefix, and verified present);
3. **present** - with neither, the image must already be present locally, and a
   missing image is a hard failure so the target trial fails and the chain moves
   on.

A pull is monitored through its own progress output (per-layer completion and
the manifest digest) and confirmed with `docker image inspect`; a build is
confirmed the same way; a present image is confirmed by tag only, so it is
recorded as the weakest, unverified tier. Removal is best-effort: an absent or
in-use image does not abort the chain, and the outcome is reported through the
returned label.

Every primitive builds a local `docker ...` command and accepts a `wrap` that
turns it into the command actually run (`ssh host docker ...` for the remote
workshop host).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from orchestrator.commands import Command, CommandRunner, require_ok

# A command wrapper: identity for local docker, ssh for a remote host. The
# primitives build a local `docker ...` command and the wrapper turns it into
# the command actually run (e.g. `ssh host docker ...`).
Wrap = Callable[[Command], Command]


def _local(command: Command) -> Command:
    return command

# The three provisioning paths, in precedence order: a declared Dockerfile
# builds (overwriting a pull), a configured registry pulls, and otherwise the
# image must already be present locally.
BUILD = "build"
PULL = "pull"
PRESENT = "present"


class ImagePrimitiveError(RuntimeError):
    """A docker image primitive failed or a pulled image could not be verified."""


def pull_reference(registry: str, image: str) -> str:
    """Join a dataset registry (host[/path]) with a target image identifier.

    An empty registry leaves the identifier untouched, so a target that names a
    fully-qualified reference still pulls as-is.
    """
    registry = registry.strip().rstrip("/")
    image = image.strip()
    if not registry:
        return image
    return f"{registry}/{image.lstrip('/')}"


def plan_pull(reference: str) -> Command:
    """`docker pull <ref>`: fetch the image, streaming per-layer progress."""
    return Command(argv=("docker", "pull", reference), description=f"pull {reference}")


def plan_inspect(reference: str) -> Command:
    """`docker image inspect <ref>`: confirm the image is present, return its id."""
    return Command(
        argv=("docker", "image", "inspect", "--format", "{{.Id}}", reference),
        description=f"verify {reference}",
    )


def plan_remove(reference: str) -> Command:
    """`docker image rm <ref>`: remove the image, keeping shared base layers."""
    return Command(
        argv=("docker", "image", "rm", reference),
        description=f"rm image {reference}",
    )


_DIGEST_RE = re.compile(r"Digest:\s*(sha256:[0-9a-f]{64})")
_LAYER_RE = re.compile(
    r"^(?P<id>[0-9a-f]{12}):\s*(?P<status>Pull complete|Download complete|Already exists)\b",
    re.MULTILINE,
)


def parse_pulled_digest(output: str) -> str | None:
    """The manifest digest `docker pull` reports, or None when absent."""
    match = _DIGEST_RE.search(output or "")
    return match.group(1) if match else None


def parse_completed_layers(output: str) -> tuple[str, ...]:
    """The layer ids `docker pull` reports as present/complete, in order."""
    return tuple(match.group("id") for match in _LAYER_RE.finditer(output or ""))


@dataclass(frozen=True)
class PullOutcome:
    """The verified result of one pull: what is now present on the host."""

    reference: str
    image_id: str
    digest: str | None
    layers: tuple[str, ...]


def pull(
    run: CommandRunner,
    reference: str,
    *,
    wrap: Wrap = _local,
    error: type[Exception] = ImagePrimitiveError,
) -> PullOutcome:
    """Pull `reference`, then verify the image is present; raise otherwise.

    The pull is monitored through its own progress output (per-layer completion
    and the manifest digest), and the image is confirmed with `docker image
    inspect`, so the outcome always names an image that is actually there.
    """
    pull_command = wrap(plan_pull(reference))
    result = require_ok(run(pull_command), pull_command, error=error)
    inspect_command = wrap(plan_inspect(reference))
    inspected = require_ok(run(inspect_command), inspect_command, error=error)
    image_id = (inspected.stdout or "").strip()
    if not image_id:
        raise error(f"pulled image {reference!r} has no image id (inspect returned nothing)")
    output = f"{result.stdout}\n{result.stderr}"
    return PullOutcome(
        reference=reference,
        image_id=image_id,
        digest=parse_pulled_digest(output),
        layers=parse_completed_layers(output),
    )


def remove(run: CommandRunner, reference: str) -> tuple[str, ...]:
    """Best-effort removal; the outcome is a label, never an abort."""
    command = plan_remove(reference)
    result = run(command)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return (f"reclaim {reference} failed: {detail}",)
    return (f"rm {reference}",)


# --- build --------------------------------------------------------------------


def plan_build(reference: str, *, dockerfile: str, context: str) -> Command:
    """`docker build -t <ref> -f <dockerfile> <context>`: build the app image.

    The reference is the target's own image identifier (as-is), so the built
    image carries the tag the target's lifecycle expects; the Dockerfile's
    `FROM` pulls its base.
    """
    return Command(
        argv=("docker", "build", "-t", reference, "-f", dockerfile, context),
        description=f"build {reference} from {dockerfile}",
    )


def build(
    run: CommandRunner,
    reference: str,
    *,
    dockerfile: str,
    context: str | None = None,
    wrap: Wrap = _local,
    error: type[Exception] = ImagePrimitiveError,
) -> PullOutcome:
    """Build `reference` from `dockerfile`, then verify the image is present.

    `context` defaults to the Dockerfile's own parent directory, which is only
    correct when the Dockerfile copies nothing from a wider tree; the caller
    should pass the real context for a `COPY`-bearing Dockerfile.
    """
    context = context or str(Path(dockerfile).parent)
    command = wrap(plan_build(reference, dockerfile=dockerfile, context=context))
    require_ok(run(command), command, error=error)
    inspect = wrap(plan_inspect(reference))
    inspected = require_ok(run(inspect), inspect, error=error)
    image_id = (inspected.stdout or "").strip()
    if not image_id:
        raise error(f"built image {reference!r} has no image id (inspect returned nothing)")
    return PullOutcome(reference=reference, image_id=image_id, digest=None, layers=())


def present(run: CommandRunner, reference: str, *, wrap: Wrap = _local) -> str | None:
    """The local image id when `reference` is already present, else None.

    This is the weakest tier: it confirms an image carries the tag, not that it
    is the expected one. A tag can point at a stale or foreign image, so the
    caller records the path as `present` (unverified) rather than as a pull.
    """
    result = run(wrap(plan_inspect(reference)))
    if result.returncode != 0:
        return None
    image_id = (result.stdout or "").strip()
    return image_id or None


# --- the provisioning precedence ----------------------------------------------


@dataclass(frozen=True)
class ProvisionOutcome:
    """Which path provisioned one image, and what it left on the host."""

    reference: str
    path: str
    image_id: str
    detail: str


def provisioned_references(
    images: tuple[str, ...], *, dockerfile: str | None = None, registry: str = ""
) -> tuple[str, ...]:
    """The local image names the precedence would leave, for a later reclaim.

    Mirrors `provision_images`: the first image is the Dockerfile's local tag,
    a configured registry qualifies every other image, and otherwise the images
    keep their bare identifier. Reclaim removes exactly these names.
    """
    references: list[str] = []
    for index, image in enumerate(images):
        if index == 0 and dockerfile:
            references.append(image)
        elif registry:
            references.append(pull_reference(registry, image))
        else:
            references.append(image)
    return tuple(references)


def provision_images(
    run: CommandRunner,
    images: tuple[str, ...],
    *,
    dockerfile: str | None = None,
    context: str | None = None,
    registry: str = "",
    wrap: Wrap = _local,
    error: type[Exception] = ImagePrimitiveError,
) -> tuple[ProvisionOutcome, ...]:
    """Provision a target's images by the precedence: build, then pull, then present.

    * a declared `dockerfile` builds the target's **app image** (the first
      identifier), overwriting any pull; the Dockerfile's `FROM` supplies its
      base;
    * a configured `registry` pulls each remaining image (qualified by the
      registry, verified present);
    * with neither, every image must already be present locally, and a missing
      one is a hard failure (`error`), so the target trial fails and the chain
      moves on.
    """
    outcomes: list[ProvisionOutcome] = []
    for index, image in enumerate(images):
        if index == 0 and dockerfile:
            built = build(
                run, image, dockerfile=dockerfile, context=context, wrap=wrap, error=error
            )
            outcomes.append(
                ProvisionOutcome(image, BUILD, built.image_id, f"build {image} from {dockerfile}")
            )
        elif registry:
            reference = pull_reference(registry, image)
            pulled = pull(run, reference, wrap=wrap, error=error)
            outcomes.append(
                ProvisionOutcome(reference, PULL, pulled.image_id, f"pull {reference}")
            )
        else:
            image_id = present(run, image, wrap=wrap)
            if image_id is None:
                raise error(
                    f"image {image!r} is not present locally and no dockerfile or "
                    "registry is configured"
                )
            outcomes.append(
                ProvisionOutcome(image, PRESENT, image_id, f"present {image}")
            )
    return tuple(outcomes)
