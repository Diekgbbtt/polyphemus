"""fingerprint.py - the single compressed hash over a stack manifest.

One sha256 over the canonical, sorted manifest lines. Canonical means the
lines are independent of the dict/tuple ordering the manifest happens to
carry; the commit field is provenance and is deliberately excluded, so a
commit that only touched unrelated files keeps the same fingerprint while any
artifact SHA or running image digest change moves it.
"""
from __future__ import annotations

import hashlib

from advance.manifest import StackManifest


def canonical_lines(manifest: StackManifest) -> list[str]:
    """The manifest as sorted, tab-separated lines: artifacts then images."""
    lines = [
        f"artifact\t{entry.name}\t{entry.artifact_class}\t{entry.sha}"
        for entry in sorted(manifest.entries, key=lambda entry: entry.name)
    ]
    lines.extend(
        f"image\t{name}\t{manifest.image_digests[name]}"
        for name in sorted(manifest.image_digests)
    )
    return lines


def fingerprint(manifest: StackManifest) -> str:
    """The stack fingerprint: one sha256 hex digest over the canonical lines."""
    payload = "\n".join(canonical_lines(manifest))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
