"""decision.py - the structured difference the orchestrator consumes.

A pure diff of two stack manifests plus the advance context (dev SHA, eval
SHA, all-idle). It enumerates what moved and carries each group's artifact
class verbatim; it contains no action strings, no fail-closed set, and no
per-class branch. The alignment decision belongs to the eval orchestrator
(D42) - the documented impact map is guidance it applies, not a rule encoded
here.

Orientation: an advance moves the currently-running `eval` commit forward to
`dev`, so `before` is `manifest_eval` and `after` is `manifest_dev`.
"""
from __future__ import annotations

from dataclasses import dataclass

from advance.manifest import StackManifest


@dataclass(frozen=True)
class ArtifactChange:
    """A path group whose SHA differs (or exists on only one side)."""

    name: str
    artifact_class: str
    before_sha: str | None
    after_sha: str | None


@dataclass(frozen=True)
class ImageChange:
    """A running component whose image digest differs (or exists on one side)."""

    component: str
    before_digest: str | None
    after_digest: str | None


@dataclass(frozen=True)
class ManifestDelta:
    """The manifest difference: changed groups and images, and the unchanged names."""

    changed: tuple[ArtifactChange, ...]
    unchanged: tuple[str, ...]
    images_changed: tuple[ImageChange, ...]
    images_unchanged: tuple[str, ...]


@dataclass(frozen=True)
class DecisionInput:
    """The advance context plus the manifest delta, for the orchestrator."""

    dev_sha: str
    eval_sha: str
    all_idle: bool
    delta: ManifestDelta


def build_decision_input(
    dev_sha: str,
    eval_sha: str,
    all_idle: bool,
    manifest_dev: StackManifest,
    manifest_eval: StackManifest,
) -> DecisionInput:
    """Diff `manifest_eval` (before) against `manifest_dev` (after)."""
    return DecisionInput(
        dev_sha=dev_sha,
        eval_sha=eval_sha,
        all_idle=all_idle,
        delta=_diff(manifest_eval, manifest_dev),
    )


def _diff(before: StackManifest, after: StackManifest) -> ManifestDelta:
    before_entries = {entry.name: entry for entry in before.entries}
    after_entries = {entry.name: entry for entry in after.entries}

    changed: list[ArtifactChange] = []
    unchanged: list[str] = []
    for name in sorted(before_entries.keys() | after_entries.keys()):
        old = before_entries.get(name)
        new = after_entries.get(name)
        old_sha = old.sha if old is not None else None
        new_sha = new.sha if new is not None else None
        if old_sha != new_sha:
            present = new if new is not None else old
            assert present is not None
            changed.append(
                ArtifactChange(name, present.artifact_class, old_sha, new_sha)
            )
        else:
            unchanged.append(name)

    images_changed: list[ImageChange] = []
    images_unchanged: list[str] = []
    for component in sorted(before.image_digests.keys() | after.image_digests.keys()):
        old_digest = before.image_digests.get(component)
        new_digest = after.image_digests.get(component)
        if old_digest != new_digest:
            images_changed.append(ImageChange(component, old_digest, new_digest))
        else:
            images_unchanged.append(component)

    return ManifestDelta(
        changed=tuple(changed),
        unchanged=tuple(unchanged),
        images_changed=tuple(images_changed),
        images_unchanged=tuple(images_unchanged),
    )
