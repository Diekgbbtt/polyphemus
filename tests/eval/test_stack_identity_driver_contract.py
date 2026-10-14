"""The operator driver's stack-identity contract.

The production eval drivers compute a trial's stack fingerprint with a one-line
python call:

    from advance import fingerprint, images, manifest
    m = manifest.build_manifest(repo, sha, images.collect_image_digests(
        images.default_containers(compose_project)))
    print(fingerprint.fingerprint(m))

The version-jump daemon removal (c97750a) emptied `eval/advance/`, so that
import raised `ImportError`; the drivers redirect stderr, so
`EVAL_STACK_FINGERPRINT` went empty and the trial record's `stack_fingerprint`
was blank. This test pins the public import surface and the non-empty
fingerprint the trial record needs, so the same collateral break cannot recur
silently.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from advance import fingerprint, images, manifest


def test_driver_import_path_is_public() -> None:
    """The exact names the operator one-liner imports must stay importable."""
    assert callable(fingerprint.fingerprint)
    assert callable(manifest.build_manifest)
    assert callable(images.collect_image_digests)
    assert callable(images.default_containers)


def test_driver_fingerprint_is_non_empty(tmp_path: Path) -> None:
    """The git-backed call the driver makes yields a real 64-hex fingerprint."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "kali").mkdir()
    (repo / "kali" / "Dockerfile").write_text("FROM scratch\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "-m", "x",
        ],
        check=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    digests = {component: "sha256:" + "0" * 64 for component in images.COMPONENTS}
    built = manifest.build_manifest(repo, sha, digests)
    result = fingerprint.fingerprint(built)

    assert isinstance(result, str)
    assert len(result) == 64
    assert result != "0" * 64


def test_default_containers_names_the_compose_project() -> None:
    """`litellm` shares the agent container (D10); the rest are `<project>-<svc>-1`."""
    containers = images.default_containers("ph-dd131acc")
    assert containers["postgres"] == "ph-dd131acc-postgres-1"
    assert containers["neo4j"] == "ph-dd131acc-neo4j-1"
    assert containers["litellm"] == "ph-dd131acc-agent-1"
