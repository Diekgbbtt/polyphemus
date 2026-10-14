"""Unit tests for the eval stack fingerprint (`eval/advance/fingerprint.py`).

The fingerprint is one compressed hash over the canonical, sorted manifest
lines: stable when nothing alignment-relevant moved (including a commit that
only touched unrelated files), and sensitive to any artifact SHA or running
image digest.
"""
from __future__ import annotations

import re

from advance import fingerprint, manifest

HEX64 = re.compile(r"^[0-9a-f]{64}$")
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def make(
    *,
    commit: str = "c0",
    src_sha: str = "src0",
    env_sha: str = "env0",
    digest: str = DIGEST_A,
    order: tuple[str, ...] = ("src", "env_schema"),
) -> manifest.StackManifest:
    entries = {
        "src": manifest.ManifestEntry("src", "agent_code", src_sha),
        "env_schema": manifest.ManifestEntry("env_schema", "config_schema", env_sha),
    }
    return manifest.StackManifest(
        commit=commit,
        entries=tuple(entries[name] for name in order),
        image_digests={"agent": digest},
    )


def test_identical_manifests_have_identical_fingerprints() -> None:
    assert fingerprint.fingerprint(make()) == fingerprint.fingerprint(make())


def test_artifact_change_changes_the_fingerprint() -> None:
    assert fingerprint.fingerprint(make()) != fingerprint.fingerprint(make(src_sha="src1"))


def test_one_byte_change_in_an_alignment_artifact_changes_it() -> None:
    assert fingerprint.fingerprint(make(env_sha="env0")) != fingerprint.fingerprint(
        make(env_sha="env1")
    )


def test_changed_image_digest_changes_the_fingerprint() -> None:
    assert fingerprint.fingerprint(make(digest=DIGEST_A)) != fingerprint.fingerprint(
        make(digest=DIGEST_B)
    )


def test_input_ordering_does_not_matter() -> None:
    a = make(order=("src", "env_schema"))
    b = make(order=("env_schema", "src"))
    assert fingerprint.fingerprint(a) == fingerprint.fingerprint(b)


def test_commit_metadata_is_not_part_of_the_fingerprint() -> None:
    # A commit that only touched unrelated files keeps the same manifest, so
    # the fingerprint must not move either (the commit field is provenance).
    assert fingerprint.fingerprint(make(commit="c0")) == fingerprint.fingerprint(
        make(commit="c1")
    )


def test_fingerprint_is_a_sha256_hex_digest() -> None:
    assert HEX64.match(fingerprint.fingerprint(make()))


def test_canonical_lines_are_sorted_artifact_then_image() -> None:
    lines = fingerprint.canonical_lines(make())
    assert lines == [
        "artifact\tenv_schema\tconfig_schema\tenv0",
        "artifact\tsrc\tagent_code\tsrc0",
        "image\tagent\t" + DIGEST_A,
    ]
