"""Docker image primitives - inspect, pull, build, tag, remove (spec #301).

Provisioning follows the precedence store -> pull -> build over a target's
canonical tags: a local `docker image inspect` hit is left alone, a declared pull
reference is pulled and bound to the tag, and otherwise the target's own build
produces the image which is bound with `docker tag`. These predicates exercise
the reference join, the pull-progress parse, the binding, the verify gate, and
the failure labels with no live docker.
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


def test_registry_reference_tags_by_target_and_service():
    """D48: the registry reference is `<registry>:<target>-<service>`, the tag
    the CI image workflow pushes."""
    assert (
        docker.registry_reference("ghcr.io/diekgbbtt/webench", "siyucms", "web")
        == "ghcr.io/diekgbbtt/webench:siyucms-web"
    )
    assert docker.registry_reference("ghcr.io/diekgbbtt/webench/", "ofbiz", "ofbiz") == (
        "ghcr.io/diekgbbtt/webench:ofbiz-ofbiz"
    )
    # An empty registry yields nothing, so the caller falls back to build.
    assert docker.registry_reference("", "siyucms", "web") == ""


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

    assert docker.remove(runner, "ph/webench/t:web") == (
        "reclaim ph/webench/t:web failed: image is in use",
    )


def test_remove_ok_binds_a_canonical_tag_label(recording_runner, fake_result):
    runner = recording_runner({"image rm": fake_result(0)})

    assert docker.remove(runner, "ph/webench/t:web") == ("rm ph/webench/t:web",)


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


def test_plan_tag_binds_source_to_canonical():
    command = docker.plan_tag("pentestbench-a:1", "ph/webench/a:web")

    assert command.argv == ("docker", "tag", "pentestbench-a:1", "ph/webench/a:web")


def test_present_none_when_absent(recording_runner, fake_result):
    runner = recording_runner({"image inspect": fake_result(1, stderr="No such image")})

    assert docker.present(runner, "pentestbench-a:1") is None


# --- the canonical-tag precedence: store -> pull -> build ---------------------


def test_provision_tags_leaves_a_store_hit_alone(recording_runner, fake_result):
    runner = recording_runner({"image inspect": fake_result(0, stdout="sha256:x\n")})

    outcomes = docker.provision_tags(
        runner, ("ph/webench/a:web",), pull_refs={"ph/webench/a:web": "reg/a:web"}
    )

    assert [(o.tag, o.source) for o in outcomes] == [("ph/webench/a:web", docker.PRESENT)]
    # A store hit is never pulled, rebuilt, or tagged: only the store check ran.
    assert runner.argv_texts == ["docker image inspect --format {{.Id}} ph/webench/a:web"]


def test_provision_tags_pulls_and_binds_the_canonical_tag(recording_runner, fake_result):
    runner = recording_runner(
        {
            "reg/a:web": fake_result(0, stdout="sha256:pulled\n"),
            "image inspect": fake_result(1, stderr="No such image"),
            "docker pull": fake_result(0, stdout="pulled"),
        }
    )

    outcomes = docker.provision_tags(
        runner, ("ph/webench/a:web",), pull_refs={"ph/webench/a:web": "reg/a:web"}
    )

    assert [(o.tag, o.source, o.reference) for o in outcomes] == [
        ("ph/webench/a:web", docker.PULL, "reg/a:web")
    ]
    assert "docker tag reg/a:web ph/webench/a:web" in runner.argv_texts


def test_provision_tags_builds_and_binds_when_no_pull(recording_runner, fake_result):
    runner = recording_runner({"image inspect": fake_result(1, stderr="No such image")})

    outcomes = docker.provision_tags(
        runner,
        ("ph/webench/a:web",),
        build=lambda: {"ph/webench/a:web": "pentestbench-a:1"},
    )

    assert [(o.tag, o.source, o.reference) for o in outcomes] == [
        ("ph/webench/a:web", docker.BUILD, "pentestbench-a:1")
    ]
    assert runner.argv_texts[-1] == "docker tag pentestbench-a:1 ph/webench/a:web"


def test_provision_tags_does_not_build_when_the_store_hits(recording_runner, fake_result):
    runner = recording_runner({"image inspect": fake_result(0, stdout="sha256:x\n")})
    built: list[bool] = []

    def build():
        built.append(True)
        return {"ph/webench/a:web": "pentestbench-a:1"}

    docker.provision_tags(runner, ("ph/webench/a:web",), build=build)

    assert built == []


def test_provision_tags_fails_hard_when_absent_with_no_source(recording_runner, fake_result):
    runner = recording_runner({"image inspect": fake_result(1, stderr="No such image")})

    with pytest.raises(docker.ImagePrimitiveError, match="no pull reference"):
        docker.provision_tags(runner, ("ph/webench/a:web",))


def test_provision_tags_applies_the_precedence_per_tag(recording_runner, fake_result):
    runner = recording_runner(
        {
            "ph/webench/a:web": fake_result(0, stdout="sha256:pa\n"),
            "reg/b:web": fake_result(0, stdout="sha256:pb\n"),
            "image inspect": fake_result(1, stderr="No such image"),
            "docker pull": fake_result(0, stdout="pulled"),
        }
    )

    outcomes = docker.provision_tags(
        runner,
        ("ph/webench/a:web", "ph/webench/b:web"),
        pull_refs={"ph/webench/b:web": "reg/b:web"},
    )

    assert [(o.tag, o.source) for o in outcomes] == [
        ("ph/webench/a:web", docker.PRESENT),
        ("ph/webench/b:web", docker.PULL),
    ]
