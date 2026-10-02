"""The per-dataset helper: compose-derived images and canonical tags (spec #301)."""
from __future__ import annotations

from pathlib import Path

from orchestrator.dataset import BenchmarkDataset
from orchestrator.datasets import canonical_tag, parse_built_images
from orchestrator.datasets.base import DatasetHelper
from orchestrator.target_config import TargetConfiguration

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
    built = parse_built_images(COMPOSE)
    assert [item.service for item in built] == ["wordpress", "wpcli"]
    assert built[0].reference == "pentestbench-wordpress:php8.2-seeded-cage2"
    assert built[1].reference == "pentestbench-wordpress-cli:php8.2-isolated"


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
        "ph/webench/wordpress:wpcli",
    )


def test_declared_images_override_the_derivation(tmp_path):
    dataset = BenchmarkDataset(id="webench", repo="r", targets=("t",), eval_root=tmp_path)
    helper = DatasetHelper(dataset)
    config = TargetConfiguration(
        target="t", runner="targetctl", compose="c.yml", images=("ph/webench/t:only",)
    )
    assert helper.canonical_tags("t", config) == ("ph/webench/t:only",)


def test_helper_defaults_readiness_to_compose_health(tmp_path):
    bank = tmp_path / "platform" / "webench" / "t"
    bank.mkdir(parents=True)
    (bank / "c.yml").write_text(COMPOSE, encoding="utf-8")
    dataset = BenchmarkDataset(
        id="webench", repo="r", platform_root=str(bank.parent), targets=("t",), eval_root=tmp_path
    )
    config = TargetConfiguration(target="t", runner="targetctl", compose="c.yml")
    plan = DatasetHelper(dataset).readiness_plan("t", config, project="ph-x")
    assert plan.kind == "compose"
    assert "compose" in " ".join(plan.probe.argv)
