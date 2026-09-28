"""Unit tests for the eval image-digest collector (`eval/advance/images.py`).

The collector shells out to `docker inspect` to learn the digest of each
running image; the command runner is injected here so the tests never touch
Docker. A missing container and unparseable inspect output are both
fail-closed: the stack manifest cannot be trusted from an incomplete stack
(R16, D37's fail-closed default under uncertainty).
"""
from __future__ import annotations

import pytest

from advance import images

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def result(returncode: int = 0, stdout: str = "", stderr: str = "") -> images.CommandResult:
    return images.CommandResult(returncode, stdout, stderr)


def test_present_containers_resolve_to_their_running_digest() -> None:
    seen: list[list[str]] = []

    def run(args):
        seen.append(list(args))
        return result(stdout={"c-agent": DIGEST_A, "c-kali": DIGEST_B}[args[-1]] + "\n")

    digests = images.collect_image_digests({"agent": "c-agent", "kali": "c-kali"}, run=run)

    assert digests == {"agent": DIGEST_A, "kali": DIGEST_B}
    assert seen[0] == ["inspect", "--format", "{{.Image}}", "c-agent"]
    assert seen[1] == ["inspect", "--format", "{{.Image}}", "c-kali"]


def test_missing_container_fails_closed() -> None:
    def run(args):
        return result(returncode=1, stderr=f"No such object: {args[-1]}")

    with pytest.raises(images.ImageDigestError, match="c-agent"):
        images.collect_image_digests({"agent": "c-agent"}, run=run)


def test_unparseable_output_fails_closed() -> None:
    def run(args):
        return result(stdout="not-a-digest\n")

    with pytest.raises(images.ImageDigestError, match="agent"):
        images.collect_image_digests({"agent": "c-agent"}, run=run)


def test_empty_output_fails_closed() -> None:
    def run(args):
        return result(stdout="")

    with pytest.raises(images.ImageDigestError, match="agent"):
        images.collect_image_digests({"agent": "c-agent"}, run=run)


def test_every_documented_component_has_a_collector_slot() -> None:
    assert images.COMPONENTS == (
        "postgres",
        "neo4j",
        "lightrag",
        "kali",
        "litellm",
        "agent",
    )
