"""Docker image primitives - pull, monitor, verify, remove.

The chain pulls each target's image (composed from the dataset registry and the
target's identifier) and confirms it with `docker image inspect`, so a
provisioned image is verified present, never assumed. Removal is best-effort.
These predicates exercise the reference join, the pull-progress parse, the
verify gate, and the failure labels with no live docker.
"""
from __future__ import annotations

import pytest

from orchestrator import docker


def test_pull_reference_joins_registry_and_image():
    assert (
        docker.pull_reference("ghcr.io/acr/webench", "pentestbench-comfyui-web:latest")
        == "ghcr.io/acr/webench/pentestbench-comfyui-web:latest"
    )


def test_pull_reference_tolerates_slashes_and_empty_registry():
    assert docker.pull_reference("ghcr.io/acr/", "/x:1") == "ghcr.io/acr/x:1"
    assert docker.pull_reference("", "mysql:8.0") == "mysql:8.0"


def test_parse_pulled_digest():
    digest = "sha256:" + "a" * 64
    assert docker.parse_pulled_digest(f"Status: Downloaded\nDigest: {digest}\n") == digest
    assert docker.parse_pulled_digest("no digest here") is None


def test_parse_completed_layers():
    output = "cafe01234567: Pull complete\n111222333444: Already exists\nzzz: Waiting\n"
    assert docker.parse_completed_layers(output) == ("cafe01234567", "111222333444")


def test_pull_monitors_progress_and_verifies(recording_runner, fake_result):
    digest = "sha256:" + "b" * 64
    runner = recording_runner(
        {
            "docker pull": fake_result(
                0, stderr=f"Digest: {digest}\ncafe01234567: Pull complete\n"
            ),
            "image inspect": fake_result(0, stdout="sha256:imageid\n"),
        }
    )

    outcome = docker.pull(runner, "reg/pentestbench-comfyui-web:latest")

    assert outcome.reference == "reg/pentestbench-comfyui-web:latest"
    assert outcome.image_id == "sha256:imageid"
    assert outcome.digest == digest
    assert outcome.layers == ("cafe01234567",)
    assert runner.argv_texts[0] == "docker pull reg/pentestbench-comfyui-web:latest"
    assert "image inspect" in runner.argv_texts[1]


def test_pull_raises_when_verify_finds_no_image(recording_runner, fake_result):
    runner = recording_runner(
        {"docker pull": fake_result(0), "image inspect": fake_result(0, stdout="")}
    )

    with pytest.raises(docker.ImagePrimitiveError, match="no image id"):
        docker.pull(runner, "reg/x:latest")


def test_pull_raises_on_pull_failure(recording_runner, fake_result):
    runner = recording_runner({"docker pull": fake_result(1, stderr="denied")})

    with pytest.raises(docker.ImagePrimitiveError, match="denied"):
        docker.pull(runner, "reg/x:latest")


def test_remove_reports_a_failure_label(recording_runner, fake_result):
    runner = recording_runner({"image rm": fake_result(1, stderr="image is in use")})

    assert docker.remove(runner, "reg/x:latest") == (
        "reclaim reg/x:latest failed: image is in use",
    )


def test_remove_ok(recording_runner, fake_result):
    runner = recording_runner({"image rm": fake_result(0)})

    assert docker.remove(runner, "reg/x:latest") == ("rm reg/x:latest",)


def test_build_tags_with_reference_and_verifies(recording_runner, fake_result):
    runner = recording_runner(
        {
            "docker build": fake_result(0),
            "image inspect": fake_result(0, stdout="sha256:built\n"),
        }
    )

    outcome = docker.build(
        runner, "pentestbench-a:1", dockerfile="setup_files/environment/Dockerfile"
    )

    assert outcome.image_id == "sha256:built"
    build_argv = runner.argv_texts[0]
    assert "docker build -t pentestbench-a:1" in build_argv
    assert "-f setup_files/environment/Dockerfile" in build_argv
    assert build_argv.endswith("setup_files/environment")


def test_present_none_when_absent(recording_runner, fake_result):
    runner = recording_runner({"image inspect": fake_result(1, stderr="No such image")})

    assert docker.present(runner, "pentestbench-a:1") is None


def test_provision_images_builds_first_and_requires_the_rest(recording_runner, fake_result):
    runner = recording_runner(
        {
            "docker build": fake_result(0),
            "image inspect": fake_result(0, stdout="sha256:x\n"),
        }
    )

    outcomes = docker.provision_images(
        runner,
        ("pentestbench-a:1", "pentestbench-a-helper:1"),
        dockerfile="setup_files/environment/Dockerfile",
    )

    assert [o.path for o in outcomes] == [docker.BUILD, docker.PRESENT]
    assert outcomes[0].reference == "pentestbench-a:1"


def test_provision_images_pulls_all_when_a_registry_is_configured(recording_runner, fake_result):
    runner = recording_runner(
        {
            "docker pull": fake_result(0),
            "image inspect": fake_result(0, stdout="sha256:x\n"),
        }
    )

    outcomes = docker.provision_images(
        runner, ("a:1", "b:2"), registry="ghcr.io/acr/webench"
    )

    assert [o.path for o in outcomes] == [docker.PULL, docker.PULL]
    assert outcomes[0].reference == "ghcr.io/acr/webench/a:1"


def test_provision_images_fails_hard_when_absent_with_no_recipe(recording_runner, fake_result):
    runner = recording_runner({"image inspect": fake_result(1, stderr="No such image")})

    with pytest.raises(docker.ImagePrimitiveError, match="not present locally"):
        docker.provision_images(runner, ("pentestbench-a:1",))


def test_provisioned_references_mirrors_the_precedence():
    assert docker.provisioned_references(
        ("a:1", "b:2"), dockerfile="Dockerfile"
    ) == ("a:1", "b:2")
    assert docker.provisioned_references(
        ("a:1", "b:2"), registry="reg"
    ) == ("reg/a:1", "reg/b:2")
    assert docker.provisioned_references(("a:1",)) == ("a:1",)
