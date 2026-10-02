"""Docker image primitives: inspect, pull, build, tag, remove.

The chain provisions each target's canonical images before it starts and removes
the previous target's canonical tags when the next target begins, so peak disk is
one target at a time. Provisioning follows a strict precedence
(`provision_tags`), store first:

1. **present** (`store`) - `docker image inspect <canonical-tag>` succeeds, so the
   image is already bound and the target is left alone; a store hit is never
   pulled, rebuilt, or reclaimed by provisioning;
2. **pull** - the target declares a pull reference for that canonical tag
   (`config.pull[tag]`); it is pulled and then bound to the canonical tag with
   `docker tag`;
3. **build** - otherwise the target's own build (its compose/Dockerfile) runs and
   the produced image is bound to the canonical tag with `docker tag`.

Binding every produced image to its canonical tag is what lets the store check
and reclaim speak one symbolic key, `ph/<dataset>/<target>:<service>`, rather than
guess at the compose's own tags. Removal is best-effort: an absent or in-use image
does not abort the chain, and the outcome is reported through the returned label.

Every primitive builds a local `docker ...` command and accepts a `wrap` that
turns it into the command actually run; the default runs it as-is on the local
eval host (D45), and a wrap adds the target's platform env (D46).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from orchestrator.commands import Command, CommandRunner, require_ok

# A command wrapper: identity for local docker, ssh for a remote host. The
# primitives build a local `docker ...` command and the wrapper turns it into
# the command actually run (e.g. `ssh host docker ...`).
Wrap = Callable[[Command], Command]


def _local(command: Command) -> Command:
    return command

# The three provisioning sources, in precedence order: a store hit leaves the
# image alone, a declared pull reference fetches it, and otherwise the target's
# own build produces it.
PRESENT = "present"
PULL = "pull"
BUILD = "build"


class ImagePrimitiveError(RuntimeError):
    """A docker image primitive failed or a provisioned image could not be verified."""


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


def registry_reference(registry: str, target: str, service: str) -> str:
    """`<registry>:<target>-<service>`: the chain's pull reference for a service.

    The registry is `host/owner/repo`, one repository for every target of a
    dataset (e.g. `ghcr.io/diekgbbtt/webench`); the tag names the target and the
    service. The CI image workflow pushes each built service under exactly this
    reference, so the chain can pull instead of building on the eval host (D48).
    An empty registry yields an empty string, so the caller falls back to build.
    """
    registry = registry.strip().rstrip("/")
    if not registry:
        return ""
    return f"{registry}:{target}-{service}"


def plan_pull(reference: str) -> Command:
    """`docker pull <ref>`: fetch the image, streaming per-layer progress."""
    return Command(argv=("docker", "pull", reference), description=f"pull {reference}")


def plan_inspect(reference: str) -> Command:
    """`docker image inspect <ref>`: confirm the image is present, return its id."""
    return Command(
        argv=("docker", "image", "inspect", "--format", "{{.Id}}", reference),
        description=f"verify {reference}",
    )


def plan_tag(source: str, tag: str) -> Command:
    """`docker tag <source> <tag>`: bind a produced image to its canonical tag."""
    return Command(
        argv=("docker", "tag", source, tag),
        description=f"tag {tag}",
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


def remove(run: CommandRunner, reference: str, *, wrap: Wrap = _local) -> tuple[str, ...]:
    """Best-effort removal; the outcome is a label, never an abort."""
    command = wrap(plan_remove(reference))
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

    This is the store tier: it confirms an image carries the tag, not that it is
    the expected one. A store hit is left alone (never pulled, rebuilt, or
    reclaimed by provisioning), so the caller records the path as `present`.
    """
    result = run(wrap(plan_inspect(reference)))
    if result.returncode != 0:
        return None
    image_id = (result.stdout or "").strip()
    return image_id or None


# --- the canonical-tag provisioning precedence --------------------------------


@dataclass(frozen=True)
class ProvisionOutcome:
    """Which source provisioned one canonical tag, and what it bound it to."""

    tag: str
    source: str
    reference: str
    detail: str


BuildMapping = Callable[[], Mapping[str, str]]


def provision_tags(
    run: CommandRunner,
    tags: tuple[str, ...],
    *,
    pull_refs: Mapping[str, str] | None = None,
    build: BuildMapping | None = None,
    wrap: Wrap = _local,
    error: type[Exception] = ImagePrimitiveError,
) -> tuple[ProvisionOutcome, ...]:
    """Provision each canonical tag by the precedence: store, pull, build.

    For every tag: a local `docker image inspect` hit is `present` and left
    alone; otherwise a declared `pull_refs[tag]` reference is pulled and bound to
    the tag with `docker tag`; otherwise `build` (invoked at most once, only when
    a tag still needs it) runs the target's own build and returns the produced
    reference for each tag, which is then bound with `docker tag`. A tag that is
    absent, has no pull reference, and is not produced by the build is a hard
    failure, so the target trial fails instead of running a missing image.
    """
    outcomes: list[ProvisionOutcome] = []
    pending: list[str] = []
    for tag in tags:
        if present(run, tag, wrap=wrap) is not None:
            outcomes.append(ProvisionOutcome(tag, PRESENT, tag, f"present {tag}"))
        else:
            pending.append(tag)

    declared = dict(pull_refs or {})
    still: list[str] = []
    for tag in pending:
        reference = declared.get(tag)
        if reference is None:
            still.append(tag)
            continue
        pulled = pull(run, reference, wrap=wrap, error=error)
        _bind(run, pulled.reference, tag, wrap=wrap, error=error)
        outcomes.append(
            ProvisionOutcome(tag, PULL, pulled.reference, f"pull {pulled.reference} -> {tag}")
        )

    if still:
        produced = dict(build() if build is not None else {})
        for tag in still:
            reference = produced.get(tag)
            if reference is None:
                raise error(
                    f"image {tag!r} is not present locally, has no pull reference, "
                    "and no build produced it"
                )
            _bind(run, reference, tag, wrap=wrap, error=error)
            outcomes.append(ProvisionOutcome(tag, BUILD, reference, f"build {reference} -> {tag}"))
    return tuple(outcomes)


def _bind(
    run: CommandRunner,
    reference: str,
    tag: str,
    *,
    wrap: Wrap,
    error: type[Exception],
) -> None:
    command = wrap(plan_tag(reference, tag))
    require_ok(run(command), command, error=error)
