"""The per-dataset helper: compose-derived images and canonical tags (spec #301)."""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.dataset import BenchmarkDataset
from orchestrator.datasets import canonical_tag, parse_built_images
from orchestrator.datasets.base import DatasetHelper, parse_target_ports
from orchestrator.target_config import TargetConfiguration, load_target_configuration

COMPOSE = """\
name: pb_wordpress
services:
  db:
    image: mysql:5.7
    restart: unless-stopped
  wordpress:
    build:
      context: ./setup_files
      dockerfile: environment/Dockerfile.wp-app
    image: pentestbench-wordpress:php8.2-seeded-cage2
    restart: unless-stopped
  wpcli:
    build:
      context: ./setup_files
      dockerfile: environment/Dockerfile.wp-cli
    image: "pentestbench-wordpress-cli:php8.2-isolated"
    profiles: ["cli"]
"""


def test_parse_built_images_only_build_services():
    # `wpcli` declares `profiles: [cli]`, so `docker compose config`/`build`
    # leave it out of the target's default stack; it is not a built image.
    built = parse_built_images(COMPOSE)
    assert [item.service for item in built] == ["wordpress"]
    assert built[0].reference == "pentestbench-wordpress:php8.2-seeded-cage2"


def test_parse_built_images_empty_when_no_build():
    assert parse_built_images("services:\n  db:\n    image: mysql:5.7\n") == ()


def test_canonical_tag_shape():
    assert canonical_tag("webexploitbench", "wordpress", "wpcli") == (
        "ph/webexploitbench/wordpress:wpcli"
    )


def test_helper_derives_canonical_tags_from_the_compose(tmp_path):
    bank = tmp_path / "platform" / "webench" / "wordpress"
    bank.mkdir(parents=True)
    (bank / "docker-compose.cage.yml").write_text(COMPOSE, encoding="utf-8")
    dataset = BenchmarkDataset(
        id="webench",
        repo="r",
        platform_root=str(tmp_path / "platform" / "webench"),
        targets=("wordpress",),
        eval_root=tmp_path,
    )
    helper = DatasetHelper(dataset)
    config = TargetConfiguration(
        target="wordpress", runner="targetctl", compose="docker-compose.cage.yml"
    )
    assert helper.compose_path("wordpress", config) == bank / "docker-compose.cage.yml"
    assert helper.canonical_tags("wordpress", config) == (
        "ph/webench/wordpress:wordpress",
    )


def test_declared_images_override_the_derivation(tmp_path):
    dataset = BenchmarkDataset(id="webench", repo="r", targets=("t",), eval_root=tmp_path)
    helper = DatasetHelper(dataset)
    config = TargetConfiguration(
        target="t", runner="targetctl", compose="c.yml", images=("ph/webench/t:only",)
    )
    assert helper.canonical_tags("t", config) == ("ph/webench/t:only",)


HEALTHCHECKED_COMPOSE = """\
name: pb_wordpress
services:
  db:
    image: mysql:5.7
  wordpress:
    build:
      context: ./setup_files
    image: pentestbench-wordpress:php8.2-seeded-cage2
    healthcheck:
      test: ["CMD", "true"]
"""


def _bank(tmp_path, compose: str = COMPOSE, challenge: str | None = None):
    bank = tmp_path / "platform" / "webench" / "t"
    bank.mkdir(parents=True)
    (bank / "c.yml").write_text(compose, encoding="utf-8")
    if challenge is not None:
        (bank / "challenge.json").write_text(challenge, encoding="utf-8")
    dataset = BenchmarkDataset(
        id="webench", repo="r", platform_root=str(bank.parent), targets=("t",), eval_root=tmp_path
    )
    return DatasetHelper(dataset)


def test_app_service_keys_come_from_challenge_json(tmp_path):
    helper = _bank(
        tmp_path,
        challenge='{"application_service_keys": ["api", "web"]}',
    )
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    assert helper.app_service_keys("t", config) == ("api", "web")


def test_app_service_keys_fall_back_to_built_services(tmp_path):
    """No challenge metadata: the compose's own built services stand in."""
    helper = _bank(tmp_path)
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    assert helper.app_service_keys("t", config) == ("wordpress",)


MULTI_SERVICE_COMPOSE = """\
name: pb_jetlinks
services:
  jetlinks:
    build:
      context: ./setup_files
    image: pentestbench-jetlinks:2.3.0-synthetic
  ui:
    build:
      context: ./setup_files
    image: pentestbench-jetlinks-ui:2.3.0
"""

MULTI_SERVICE_CHALLENGE = (
    '{"application_service_keys": ["jetlinks", "ui"], '
    '"target_ports": {"jetlinks": 8848, "ui": 80}}'
)


def test_parse_target_ports_reads_the_published_application_ports():
    assert parse_target_ports(MULTI_SERVICE_CHALLENGE) == {"jetlinks": 8848, "ui": 80}
    assert parse_target_ports("not json") == {}
    assert parse_target_ports('{"application_service_keys": ["a"]}') == {}


def test_multi_service_app_probes_each_published_application_service(tmp_path):
    """#323: the front's `/` is served by `ui` while the `jetlinks` backend
    boots, so a front-only HTTP probe reads ready too early. Every application
    service the challenge publishes gets its own published-port probe."""
    helper = _bank(tmp_path, compose=MULTI_SERVICE_COMPOSE, challenge=MULTI_SERVICE_CHALLENGE)
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    plan = helper.readiness_plan("t", config, project="web_t", host="t-abc.target")

    assert plan.kind == "composite"
    commands = plan.commands
    assert "Host: t-abc.target" in commands[0].argv
    assert "compose" in " ".join(commands[-1].argv)
    backends = {
        command.description: " ".join(command.argv)
        for command in commands
        if command.description.startswith("probe app port")
    }
    assert set(backends) == {"probe app port jetlinks", "probe app port ui"}, backends
    jetlinks = backends["probe app port jetlinks"]
    assert "docker compose -p web_t" in jetlinks
    assert "-f " in jetlinks
    assert "port jetlinks 8848" in jetlinks
    assert "port ui 80" in backends["probe app port ui"]


def test_no_target_ports_keeps_the_front_compose_composite(tmp_path):
    """Without the challenge's published-port metadata the plan cannot resolve a
    backend port; it keeps the front + compose composite, never dropping the
    assertion silently."""
    helper = _bank(
        tmp_path,
        compose=MULTI_SERVICE_COMPOSE,
        challenge='{"application_service_keys": ["jetlinks", "ui"]}',
    )
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    plan = helper.readiness_plan("t", config, project="web_t", host="t-abc.target")
    assert plan.kind == "composite"
    assert len(plan.commands) == 2


def test_helper_defaults_readiness_to_compose_health_when_app_is_healthchecked(tmp_path):
    """A compose whose application service declares a healthcheck can trust the
    compose poll alone."""
    helper = _bank(tmp_path, compose=HEALTHCHECKED_COMPOSE)
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    plan = helper.readiness_plan("t", config, project="ph-x", host="t-abc.target")
    assert plan.kind == "compose"
    argv = " ".join(plan.commands[0].argv)
    assert "compose" in argv


def test_helper_defaults_to_composite_when_app_has_no_healthcheck(tmp_path):
    """#325: a targetctl/compose target whose application service declares no
    healthcheck gets the composite plan - the front answer AND the stack health -
    so the boot window cannot read ready. No per-target opt-in is required."""
    helper = _bank(tmp_path)
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    plan = helper.readiness_plan("t", config, project="web_t", host="t-abc.target")

    assert plan.kind == "composite"
    front, compose = plan.commands
    assert "Host: t-abc.target" in front.argv
    assert "compose" in " ".join(compose.argv)


def test_challenge_app_service_with_no_healthcheck_forces_the_front(tmp_path):
    """The challenge's own `application_service_keys` are the authority: an app
    service with no healthcheck selects the front even when a support service is
    healthchecked (the class #325 reports)."""
    helper = _bank(
        tmp_path,
        compose=COMPOSE,
        challenge='{"application_service_keys": ["wordpress"]}',
    )
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    plan = helper.readiness_plan("t", config, project="web_t", host="t-abc.target")
    assert plan.kind == "composite"


def test_image_runner_probes_the_published_port(tmp_path):
    """A compose-less target has no stack to assert; it probes its port."""
    helper = _bank(tmp_path)
    config = TargetConfiguration(target="t", runner="image", image="x", port=18080)
    plan = helper.readiness_plan("t", config, project="ph-x", port=18080)
    assert plan.kind == "http"
    assert "18080" in " ".join(plan.commands[0].argv)


def test_http_probe_falls_back_to_the_port_when_no_host(tmp_path):
    """The port branch is the explicit fallback for a caller with no synthetic
    host; it must not be a silent skip."""
    helper = _bank(tmp_path)
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    plan = helper.readiness_plan("t", config, project="web_t", port=12345)
    front, _compose = plan.commands
    assert "12345" in " ".join(front.argv)


def test_named_http_checker_is_composite_with_the_stack(tmp_path):
    """#325 finding 5: the named `http` checker keeps the stack assertion, so a
    declared HTTP contract cannot silently drop the support services."""
    helper = _bank(tmp_path)
    config = TargetConfiguration(
        target="t", runner="targetctl", compose="c.yml", checker="http"
    )
    plan = helper.readiness_plan("t", config, project="web_t", host="t-abc.target")

    assert plan.kind == "composite"
    front, compose = plan.commands
    assert "Host: t-abc.target" in front.argv
    assert "compose" in " ".join(compose.argv)


def test_named_http_checker_also_probes_each_application_service(tmp_path):
    """The named `http` checker keeps every application service asserted, not
    just the front root, for a multi-service no-healthcheck application."""
    helper = _bank(tmp_path, compose=MULTI_SERVICE_COMPOSE, challenge=MULTI_SERVICE_CHALLENGE)
    config = TargetConfiguration(
        target="t", runner="targetctl", compose="c.yml", checker="http"
    )
    plan = helper.readiness_plan("t", config, project="web_t", host="t-abc.target")
    assert "probe app port jetlinks" in [c.description for c in plan.commands]


def test_unknown_named_checker_fails_loud(tmp_path):
    """A misspelled checker must not silently fall back to compose health."""
    helper = _bank(tmp_path)
    config = TargetConfiguration(
        target="t", runner="targetctl", compose="c.yml", checker="htpp"
    )
    with pytest.raises(ValueError, match="htpp"):
        helper.readiness_plan("t", config, project="web_t", host="t-abc.target")


def test_webexploitbench_targets_declare_no_checker():
    """#325: the readiness contract is defaulted, not opted into per target, so
    the shipped WebExploitBench target configs carry no `checker`."""
    root = Path(__file__).resolve().parents[2]
    for name in ("comfyui", "jetlinks"):
        config = load_target_configuration(
            root / "eval" / "targets" / "webexploitbench" / f"{name}.yaml"
        )
        assert config.checker is None
